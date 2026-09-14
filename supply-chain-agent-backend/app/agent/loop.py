"""The recovery agent loop, with guardrails.

Orchestration only. The loop decides *when* to call a tool and records what came
back; it never computes a cost, a delivery time or a carbon figure (that lives
in the Step 5 optimizer behind ``optimize_recovery``) and it never supplies a
number of its own (the shortage and deadline handed to the optimizer are copied
straight out of ``get_demand``).

The prescribed phases:

1. :meth:`RecoveryAgent.observe`      — ``get_demand``, ``get_shipments``, ``get_routes``
2. :meth:`RecoveryAgent.detect`       — is ``constraint_violated`` true?
3. :meth:`RecoveryAgent.investigate`  — ``get_vendors``, ``get_inventory``, ``get_routes``
4. :meth:`RecoveryAgent.optimize`     — ``optimize_recovery`` with the observed shortage/deadline
5. :meth:`RecoveryAgent.execute`      — the tool behind the authorized decision
6. :meth:`RecoveryAgent.verify`       — ``verify_state``; replan on failure, capped

Four guardrails sit on top of those phases, and each is an explicit code path
rather than something left to judgement:

**Grounding.** :meth:`RecoveryAgent._explain` never trusts the first draft. It
runs :func:`~app.agent.explain.ungrounded_numbers` over the prose and, if a
figure is absent from the trace, discards it and regenerates once with
:data:`~app.agent.constants.GROUNDING_INSTRUCTION`; only if that fails does the
deterministic template produce the final text. The pass is recorded in the trace
and summarised as a :class:`~app.agent.explain.GroundingReport`.

**No silent action.** A state-changing tool is only ever reached via a
:class:`~app.agent.decision.ActionDecision` that was validated as structured JSON
*and* then authorised by :meth:`RecoveryAgent._authorise`, which refuses anything
that does not name the optimizer's top-ranked feasible option from this cycle.
A refusal is logged and no mutating tool runs.

**Refuse if uncertain.** When the optimizer returns no feasible option the loop
breaks immediately with :data:`~app.agent.constants.NO_FEASIBLE_MESSAGE` — it
cannot force a choice, because no decision is ever requested in that branch.

**Bounded autonomy.** At most :data:`~app.agent.constants.MAX_REPLAN_CYCLES`
replan cycles and at most :data:`~app.agent.constants.MAX_TOOL_CALLS_PER_CYCLE`
tool calls per cycle; exceeding either stops the run with a distinct outcome.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.constants import (
    GROUNDING_INSTRUCTION,
    MAX_REPLAN_CYCLES,
    MAX_TOOL_CALLS_PER_CYCLE,
    NO_FEASIBLE_MESSAGE,
)
from app.agent.decision import ActionDecision, ActionSelector, TopRankedSelector
from app.agent.explain import (
    Explainer,
    ExplainerError,
    ExplainerUnavailable,
    ExplanationContext,
    GroundingReport,
    TemplateExplainer,
    choose_explainer,
    ungrounded_numbers,
)
from app.agent.tools import Toolbox, ToolResult
from app.agent.trace import AgentOutcome, AgentPhase, ReasoningTrace
from app.models import Actor
from app.services.audit_log_service import record

__all__ = [
    "MAX_REPLAN_CYCLES",
    "MAX_TOOL_CALLS_PER_CYCLE",
    "AgentRun",
    "RecoveryAgent",
    "ToolCallLimitExceeded",
    "run_recovery_agent",
]


class ToolCallLimitExceeded(RuntimeError):
    """Raised when a cycle exhausts its tool-call budget."""


def _jsonable(value: Any) -> Any:
    """Keep a value renderable in the trace, whatever a selector returned."""
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass
class AgentRun:
    """The result of one agent run: outcome, explanation, trace and guardrails."""

    run_id: str
    outcome: AgentOutcome
    explanation: str
    trace: ReasoningTrace
    demand: Dict[str, Any]
    plan: Optional[Dict[str, Any]] = None
    verify: Optional[Dict[str, Any]] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    replan_cycles: int = 0
    tool_calls: int = 0
    grounding: Optional[GroundingReport] = None
    audit_log_ids: List[int] = field(default_factory=list)


class RecoveryAgent:
    """Runs the observe → detect → investigate → optimize → decide → execute → verify loop."""

    def __init__(
        self,
        toolbox: Toolbox,
        *,
        max_replans: int = MAX_REPLAN_CYCLES,
        explainer: Optional[Explainer] = None,
        selector: Optional[ActionSelector] = None,
    ) -> None:
        self.toolbox = toolbox
        #: Never above the hard cap.
        self.max_replans = max(0, min(max_replans, MAX_REPLAN_CYCLES))
        self.explainer: Explainer = explainer or TemplateExplainer()
        self.selector: ActionSelector = selector or TopRankedSelector()
        self.trace = ReasoningTrace()
        #: Tool calls across the whole run, and within the current cycle.
        self.tool_calls = 0
        self._cycle_tool_calls = 0
        #: Set by ``optimize`` so ``_authorise`` can insist the decision matches.
        self._optimized_this_cycle = False
        self._top_option: Optional[Dict[str, Any]] = None

    # --- phase 1: observe --------------------------------------------------
    def observe(self) -> Dict[str, Any]:
        """Read the current demand picture plus the shipments and routes."""
        return {
            "demand": self._call(AgentPhase.OBSERVE, "get_demand").data,
            "shipments": self._call(AgentPhase.OBSERVE, "get_shipments").data,
            "routes": self._call(AgentPhase.OBSERVE, "get_routes").data,
        }

    # --- phase 2: detect ---------------------------------------------------
    def detect(self, demand: Dict[str, Any]) -> bool:
        """Whether the demand view reports a violated constraint."""
        violated = bool(demand["constraint_violated"])
        self.trace.add(
            AgentPhase.DETECT,
            result={
                "constraint_violated": demand["constraint_violated"],
                "shortage": demand["shortage"],
                "constraint_violations": demand["constraint_violations"],
            },
            note=(
                "constraint_violated=true, investigating recovery options"
                if violated
                else "constraint_violated=false, no action needed"
            ),
        )
        return violated

    # --- phase 3: investigate ---------------------------------------------
    def investigate(self) -> Dict[str, Any]:
        """Read the alternatives available to recover."""
        return {
            "vendors": self._call(AgentPhase.INVESTIGATE, "get_vendors").data,
            "inventory": self._call(AgentPhase.INVESTIGATE, "get_inventory").data,
            "routes": self._call(AgentPhase.INVESTIGATE, "get_routes").data,
        }

    # --- phase 4: optimize -------------------------------------------------
    def optimize(self, demand: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ask the optimizer to rank options, using the observed numbers as-is."""
        result = self._call(
            AgentPhase.OPTIMIZE,
            "optimize_recovery",
            shortage_quantity=demand["shortage"],
            deadline=demand["deadline"],
        )
        plan = result.data
        options = (plan or {}).get("options", [])
        # Remember the ranking this cycle is allowed to act on.
        self._optimized_this_cycle = True
        self._top_option = options[0] if options else None
        return plan

    # --- structured decision ----------------------------------------------
    def decide(self, plan: Dict[str, Any]) -> Optional[ActionDecision]:
        """Ask the selector for a decision and validate it as structured JSON.

        Guardrail: *structured output only*. Free text, a malformed payload or a
        missing field cannot become an action — only a validated
        :class:`ActionDecision` is returned.
        """
        try:
            raw = self.selector.choose(plan)
        except Exception as exc:  # a selector must not be able to crash the run
            self.trace.add(
                AgentPhase.DECIDE,
                result={"error": str(exc)},
                note="selector failed; no decision produced",
            )
            return None

        try:
            decision = ActionDecision.model_validate(raw)
        except ValidationError as exc:
            self.trace.add(
                AgentPhase.DECIDE,
                result={"raw": _jsonable(raw), "errors": str(exc)},
                note="decision failed schema validation; no tool call authorised",
            )
            return None

        self.trace.add(
            AgentPhase.DECIDE,
            result=decision.model_dump(),
            note="decision validated as structured JSON",
        )
        return decision

    # --- phase 5: execute --------------------------------------------------
    def execute(self, decision: ActionDecision, demand: Dict[str, Any]) -> ToolResult:
        """Run the tool behind an authorized decision."""
        tool, arguments = self._tool_for(decision, demand)
        return self._call(AgentPhase.EXECUTE, tool, **arguments)

    # --- phase 6: verify ---------------------------------------------------
    def verify(self) -> Optional[Dict[str, Any]]:
        """Re-read demand and routes and report whether the requirement is met."""
        return self._call(AgentPhase.VERIFY, "verify_state").data

    # --- orchestration -----------------------------------------------------
    def run(self) -> AgentRun:
        run_id = str(uuid4())
        observed = self.observe()
        observed_demand = observed["demand"]
        demand = observed_demand

        plan: Optional[Dict[str, Any]] = None
        verify: Optional[Dict[str, Any]] = None
        actions: List[Dict[str, Any]] = []
        audit_log_ids: List[int] = []
        refused: Set[Tuple[str, int]] = set()
        replan_cycles = 0

        if self.detect(observed_demand):
            try:
                while True:
                    self._start_cycle()
                    self.investigate()
                    plan = self.optimize(demand)
                    options = (plan or {}).get("options", [])

                    if not options:
                        # Guardrail: refuse if uncertain. No decision is even
                        # requested, so no action can be forced or invented.
                        self.trace.add(
                            AgentPhase.GUARDRAIL,
                            result={
                                "options": [],
                                "excluded": (plan or {}).get("excluded", []),
                            },
                            note=NO_FEASIBLE_MESSAGE,
                        )
                        outcome = AgentOutcome.NO_FEASIBLE_OPTION
                        break

                    top = options[0]
                    signature = (top["action"], top["reference_id"])
                    if signature in refused:
                        self.trace.add(
                            AgentPhase.GUARDRAIL,
                            result={
                                "action": top["action"],
                                "reference_id": top["reference_id"],
                            },
                            note=(
                                "top-ranked action was already refused; stopping "
                                "instead of repeating it"
                            ),
                        )
                        outcome = AgentOutcome.ACTION_REJECTED
                        break

                    decision = self.decide(plan)
                    if decision is None:
                        outcome = AgentOutcome.DECISION_REJECTED
                        break

                    rejection = self._authorise(decision)
                    if rejection is not None:
                        # Guardrail: no silent action. The decision did not match
                        # the optimizer's ranking, so it is refused and logged.
                        self.trace.add(
                            AgentPhase.GUARDRAIL,
                            result={
                                "decision": decision.model_dump(),
                                "top_option": {
                                    "action": top["action"],
                                    "reference_id": top["reference_id"],
                                    "quantity": top["quantity"],
                                },
                            },
                            note=f"decision refused: {rejection}",
                        )
                        outcome = AgentOutcome.DECISION_REJECTED
                        break

                    execution = self.execute(decision, demand)
                    actions.append(
                        {
                            "tool": execution.name,
                            "arguments": self.trace.steps[-1].arguments,
                            "ok": execution.ok,
                            "error": execution.error,
                            "reason": execution.reason,
                            "result": execution.data,
                        }
                    )
                    if execution.ok:
                        audit_id = self._audit_id(execution.data)
                        if audit_id is not None:
                            audit_log_ids.append(audit_id)
                    else:
                        refused.add(signature)

                    verify = self.verify()
                    if execution.ok and verify and verify["satisfied"]:
                        outcome = AgentOutcome.RESOLVED
                        break

                    replan_cycles += 1
                    if replan_cycles > self.max_replans:
                        outcome = AgentOutcome.REPLAN_LIMIT_REACHED
                        break

                    # Replan from the freshest real numbers, not from memory.
                    demand = verify["demand"] if verify else demand
            except ToolCallLimitExceeded as exc:
                self.trace.add(AgentPhase.GUARDRAIL, note=str(exc))
                outcome = AgentOutcome.TOOL_CALL_LIMIT_REACHED

        else:
            outcome = AgentOutcome.NO_ACTION_NEEDED

        context = ExplanationContext(
            outcome=outcome,
            demand=observed_demand,
            plan=plan,
            verify=verify,
            actions=actions,
            replan_cycles=replan_cycles,
            trace=self.trace,
        )
        explanation, grounding = self._explain(context)
        self.trace.add(
            AgentPhase.GUARDRAIL,
            result={
                "attempts": grounding.attempts,
                "rejected_numbers": grounding.rejected_numbers,
                "regenerated": grounding.regenerated,
                "fallback_used": grounding.fallback_used,
                "fallback_reason": grounding.fallback_reason,
            },
            note="grounding validation pass over the final explanation",
        )
        audit_log_ids.append(
            self._log_run(run_id, outcome, replan_cycles, actions, verify, grounding)
        )

        return AgentRun(
            run_id=run_id,
            outcome=outcome,
            explanation=explanation,
            trace=self.trace,
            demand=observed_demand,
            plan=plan,
            verify=verify,
            actions=actions,
            replan_cycles=replan_cycles,
            tool_calls=self.tool_calls,
            grounding=grounding,
            audit_log_ids=audit_log_ids,
        )

    # --- helpers -----------------------------------------------------------
    def _start_cycle(self) -> None:
        """Reset the per-cycle budget and the ranking this cycle may act on."""
        self._cycle_tool_calls = 0
        self._optimized_this_cycle = False
        self._top_option = None

    def _call(self, phase: AgentPhase, name: str, **arguments: Any) -> ToolResult:
        """Invoke a tool and record the call and its raw result in the trace.

        Guardrail: *bounded autonomy*. The per-cycle budget is checked before the
        call, so a cycle can never exceed it.
        """
        if self._cycle_tool_calls >= MAX_TOOL_CALLS_PER_CYCLE:
            raise ToolCallLimitExceeded(
                f"per-cycle tool-call budget of {MAX_TOOL_CALLS_PER_CYCLE} exhausted"
            )
        self._cycle_tool_calls += 1
        self.tool_calls += 1

        result = self.toolbox.call(name, **arguments)
        recorded = result.data if result.ok else {
            "error": result.error,
            "reason": result.reason,
        }
        self.trace.add(
            phase,
            tool=name,
            arguments=arguments,
            result=recorded,
            note=None if result.ok else f"refused: {result.error} ({result.reason})",
        )
        return result

    def _authorise(self, decision: ActionDecision) -> Optional[str]:
        """Return why ``decision`` may not be executed, or ``None`` if it may.

        Guardrail: *no silent action*. A state-changing tool is only reachable
        when ``optimize_recovery`` ran in this same cycle and the decision names
        its top-ranked feasible option, target and quantity included.
        """
        if not self._optimized_this_cycle:
            return "no optimize_recovery call in this reasoning cycle"
        if self._top_option is None:
            return "no top-ranked feasible option to match"

        expected = (self._top_option["action"], self._top_option["reference_id"])
        actual = (decision.action, decision.params.reference_id)
        if actual != expected:
            return (
                f"decision {actual} does not match optimize_recovery's top-ranked "
                f"feasible option {expected}"
            )
        if decision.params.quantity != self._top_option["quantity"]:
            return (
                f"decision quantity {decision.params.quantity} does not match the "
                f"top-ranked quantity {self._top_option['quantity']}"
            )
        # For reroute decisions, the new route must match the optimizer's pick.
        if decision.action == "reroute_shipment":
            expected_route = self._top_option.get("route_id")
            actual_route = decision.params.new_route_id
            if expected_route is not None and actual_route != expected_route:
                return (
                    f"decision new_route_id {actual_route} does not match the "
                    f"top-ranked route_id {expected_route}"
                )
        return None

    @staticmethod
    def _tool_for(
        decision: ActionDecision, demand: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        """Map an authorized decision onto the tool that carries it out."""
        reference_id = decision.params.reference_id
        quantity = decision.params.quantity
        if decision.action == "warehouse_transfer":
            return "transfer_inventory", {
                "from_id": reference_id,
                "to_id": demand["dealer_id"],
                "quantity": quantity,
            }
        if decision.action == "vendor_purchase":
            return "purchase_from_vendor", {
                "vendor_id": reference_id,
                "quantity": quantity,
            }
        if decision.action == "reroute_shipment":
            return "reroute_shipment", {
                "shipment_id": decision.params.shipment_id,
                "new_route_id": decision.params.new_route_id,
            }
        raise ValueError(f"no tool implements action {decision.action!r}")

    @staticmethod
    def _audit_id(data: Any) -> Optional[int]:
        if isinstance(data, dict):
            return data.get("audit_log_id")
        return None

    def _explain(
        self, context: ExplanationContext
    ) -> Tuple[str, GroundingReport]:
        """Produce the final text, regenerating once if it is not grounded.

        Guardrail: *grounding*. Attempt one is whatever the explainer returns;
        if any number in it is absent from the trace, the answer is discarded and
        the explainer is asked again with an explicit instruction. If that also
        fails, the deterministic template produces the text.
        """
        rejected: List[List[str]] = []
        attempts = 0
        fallback_reason: Optional[str] = None

        for correction in (None, GROUNDING_INSTRUCTION):
            attempts += 1
            try:
                text = self.explainer.explain(context, correction=correction)
            except ExplainerUnavailable as exc:
                # Infrastructure problem, not a grounding failure: go straight
                # to the template rather than asking a dead explainer twice.
                fallback_reason = str(exc)
                break
            except ExplainerError as exc:
                fallback_reason = str(exc)
                continue

            ungrounded = ungrounded_numbers(text, context.trace)
            if not ungrounded:
                return text, GroundingReport(
                    attempts=attempts,
                    rejected_numbers=rejected,
                    regenerated=correction is not None,
                    fallback_used=False,
                )
            rejected.append(ungrounded)

        return (
            TemplateExplainer().explain(context),
            GroundingReport(
                attempts=attempts,
                rejected_numbers=rejected,
                regenerated=False,
                fallback_used=True,
                fallback_reason=fallback_reason,
            ),
        )

    def _log_run(
        self,
        run_id: str,
        outcome: AgentOutcome,
        replan_cycles: int,
        actions: Sequence[Dict[str, Any]],
        verify: Optional[Dict[str, Any]],
        grounding: GroundingReport,
    ) -> int:
        entry = record(
            self.toolbox.db,
            actor=Actor.AGENT,
            action_type="agent_recovery_run",
            details={
                "run_id": run_id,
                "outcome": outcome.value,
                "replan_cycles": replan_cycles,
                "tool_calls": self.tool_calls,
                "executed": [
                    {
                        "tool": action["tool"],
                        "arguments": action["arguments"],
                        "ok": action["ok"],
                    }
                    for action in actions
                ],
                "satisfied": None if verify is None else verify["satisfied"],
                "grounding": {
                    "attempts": grounding.attempts,
                    "rejected_numbers": grounding.rejected_numbers,
                    "regenerated": grounding.regenerated,
                    "fallback_used": grounding.fallback_used,
                },
                "trace_steps": len(self.trace.steps),
            },
            result=outcome.value,
        )
        return entry.id


def run_recovery_agent(
    db: Session,
    *,
    max_replans: int = MAX_REPLAN_CYCLES,
    explainer: Optional[Explainer] = None,
    selector: Optional[ActionSelector] = None,
) -> AgentRun:
    """Run one recovery pass over the current database state."""
    agent = RecoveryAgent(
        Toolbox(db),
        max_replans=max_replans,
        explainer=explainer or choose_explainer(),
        selector=selector,
    )
    return agent.run()
