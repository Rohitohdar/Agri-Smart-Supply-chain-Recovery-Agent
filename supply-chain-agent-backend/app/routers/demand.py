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
        "``shortage``, ``constraint_violations`` and ``constraint_violated`` are "
        "computed: a constraint is violated when there is a shortage, or when an "
        "in-flight shipment inbound to the dealer is expected after the deadline."
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
