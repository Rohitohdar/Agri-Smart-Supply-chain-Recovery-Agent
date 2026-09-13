"""The reasoning trace: every tool call the agent made, and its raw result.

This is the artifact the frontend renders and the artifact the explanation is
generated *from*. Nothing here is summarised or recomputed — each step stores
the arguments that were passed and the raw JSON that came back, so a reader can
check any number in the agent's prose against its source.
"""

import enum
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AgentPhase(str, enum.Enum):
    """The stage of the loop a step belongs to.

    The first six are the prescribed recovery phases; ``decide`` validates the
    structured action decision and ``guardrail`` records a guardrail firing (a
    refused decision, the honest no-feasible refusal, a budget being exhausted,
    or the grounding validation pass).
    """

    OBSERVE = "observe"
    DETECT = "detect"
    INVESTIGATE = "investigate"
    OPTIMIZE = "optimize"
    DECIDE = "decide"
    EXECUTE = "execute"
    VERIFY = "verify"
    REROUTE = "reroute"
    GUARDRAIL = "guardrail"


class AgentOutcome(str, enum.Enum):
    """How a run ended."""

    NO_ACTION_NEEDED = "no_action_needed"
    RESOLVED = "resolved"
    NO_FEASIBLE_OPTION = "no_feasible_option"
    ACTION_REJECTED = "action_rejected"
    #: The selected action did not match the optimizer's top-ranked option, or
    #: was not structured JSON, so it was refused before execution.
    DECISION_REJECTED = "decision_rejected"
    REPLAN_LIMIT_REACHED = "replan_limit_reached"
    #: A cycle exhausted its tool-call budget.
    TOOL_CALL_LIMIT_REACHED = "tool_call_limit_reached"


@dataclass
class TraceStep:
    """One tool call, or one decision the agent made without a tool call."""

    index: int
    phase: AgentPhase
    #: Tool name, or ``None`` for a pure decision step (e.g. the detect verdict).
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    #: The tool's raw, unmodified JSON result.
    result: Any = None
    #: Optional short annotation (never a substitute for the raw result).
    note: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "phase": self.phase.value,
            "tool": self.tool,
            "arguments": self.arguments,
            "result": self.result,
            "note": self.note,
        }


class ReasoningTrace:
    """Append-only list of :class:`TraceStep` objects."""

    def __init__(self) -> None:
        self.steps: List[TraceStep] = []

    def add(
        self,
        phase: AgentPhase,
        *,
        tool: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        result: Any = None,
        note: Optional[str] = None,
    ) -> TraceStep:
        step = TraceStep(
            index=len(self.steps),
            phase=phase,
            tool=tool,
            arguments=dict(arguments or {}),
            result=result,
            note=note,
        )
        self.steps.append(step)
        return step

    def tool_results(self) -> List[Any]:
        """Every raw result recorded for an actual tool call."""
        return [step.result for step in self.steps if step.tool is not None]

    def to_json(self) -> List[Dict[str, Any]]:
        return [step.to_json() for step in self.steps]

    def json_dump(self) -> str:
        """Canonical serialization used for grounding checks."""
        return json.dumps(self.to_json(), default=str, sort_keys=True)
