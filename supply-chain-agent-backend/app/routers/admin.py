"""Admin endpoints for resetting and inspecting the demo state."""

from fastapi import APIRouter

from app.routers.deps import DbSession
from app.schemas.admin import ResetResponse, StateResponse
from app.security import WRITE_GUARD
from app.services.admin_service import reset_to_seed_state, state_snapshot

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/reset",
    response_model=ResetResponse,
    summary="Reset the database to the seeded starting state",
    description=(
        "Drops every table, recreates the schema and reloads the seed scenario. "
        "This is destructive and always ends with exactly the documented "
        "starting state. Requires the API key: it deletes all data."
    ),
    dependencies=WRITE_GUARD,
)
def reset_database(db: DbSession):
    return ResetResponse(**reset_to_seed_state(db))


@router.get(
    "/state",
    response_model=StateResponse,
    summary="Snapshot of the current state",
)
def get_state(db: DbSession):
    return StateResponse(**state_snapshot(db))
