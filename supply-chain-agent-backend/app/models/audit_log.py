"""Audit log model."""

import enum
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import DateTime, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.utils import utcnow


class Actor(str, enum.Enum):
    """Who performed the action."""

    AGENT = "agent"
    SYSTEM = "system"


class AuditLog(Base):
    """Append-only trail of everything the agent or the system does."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
    actor: Mapped[Actor] = mapped_column(
        Enum(Actor, native_enum=False, length=16, validate_strings=True),
        nullable=False,
        default=Actor.SYSTEM,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[str] = mapped_column(String(255), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AuditLog id={self.id} actor={self.actor.value} "
            f"action={self.action_type!r}>"
        )
