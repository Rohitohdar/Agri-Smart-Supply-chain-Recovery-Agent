"""Audit log service."""

from collections.abc import Sequence
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Actor, AuditLog
from app.schemas.audit_log import AuditLogCreate, AuditLogUpdate
from app.services.base import CRUDService
from app.utils import utcnow


class AuditLogService(CRUDService[AuditLog, AuditLogCreate, AuditLogUpdate]):
    model = AuditLog
    label = "AuditLog"

    def recent(
        self,
        *,
        actor: Actor | None = None,
        action_type: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Sequence[AuditLog]:
        """Newest-first entries, optionally narrowed by actor and/or action type."""
        stmt = select(AuditLog)
        if actor is not None:
            stmt = stmt.where(AuditLog.actor == actor)
        if action_type is not None:
            stmt = stmt.where(AuditLog.action_type == action_type)
        stmt = (
            stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .offset(skip)
            .limit(min(limit, self.max_limit))
        )
        return list(self.db.scalars(stmt).all())

    def list_recent(self, limit: int = 50) -> Sequence[AuditLog]:
        return self.recent(limit=limit)

    def list_by_actor(self, actor: Actor, limit: int = 50) -> Sequence[AuditLog]:
        return self.recent(actor=actor, limit=limit)


def stage(
    db: Session,
    *,
    actor: Actor | str,
    action_type: str,
    details: Mapping[str, Any] | None = None,
    result: str = "success",
) -> AuditLog:
    """Add an audit entry to the session *without* committing it.

    This is what the atomic action service uses: the entry is flushed and
    committed together with the change it describes, so a state change and its
    audit record can never land separately.
    """
    entry = AuditLog(
        timestamp=utcnow(),
        actor=Actor(actor),
        action_type=action_type,
        details=dict(details or {}),
        result=result,
    )
    db.add(entry)
    return entry


def record(
    db: Session,
    *,
    actor: Actor | str,
    action_type: str,
    details: Mapping[str, Any] | None = None,
    result: str = "success",
) -> AuditLog:
    """Append one audit entry and commit it immediately.

    Shared by the seed script and the admin endpoints; agent actions will use
    the same helper once the agent layer exists. State-changing actions that
    must be atomic use :func:`stage` instead so the entry shares their
    transaction.
    """
    entry = stage(
        db,
        actor=actor,
        action_type=action_type,
        details=details,
        result=result,
    )
    db.commit()
    db.refresh(entry)
    return entry
