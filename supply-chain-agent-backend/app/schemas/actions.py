"""Request and response schemas for the state-changing action endpoints.

Every action returns the *resulting* state (never just ``{"ok": true}``), and the
two that change an existing row also return what it looked like beforehand, so a
caller can see exactly what its request did without re-reading the entity.
"""

from datetime import datetime

from pydantic import Field

from app.models.shipment import ShipmentStatus
from app.schemas.common import MAX_QUANTITY, ORMModel
from app.schemas.inventory import LocationInventory, WarehouseStock
from app.schemas.route import RouteRead
from app.schemas.shipment import ShipmentRead
from app.schemas.vendor import VendorRead


class InventoryTransferRequest(ORMModel):
    """Body for ``POST /inventory/transfer``."""

    from_warehouse_id: int = Field(
        gt=0, description="Source warehouse id (warehouses are 101-199)"
    )
    to_id: int = Field(
        gt=0, description="Destination location id: a warehouse or the dealer"
    )
    quantity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
        description="Units to move; must not exceed the source stock",
    )
    product_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Product to move. May be omitted when the catalogue holds exactly "
            "one product."
        ),
    )


class InventoryTransferResponse(ORMModel):
    """The stock movement plus both locations before and after it."""

    product_id: int
    quantity: int
    source_before: WarehouseStock
    source_after: WarehouseStock
    destination_before: LocationInventory
    destination_after: LocationInventory
    audit_log_id: int


class ShipmentRerouteRequest(ORMModel):
    """Body for ``POST /shipment/{id}/reroute``."""

    new_route_id: int = Field(
        gt=0, description="Available route the shipment should now travel"
    )


class ShipmentRerouteResponse(ORMModel):
    """The shipment after rerouting, with its previous origin and ETA."""

    shipment: ShipmentRead
    route: RouteRead
    previous_from_id: int
    previous_to_id: int
    previous_expected_arrival: datetime | None = None
    audit_log_id: int


class VendorPurchaseRequest(ORMModel):
    """Body for ``POST /vendor/{id}/purchase``."""

    quantity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
        description="Units to buy; must not exceed the vendor's stock",
    )


class VendorPurchaseResponse(ORMModel):
    """The new inbound shipment plus the vendor's remaining availability."""

    vendor: VendorRead
    vendor_available_before: int
    shipment: ShipmentRead
    audit_log_id: int


class ShipmentCancelResponse(ORMModel):
    """The cancelled shipment and the status it held before the cancellation."""

    shipment: ShipmentRead
    previous_status: ShipmentStatus
    audit_log_id: int
