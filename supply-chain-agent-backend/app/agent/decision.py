"""Structured action selection — never free text.

The action the agent takes is never parsed out of prose. A selector returns JSON
that is validated against :class:`ActionDecision` before anything can be
executed, and the loop then authorises it against the optimizer's own ranking
(see ``RecoveryAgent._authorise``). Two guardrails meet here:

* **structured output only** — an unvalidated or malformed decision cannot reach
  a mutating tool, because nothing but a validated ``ActionDecision`` is accepted;
* **no silent action** — the decision must name the optimizer's top-ranked
  feasible option, so a state-changing tool can never be called on a whim.

The default :class:`TopRankedSelector` is deterministic: it echoes the
optimizer's ranking, so the shipped agent cannot diverge. The schema is what lets
a model-backed selector be dropped in later without that becoming possible.
"""

from typing import Any, Dict, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Accept the *tool* vocabulary as well as the optimizer's action vocabulary, so
#: ``{"action": "transfer_inventory", ...}`` and ``{"action": "warehouse_transfer",
#: ...}`` both validate — they name the same thing.
_TOOL_TO_ACTION = {
    "transfer_inventory": "warehouse_transfer",
    "purchase_from_vendor": "vendor_purchase",
    "reroute_shipment": "reroute_shipment",
}


class ActionParams(BaseModel):
    """Which target the action applies to, and for how much."""

    model_config = ConfigDict(extra="forbid")

    #: Warehouse id or vendor id, matching the optimizer option's ``reference_id``.
    reference_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    #: For reroute_shipment: the shipment to reroute.
    shipment_id: Optional[int] = Field(default=None, gt=0)
    #: For reroute_shipment: the new route to use.
    new_route_id: Optional[int] = Field(default=None, gt=0)


class ActionDecision(BaseModel):
    """One structured tool-selection decision."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["warehouse_transfer", "vendor_purchase", "reroute_shipment"]
    params: ActionParams
    reasoning: str = Field(min_length=1)

    @field_validator("action", mode="before")
    @classmethod
    def _normalise_action(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _TOOL_TO_ACTION.get(value, value)
        return value


class ActionSelector(Protocol):
    """Anything that can pick an action from an optimizer plan."""

    def choose(self, plan: Dict[str, Any]) -> Any:  # pragma: no cover - protocol
        ...


class TopRankedSelector:
    """Deterministic selector: the optimizer's top-ranked feasible option, as-is.

    Because it copies the ranking rather than re-deciding it, the authorisation
    guard can only ever pass; a selector that reasons for itself is what the
    guard exists for.
    """

    def choose(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        top = plan["options"][0]
        params: Dict[str, Any] = {
            "reference_id": top["reference_id"],
            "quantity": top["quantity"],
        }
        # Reroute candidates carry shipment_id and new_route_id.
        if top["action"] == "reroute_shipment":
            params["shipment_id"] = top["reference_id"]
            params["new_route_id"] = top.get("route_id")
        return {
            "action": top["action"],
            "params": params,
            "reasoning": (
                f"Top-ranked feasible option: {top['action']} from {top['label']} "
                f"for {top['quantity']} units at score {top['score']}."
            ),
        }
