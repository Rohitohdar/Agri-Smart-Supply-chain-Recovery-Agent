"""Audit log schemas."""

from datetime import datetime
from typing import Any, Dict, Literal

from pydantic import Field

from app.models.audit_log import Actor
from app.schemas.common import ORMModel

ActorLiteral = Literal["agent", "system"]


class AuditLogBase(ORMModel):
    actor: Actor
    action_type: str = Field(min_length=1, max_length=64)
    details: Dict[str, Any] = Field(default_factory=dict)
    result: str = Field(min_length=1, max_length=255)


class AuditLogCreate(AuditLogBase):
    timestamp: datetime | None = None


class AuditLogUpdate(ORMModel):
    actor: Actor | None = None
    action_type: str | None = Field(default=None, min_length=1, max_length=64)
    details: Dict[str, Any] | None = None
    result: str | None = Field(default=None, min_length=1, max_length=255)


class AuditLogRead(AuditLogBase):
    id: int
    timestamp: datetime
