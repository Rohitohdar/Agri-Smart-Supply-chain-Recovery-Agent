"""Read-only demand endpoint."""

from fastapi import APIRouter, Query

from app.routers.deps import DemandServiceDep
from app.schemas.demand import DemandResponse

router = APIRouter(prefix="/demand", tags=["demand"])


@router.get(
    "",
    response_model=DemandResponse,
    summary="Dealer demand, stock, deadline and constraint status",
    description=(
        "``shortage`` / ``on_hand_shortfall`` report the raw on-hand gap as a "
        "secondary stat. ``constraint_violated`` uses the coverage definition: "
        "violated when (on_hand + inbound_by_deadline) < required, or when an "
        "in-flight shipment is expected after the deadline. This matches the "
        "agent's own ``verify_state`` tool, so the status badge and the agent's "
        "verdict always agree."
    ),
)
def get_demand(
    service: DemandServiceDep,
    dealer_id: int | None = Query(
        default=None,
        gt=0,
        description="Dealer to report on; defaults to the lowest-id dealer",
    ),
):
    dealer = service.dealer_or_default(dealer_id)
    return DemandResponse.from_dealer(dealer, service.active_shipments(dealer.id))
