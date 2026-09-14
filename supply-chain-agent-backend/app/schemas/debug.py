"""Schemas for the debug / demo-tooling endpoints."""

from typing import Literal, Optional, Union

from pydantic import Field

from app.schemas.common import ORMModel
from app.schemas.optimize import RankedOptionRead


class VendorDisruptionTarget(ORMModel):
    """Disable this vendor to force the agent away from a vendor_purchase."""

    kind: Literal["vendor_failure"] = "vendor_failure"
    vendor_id: int
    vendor_name: str
    #: Frontend disruption endpoint to call.
    endpoint: str = "/simulate/vendor-failure"
    #: JSON body to POST to that endpoint.
    payload: dict = Field(default_factory=dict)


class RouteDisruptionTarget(ORMModel):
    """Block this route to force the agent away from a warehouse_transfer."""

    kind: Literal["route_block"] = "route_block"
    route_id: int
    #: Frontend disruption endpoint to call.
    endpoint: str = "/simulate/route-block"
    #: JSON body to POST to that endpoint.
    payload: dict = Field(default_factory=dict)


class ShipmentDisruptionTarget(ORMModel):
    """Delay this shipment to force the agent to reroute or purchase instead."""

    kind: Literal["shipment_delay"] = "shipment_delay"
    shipment_id: int
    #: Frontend disruption endpoint to call.
    endpoint: str = "/simulate/shipment-delay"
    #: JSON body to POST to that endpoint.
    payload: dict = Field(default_factory=dict)


DisruptionTarget = Union[
    VendorDisruptionTarget, RouteDisruptionTarget, ShipmentDisruptionTarget
]


class WouldChooseResponse(ORMModel):
    """What the agent would pick right now, and how to disrupt it for the demo."""

    #: Shortage and deadline the optimizer was called with.
    shortage_quantity: int
    deadline: str
    hours_available: float
    #: The top-ranked feasible option, or None when nothing is feasible.
    top_option: Optional[RankedOptionRead] = None
    #: How many feasible options exist in total.
    feasible_count: int
    #: The entity to disable so the agent is forced to choose differently.
    #: None when there is no feasible option or no second option to fall back to.
    disruption_target: Optional[DisruptionTarget] = Field(default=None, discriminator="kind")
    #: Plain-English instruction for the demo operator.
    demo_instruction: str
