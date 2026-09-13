"""The audit view: what happened, who did it, and what it changed.

``GET /audit`` is the one read-only endpoint that *also* requires the API key.
The trail is the record of every mutation in the system and carries before/after
state, so it is exposed deliberately rather than left open with the rest of the
reads. Each entry holds the actor (``agent`` or ``system``), the action type and
the change it described, which is what makes a demo narratable after the fact.
"""

from fastapi import APIRouter, Query

from app.models import Actor
from app.routers.deps import AuditLogServiceDep, LimitQuery, SkipQuery
from app.schemas.audit_log import AuditLogRead

# Read-only, but not public: the trail is gated with the same guard writes use.
from app.security import WRITE_GUARD

router = APIRouter(tags=["audit"])


@router.get(
    "/audit",
    response_model=list[AuditLogRead],
    summary="View the audit trail",
    description=(
        "Every state-changing action, newest first, with the actor, the action "
        "type and the before/after state in ``details``. Requires the API key."
    ),
    dependencies=WRITE_GUARD,
)
def view_audit_trail(
    service: AuditLogServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    actor: Actor | None = Query(default=None, description="Filter by actor"),
    action_type: str | None = Query(
        default=None, max_length=64, description="Filter by action type"
    ),
):
    return service.recent(
        actor=actor, action_type=action_type, skip=skip, limit=limit
    )
