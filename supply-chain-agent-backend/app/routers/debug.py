"""Debug / demo-tooling endpoints.

These endpoints are read-only and carry no ``WRITE_GUARD``, but they are
intentionally absent from the production tag list so they do not appear
alongside the operational API in generated docs.

``GET /debug/would-choose``
    Runs the optimizer against the current database state and returns the
    top-ranked feasible option together with a ``disruption_target`` block
    that names the exact entity to disable in order to force the agent to
    choose a different option.  Use this as a pre-check before recording a
    demo: call the endpoint, read ``disruption_target``, press the matching
    disruption button, then run the agent — the recorded run will show a
    visible before-vs-after change in the chosen action.
"""

from fastapi import APIRouter

from app.routers.deps import DbSession
from app.schemas.debug import WouldChooseResponse
from app.services.debug_service import WouldChooseService

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get(
    "/would-choose",
    response_model=WouldChooseResponse,
    summary="What the agent would pick right now (demo pre-check)",
    description=(
        "Runs the optimizer against the current state without applying any "
        "disruption and returns the top-ranked feasible option. The response "
        "includes a ``disruption_target`` block naming the exact vendor, route "
        "or shipment to disable so that the recorded demo shows a clear "
        "cause-and-effect change in the agent's choice. "
        "Read-only; does not change any state."
    ),
)
def would_choose(db: DbSession) -> WouldChooseResponse:
    return WouldChooseService(db).would_choose()
