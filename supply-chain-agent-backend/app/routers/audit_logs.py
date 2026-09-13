"""Audit log endpoints.

The trail is append-only from the API's point of view: callers can read entries
and append new ones, but there is deliberately no update or delete route.
"""

from fastapi import APIRouter, Query, status

from app.models import Actor
from app.routers.deps import AuditLogServiceDep, LimitQuery, SkipQuery
from app.schemas.audit_log import AuditLogCreate, AuditLogRead
from app.security import WRITE_GUARD

router = APIRouter(prefix="/audit-logs", tags=["audit_logs"])


@router.get("", response_model=list[AuditLogRead], summary="List audit log entries")
def list_audit_logs(
    service: AuditLogServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    actor: Actor | None = Query(default=None, description="Filter by actor"),
):
    if actor is not None:
        return service.list_by_actor(actor, limit=limit)[skip : skip + limit]
    return service.list(skip=skip, limit=limit)


@router.get(
    "/recent",
    response_model=list[AuditLogRead],
    summary="Most recent audit log entries",
)
def list_recent_audit_logs(
    service: AuditLogServiceDep, limit: LimitQuery = 50
):
    return service.list_recent(limit=limit)


@router.post(
    "",
    response_model=AuditLogRead,
    status_code=status.HTTP_201_CREATED,
    summary="Append an audit log entry",
    dependencies=WRITE_GUARD,
)
def create_audit_log(payload: AuditLogCreate, service: AuditLogServiceDep):
    return service.create(payload)


@router.get(
    "/{audit_log_id}", response_model=AuditLogRead, summary="Get an audit log entry"
)
def get_audit_log(audit_log_id: int, service: AuditLogServiceDep):
    return service.get_or_404(audit_log_id)
