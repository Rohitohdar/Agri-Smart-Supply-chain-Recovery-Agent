"""State-changing action endpoints.

These are the only endpoints that mutate the supply chain. Each one is a thin
wrapper over :class:`app.services.action_service.ActionService`, which owns all
validation, applies the change and its audit entry in one transaction, and
returns the resulting state. Callers (including the future agent layer) cannot
bypass those checks — passing an infeasible request back returns ``409`` with a
stable ``reason`` code and leaves the database untouched.

The specification names two of these paths in the singular
(``/shipment/{id}/...``, ``/vendor/{id}/purchase``); plural aliases that match
the rest of the API's naming are registered too, hidden from the OpenAPI schema
so the contract stays uncluttered.
"""

from fastapi import APIRouter

from app.routers.deps import ActionServiceDep
from app.schemas.actions import (
    InventoryTransferRequest,
    InventoryTransferResponse,
    ShipmentCancelResponse,
    ShipmentRerouteRequest,
    ShipmentRerouteResponse,
    VendorPurchaseRequest,
    VendorPurchaseResponse,
)
from app.security import WRITE_GUARD

#: Every route here mutates supply-chain state, so the whole router is guarded.
router = APIRouter(tags=["actions"], dependencies=WRITE_GUARD)


@router.post(
    "/inventory/transfer",
    response_model=InventoryTransferResponse,
    summary="Move stock between locations",
    description=(
        "Moves stock out of a warehouse into another warehouse or the dealer. "
        "Validated against the source's current stock; refuses with ``409`` "
        "when it holds too little (``insufficient_stock``) and returns both "
        "locations before and after the move."
    ),
)
def transfer_inventory(
    payload: InventoryTransferRequest, service: ActionServiceDep
):
    return service.transfer_inventory(payload)


@router.post(
    "/shipment/{shipment_id}/reroute",
    response_model=ShipmentRerouteResponse,
    summary="Change a shipment's route",
    description=(
        "Puts a shipment on a different available route. The route must still "
        "end at the shipment's destination; the ETA is recomputed from the new "
        "route's travel time. Refuses when the route is unavailable "
        "(``route_unavailable``) or the shipment has already landed."
    ),
)
@router.post(
    "/shipments/{shipment_id}/reroute",
    response_model=ShipmentRerouteResponse,
    include_in_schema=False,
)
def reroute_shipment(
    shipment_id: int, payload: ShipmentRerouteRequest, service: ActionServiceDep
):
    return service.reroute_shipment(shipment_id, payload)


@router.post(
    "/vendor/{vendor_id}/purchase",
    response_model=VendorPurchaseResponse,
    summary="Purchase stock from a vendor",
    description=(
        "Reserves stock at a supplier and creates a new inbound ``PENDING`` "
        "shipment for the dealer, scheduled after the vendor's delivery time. "
        "Refuses an unavailable vendor (``vendor_unavailable``) or a quantity "
        "the vendor cannot cover (``insufficient_supplier_stock``)."
    ),
)
@router.post(
    "/vendors/{vendor_id}/purchase",
    response_model=VendorPurchaseResponse,
    include_in_schema=False,
)
def purchase_from_vendor(
    vendor_id: int, payload: VendorPurchaseRequest, service: ActionServiceDep
):
    return service.purchase_from_vendor(vendor_id, payload)


@router.post(
    "/shipment/{shipment_id}/cancel",
    response_model=ShipmentCancelResponse,
    summary="Cancel a shipment",
    description=(
        "Cancels a shipment that has not landed. The shipment keeps its row "
        "with status ``CANCELLED`` and immediately stops counting as inbound "
        "supply. Refuses an arrived (``shipment_already_arrived``) or already "
        "cancelled (``shipment_already_cancelled``) shipment."
    ),
)
@router.post(
    "/shipments/{shipment_id}/cancel",
    response_model=ShipmentCancelResponse,
    include_in_schema=False,
)
def cancel_shipment(shipment_id: int, service: ActionServiceDep):
    return service.cancel_shipment(shipment_id)
