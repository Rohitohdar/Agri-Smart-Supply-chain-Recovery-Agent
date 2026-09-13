"""Request and response schemas for the agent endpoints.

The run response is deliberately verbose: the frontend gets the agent's prose,
the full reasoning trace (every tool call with its raw JSON result), the plan it
ranked and the verification it finished on — so nothing the agent says has to be
taken on trust.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import Field

from app.agent.constants import MAX_REPLAN_CYCLES
from app.agent.trace import AgentOutcome, AgentPhase
from app.schemas.common import ORMModel

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from app.agent.loop import AgentRun


class AgentRunRequest(ORMModel):
    """Body for ``POST /agent/recover``."""

    max_replans: Optional[int] = Field(
        default=None,
        ge=0,
        le=MAX_REPLAN_CYCLES,
        description=(
            "Replan cycles allowed before giving up. Defaults to the hard cap "
            f"of {MAX_REPLAN_CYCLES} and can only be lowered."
        ),
    )


class TraceStepRead(ORMModel):
    """One recorded step: a tool call or a decision."""

    index: int
    phase: AgentPhase
    tool: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    #: The tool's raw JSON result, unmodified.
    result: Any = None
    note: Optional[str] = None


class AgentActionRead(ORMModel):
    """One executed (or refused) mutating action."""

    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error: Optional[str] = None
    reason: Optional[str] = None
    result: Any = None


class GroundingReportRead(ORMModel):
    """What the grounding validation pass did before the prose was shown."""

    attempts: int
    #: Numbers rejected per failed attempt (empty when the first attempt passed).
    rejected_numbers: List[List[str]] = Field(default_factory=list)
    #: True when the accepted text came from the corrected re-ask.
    regenerated: bool = False
    #: True when the configured explainer failed and the template produced the text.
    fallback_used: bool = False
    #: Why the fallback happened; None when the LLM wrote the text.
    fallback_reason: Optional[str] = None


class AgentRunResponse(ORMModel):
    """Everything one agent run produced."""

    run_id: str
    outcome: AgentOutcome
    explanation: str
    replan_cycles: int
    #: Total tool calls made across the run (each cycle is separately capped).
    tool_calls: int = 0
    grounding: Optional[GroundingReportRead] = None
    observed_demand: Dict[str, Any]
    plan: Optional[Dict[str, Any]] = None
    verify: Optional[Dict[str, Any]] = None
    actions: List[AgentActionRead] = Field(default_factory=list)
    audit_log_ids: List[int] = Field(default_factory=list)
    trace: List[TraceStepRead] = Field(default_factory=list)

    @classmethod
    def from_run(cls, run: "AgentRun") -> "AgentRunResponse":
        grounding = run.grounding
        return cls(
            run_id=run.run_id,
            outcome=run.outcome,
            explanation=run.explanation,
            replan_cycles=run.replan_cycles,
            tool_calls=run.tool_calls,
            grounding=None
            if grounding is None
            else GroundingReportRead(
                attempts=grounding.attempts,
                rejected_numbers=grounding.rejected_numbers,
                regenerated=grounding.regenerated,
                fallback_used=grounding.fallback_used,
                fallback_reason=grounding.fallback_reason,
            ),
            observed_demand=run.demand,
            plan=run.plan,
            verify=run.verify,
            actions=[
                AgentActionRead(
                    tool=action["tool"],
                    arguments=action["arguments"],
                    ok=action["ok"],
                    error=action["error"],
                    reason=action["reason"],
                    result=action["result"],
                )
                for action in run.actions
            ],
            audit_log_ids=run.audit_log_ids,
            trace=[TraceStepRead(**step.to_json()) for step in run.trace.steps],
        )


class ToolSpecRead(ORMModel):
    """One tool: what it does and which backend endpoint it wraps."""

    name: str
    description: str
    endpoint: str
