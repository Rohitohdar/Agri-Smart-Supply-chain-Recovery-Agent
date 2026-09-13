"""Request and response schemas for the disruption-trigger endpoints.

These drive live demos by breaking the seeded scenario on purpose. Like the
other actions they return the resulting state and their before/after, and they
all record a single ``disruption_injected`` audit entry so the timeline of what
was done to the scenario stays fully traceable.
"""

from datetime import datetime

from pydantic import Field

from app.models.shipment import ShipmentStatus
from app.schemas.common import MAX_HOURS, MAX_QUANTITY, ORMModel
from app.schemas.dealer import DealerRead
from app.schemas.route import RouteRead
from app.schemas.shipment import ShipmentRead
from app.schemas.vendor import VendorRead


class ShipmentDelayRequest(ORMModel):
    """Body for ``POST /simulate/shipment-delay``."""

    shipment_id: int = Field(gt=0)
    delay_hours: float = Field(
        gt=0,
        le=MAX_HOURS,
        description="Hours to add to the shipment's expected arrival",
    )


class ShipmentDelayResponse(ORMModel):
    shipment: ShipmentRead
    delay_hours: float
    previous_status: ShipmentStatus
    previous_expected_arrival: datetime | None = None
    audit_log_id: int


class VendorFailureRequest(ORMModel):
    """Body for ``POST /simulate/vendor-failure``."""

    vendor_id: int = Field(gt=0)


class VendorFailureResponse(ORMModel):
    vendor: VendorRead
    previous_is_available: bool
    audit_log_id: int


class RouteBlockRequest(ORMModel):
    """Body for ``POST /simulate/route-block``."""

    route_id: int = Field(gt=0)


class RouteBlockResponse(ORMModel):
    route: RouteRead
    previous_is_available: bool
    audit_log_id: int


class DemandSpikeRequest(ORMModel):
    """Body for ``POST /simulate/demand-spike``."""

    dealer_id: int = Field(gt=0)
    new_required_quantity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
        description="Must exceed the dealer's current requirement",
    )


class DemandSpikeResponse(ORMModel):
    dealer: DealerRead
    previous_required_quantity: int
    shortage_before: int
    shortage_after: int
    audit_log_id: int
