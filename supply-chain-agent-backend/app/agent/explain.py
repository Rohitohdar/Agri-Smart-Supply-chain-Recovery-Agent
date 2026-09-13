"""Turning a reasoning trace into prose — without letting the prose invent data.

Two explainers implement the same tiny interface, and both take an optional
``correction`` so they can be asked again under stricter instructions:

* :class:`TemplateExplainer` (the default) assembles sentences *by reading
  fields out of the recorded tool results*. Every number is interpolated from
  the trace, so it is structurally impossible for it to state a figure that no
  tool returned.
* :class:`GroqExplainer` hands the trace to a model hosted by Groq.

The validation pass itself lives in the loop (`RecoveryAgent._explain`), so
there is exactly one enforcement point: :func:`ungrounded_numbers` extracts every
number from the returned prose and compares it with the trace. A reply citing a
figure no tool produced is discarded and regenerated once with an explicit
instruction (:data:`~app.agent.constants.GROUNDING_INSTRUCTION`); only if that
attempt also fails does the deterministic template take over. The text a user
sees is therefore always grounded in tool results already returned, never in
recollection or estimation.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

from app.agent.constants import NO_FEASIBLE_MESSAGE
from app.agent.trace import AgentOutcome, ReasoningTrace

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class ExplainerError(RuntimeError):
    """Base class for explainer problems."""


class ExplainerUnavailable(ExplainerError):
    """The LLM explainer cannot run (no dependency, no key, or an API failure)."""


@dataclass(frozen=True)
class GroundingReport:
    """What the grounding validation pass did, for the trace and the frontend."""

    #: How many times the explainer was asked.
    attempts: int
    #: Numbers rejected per failed attempt (empty when the first attempt passed).
    rejected_numbers: List[List[str]] = field(default_factory=list)
    #: True when the accepted text came from the corrected re-ask.
    regenerated: bool = False
    #: True when the configured explainer failed and the template was used instead.
    fallback_used: bool = False
    #: Why the fallback happened; None when it did not. Without this a provider
    #: failure is indistinguishable from a missing key or an exhausted budget.
    fallback_reason: Optional[str] = None


def ungrounded_numbers(text: str, trace: ReasoningTrace) -> List[str]:
    """Numbers in ``text`` that do not appear anywhere in the trace's output."""
    haystack = trace.json_dump()
    return [token for token in _NUMBER.findall(text) if token not in haystack]


def _n(value: Any) -> str:
    """Render a value exactly as JSON does, so it can be matched back to the trace."""
    return json.dumps(value)


@dataclass(frozen=True)
class ExplanationContext:
    """Everything the explanation may talk about."""

    outcome: AgentOutcome
    demand: Dict[str, Any]
    plan: Optional[Dict[str, Any]]
    verify: Optional[Dict[str, Any]]
    #: Executed actions: {tool, arguments, ok, error, reason, result}.
    actions: Sequence[Dict[str, Any]]
    replan_cycles: int
    trace: ReasoningTrace


class Explainer(Protocol):
    """Anything that can turn a run into a natural-language explanation."""

    def explain(
        self, context: ExplanationContext, *, correction: Optional[str] = None
    ) -> str:  # pragma: no cover - protocol
        ...


class TemplateExplainer:
    """Deterministic, grounded-by-construction explanation."""

    def explain(
        self, context: ExplanationContext, *, correction: Optional[str] = None
    ) -> str:
        # ``correction`` is ignored: this explainer is grounded by construction.
        sentences = [self._observation(context.demand)]

        if context.outcome is AgentOutcome.NO_ACTION_NEEDED:
            sentences.append(
                "constraint_violated was "
                + _n(context.demand["constraint_violated"])
                + ", so no action was needed."
            )
            return " ".join(sentences)

        if context.outcome is AgentOutcome.NO_FEASIBLE_OPTION:
            # The explicit refuse-if-uncertain path: the exact sentence, never a
            # softened paraphrase and never a forced choice.
            sentences.append(f"{NO_FEASIBLE_MESSAGE}.")
            sentences.append(self._exclusions(context.plan))
            return " ".join(filter(None, sentences))

        sentences.append(self._optimization(context.plan))
        sentences.extend(self._action_sentences(action) for action in context.actions)
        sentences.append(self._verification(context.verify))

        if context.outcome is AgentOutcome.ACTION_REJECTED:
            sentences.append(
                "The optimizer's top-ranked action had already been refused, so "
                "the agent stopped instead of repeating it."
            )
        elif context.outcome is AgentOutcome.REPLAN_LIMIT_REACHED:
            sentences.append(
                "The replan limit was reached with the requirement still not "
                "covered, so the agent stopped."
            )
        elif context.outcome is AgentOutcome.DECISION_REJECTED:
            sentences.append(
                "The proposed action was refused by the authorization guard "
                "before execution, so no stock-moving tool was called."
            )
        elif context.outcome is AgentOutcome.TOOL_CALL_LIMIT_REACHED:
            sentences.append(
                "The per-cycle tool-call budget was exhausted, so the agent "
                "stopped rather than loop."
            )
        return " ".join(filter(None, sentences))

    # --- pieces ------------------------------------------------------------
    @staticmethod
    def _observation(demand: Dict[str, Any]) -> str:
        return (
            f"Dealer {demand['dealer_name']} ({_n(demand['dealer_id'])}) requires "
            f"{_n(demand['required_quantity'])} units by {demand['deadline']} and "
            f"holds {_n(demand['available_quantity'])}, a shortage of "
            f"{_n(demand['shortage'])} with "
            f"{_n(demand['active_shipment_quantity'])} units already inbound "
            f"(constraint_violations={_n(demand['constraint_violations'])})."
        )

    @staticmethod
    def _exclusions(plan: Optional[Dict[str, Any]]) -> str:
        if not plan or not plan.get("excluded"):
            return ""
        reasons = ", ".join(
            f"{item['action']} {_n(item['reference_id'])} ({item['reason']}: "
            f"available {_n(item['available_quantity'])})"
            for item in plan["excluded"]
        )
        return f"Excluded candidates: {reasons}."

    @staticmethod
    def _optimization(plan: Optional[Dict[str, Any]]) -> str:
        if not plan or not plan.get("options"):
            return ""
        top = plan["options"][0]
        return (
            f"The optimizer ranked {top['action']} from {top['label']} "
            f"(reference_id {_n(top['reference_id'])}) first for "
            f"{_n(top['quantity'])} units: cost {_n(top['total_cost'])}, delivery "
            f"{_n(top['total_delivery_hours'])} h, carbon {_n(top['total_carbon'])}, "
            f"score {_n(top['score'])}."
        )

    @staticmethod
    def _action_sentences(action: Dict[str, Any]) -> str:
        tool = action["tool"]
        arguments = action.get("arguments", {})
        if not action.get("ok"):
            return (
                f"Executing {tool}({_n(arguments)}) was refused: "
                f"{action.get('error')} ({action.get('reason')})."
            )
        result = action.get("result") or {}
        if tool == "purchase_from_vendor":
            shipment = result["shipment"]
            vendor = result["vendor"]
            return (
                f"Executed purchase_from_vendor({_n(arguments)}), which created "
                f"shipment {_n(shipment['id'])} of {_n(shipment['quantity'])} units "
                f"from {vendor['name']} arriving {shipment['expected_arrival']} and "
                f"left vendor availability at {_n(vendor['available_quantity'])} "
                f"(was {_n(result['vendor_available_before'])})."
            )
        if tool == "transfer_inventory":
            return (
                f"Executed transfer_inventory({_n(arguments)}): the source now "
                f"holds {_n(result['source_after']['total_quantity'])} and the "
                f"destination {_n(result['destination_after']['total_quantity'])}."
            )
        if tool == "reroute_shipment":
            shipment = result["shipment"]
            return (
                f"Executed reroute_shipment({_n(arguments)}): shipment "
                f"{_n(shipment['id'])} now departs from "
                f"{_n(shipment['from_id'])} with expected arrival "
                f"{shipment['expected_arrival']}."
            )
        return f"Executed {tool}({_n(arguments)})."

    @staticmethod
    def _verification(verify: Optional[Dict[str, Any]]) -> str:
        if not verify:
            return ""
        return (
            f"Verification: satisfied={_n(verify['satisfied'])} — on hand "
            f"{_n(verify['available_quantity'])} plus "
            f"{_n(verify['on_time_inbound_quantity'])} inbound by the deadline is "
            f"{_n(verify['covered_quantity'])} against a requirement of "
            f"{_n(verify['required_quantity'])}, with late shipments "
            f"{_n(verify['late_shipment_ids'])}."
        )


class GroqExplainer:
    """Optional LLM explanation via Groq; the caller validates its grounding.

    The model is given the trace and asked to narrate it. Its reply is handed
    back unvalidated on purpose: the loop runs :func:`ungrounded_numbers` over it
    and regenerates once with :data:`GROUNDING_INSTRUCTION` if any figure is
    untraceable, so an LLM cannot introduce data into the pipeline.

    Groq exposes an OpenAI-compatible chat-completions API, so this is the only
    provider-specific code in the project; nothing else knows which model wrote
    the prose.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        max_tokens: int = 2048,
        reasoning_effort: str = "low",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort

    def explain(
        self, context: ExplanationContext, *, correction: Optional[str] = None
    ) -> str:
        try:
            from groq import Groq  # imported lazily: an optional extra
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ExplainerUnavailable("the 'groq' package is not installed") from exc

        instruction = (
            "You write the closing summary of a supply-chain recovery run for a "
            "non-technical reader. Use ONLY the numbers in the JSON below, "
            "verbatim. Do not compute, estimate, round or invent any figure; if a "
            "value is not in the JSON, do not state it. Three or four sentences of "
            "plain prose: no field names, no snake_case, no JSON snippets."
        )
        if correction:
            # The re-ask after a grounding failure, in the caller's own words.
            instruction = f"{instruction}\n\nCorrection required: {correction}"
        payload = json.dumps(
            {
                "outcome": context.outcome.value,
                "demand": context.demand,
                "plan": context.plan,
                "verify": context.verify,
                "actions": list(context.actions),
                "trace": context.trace.to_json(),
            },
            default=str,
        )
        request: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # No sampling tuning here: the valid sampling range differs per model
            # (Groq discourages 0 for the gpt-oss family), and an unsupported
            # value is a 4xx that would silently drop the run back to the
            # template. Grounding, not temperature, is what makes it trustworthy.
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": payload},
            ],
        }
        if self.reasoning_effort:
            # Sent in the body's pass-through: the installed SDK predates this
            # field. A reasoning model that is allowed to think unboundedly about
            # a three-sentence summary turns a live demo into a long silence.
            request["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        try:
            client = Groq(api_key=self.api_key, timeout=self.timeout)
            completion = client.chat.completions.create(**request)
        except Exception as exc:  # pragma: no cover - network/SDK dependent
            raise ExplainerUnavailable(f"LLM explainer failed: {exc}") from exc

        choices = getattr(completion, "choices", None) or []
        if not choices:  # pragma: no cover - SDK shape
            raise ExplainerUnavailable("LLM explainer returned no choices")
        text = (getattr(choices[0].message, "content", None) or "").strip()
        if not text:
            raise ExplainerUnavailable(self._empty_reply_reason(choices[0], completion))
        # Grounding is checked by the caller (the loop), so there is one
        # enforcement point rather than two that could disagree.
        return text

    def _empty_reply_reason(self, choice: Any, completion: Any) -> str:
        """Say *why* a reply was empty, since a reasoning model can eat its budget.

        A reasoning model bills its thinking against the same token budget as
        its answer, so a budget that is too small returns ``finish_reason=length``
        with an empty ``content`` — indistinguishable, as a bare "no text", from
        a broken request.
        """
        usage = getattr(completion, "usage", None)
        details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        if isinstance(details, dict):
            reasoning = details.get("reasoning_tokens", reasoning)
        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            return (
                f"LLM explainer used its whole {self.max_tokens} token budget "
                f"({reasoning} on reasoning) before writing any text; raise "
                "AGENT_EXPLAINER_MAX_TOKENS"
            )
        return f"LLM explainer returned no text (finish_reason={finish})"


def choose_explainer() -> Explainer:
    """The Groq explainer when a key is configured, otherwise the template."""
    from app.config import get_settings

    settings = get_settings()
    if settings.groq_api_key:
        return GroqExplainer(
            api_key=settings.groq_api_key,
            model=settings.agent_explainer_model,
            timeout=settings.agent_explainer_timeout,
            max_tokens=settings.agent_explainer_max_tokens,
            reasoning_effort=settings.agent_explainer_reasoning_effort,
        )
    return TemplateExplainer()
