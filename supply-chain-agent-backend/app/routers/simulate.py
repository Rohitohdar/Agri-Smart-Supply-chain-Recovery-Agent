"""Disruption-trigger endpoints used to drive live demos.

Each one breaks the seeded scenario on purpose (a late shipment, a failed
vendor, a blocked route, a demand spike). They are thin wrappers over
``ActionService``, so they share the same validation, transaction and
before/after response contract as the rest of the action layer, and every call
appends a single ``action_type = "disruption_injected"`` audit entry — which is
what makes the timeline of a demo fully narratable afterwards.
"""

from fastapi import APIRouter

from app.routers.deps import ActionServiceDep
from app.schemas.simulate import (
    DemandSpikeRequest,
    DemandSpikeResponse,
    RouteBlockRequest,
    RouteBlockResponse,
    ShipmentDelayRequest,
    ShipmentDelayResponse,
    VendorFailureRequest,
    VendorFailureResponse,
)
from app.security import WRITE_GUARD

#: Every route here changes the scenario, so the whole router is guarded.
router = APIRouter(prefix="/simulate", tags=["simulate"], dependencies=WRITE_GUARD)


@router.post(
    "/shipment-delay",
    response_model=ShipmentDelayResponse,
    summary="Delay a shipment",
    description=(
        "Marks the shipment ``DELAYED`` and pushes its expected arrival by "
        "``delay_hours``. Delays compound when injected repeatedly. Refuses a "
        "shipment that already arrived or was cancelled "
        "(``shipment_not_delayable``)."
    ),
)
def simulate_shipment_delay(
    payload: ShipmentDelayRequest, service: ActionServiceDep
):
    return service.inject_shipment_delay(payload)


@router.post(
    "/vendor-failure",
    response_model=VendorFailureResponse,
    summary="Fail a vendor",
    description=(
        "Sets the vendor's ``is_available`` to false so it drops out of supply "
        "comparisons. Refuses a vendor that is already unavailable "
        "(``vendor_already_unavailable``)."
    ),
)
def simulate_vendor_failure(
    payload: VendorFailureRequest, service: ActionServiceDep
):
    return service.inject_vendor_failure(payload)


@router.post(
    "/route-block",
    response_model=RouteBlockResponse,
    summary="Block a route",
    description=(
        "Sets the route's ``is_available`` to false so it cannot be used (for "
        "example a reroute). Refuses a route that is already blocked "
        "(``route_already_unavailable``)."
    ),
)
def simulate_route_block(payload: RouteBlockRequest, service: ActionServiceDep):
    return service.inject_route_block(payload)


@router.post(
    "/demand-spike",
    response_model=DemandSpikeResponse,
    summary="Spike dealer demand",
    description=(
        "Raises the dealer's required quantity, returning the shortage before "
        "and after. Refuses a value that does not exceed the current "
        "requirement (``not_a_demand_spike``)."
    ),
)
def simulate_demand_spike(
    payload: DemandSpikeRequest, service: ActionServiceDep
):
    return service.inject_demand_spike(payload)
