"""Recovery optimization endpoint.

Deterministic and LLM-free: ``POST /optimize/recovery`` snapshots the current
database state (warehouse stock, available vendors and open routes), generates
``warehouse_transfer`` and ``vendor_purchase`` candidates sized to the shortage,
drops the infeasible ones and ranks the rest with the weighted score described
in :mod:`app.optimizer`. Same request and state, same ranking — every time.
"""

from fastapi import APIRouter, Request

from app.ratelimit import OPTIMIZE_LIMIT, limiter
from app.routers.deps import OptimizerServiceDep
from app.schemas.optimize import RecoveryOptimizeRequest, RecoveryPlanResponse

router = APIRouter(prefix="/optimize", tags=["optimize"])


@router.post(
    "/recovery",
    response_model=RecoveryPlanResponse,
    summary="Rank recovery options for a shortage",
    description=(
        "Enumerates candidate recovery actions (warehouse transfers and vendor "
        "purchases), filters out those that cannot cover the shortage or miss "
        "the deadline, and ranks the rest by ``0.4 * normalized cost + 0.4 * "
        "normalized delivery hours + 0.2 * normalized carbon`` (lower is "
        "better). The response carries the raw metrics, the normalized values, "
        "each weighted contribution and the final score, plus the candidates "
        "that were filtered out and the numbers that filtered them."
    ),
)
@limiter.limit(OPTIMIZE_LIMIT)
def optimize_recovery(
    request: Request,
    payload: RecoveryOptimizeRequest,
    service: OptimizerServiceDep,
) -> RecoveryPlanResponse:
    plan = service.plan(
        shortage_quantity=payload.shortage_quantity, deadline=payload.deadline
    )
    return RecoveryPlanResponse.from_plan(plan)
