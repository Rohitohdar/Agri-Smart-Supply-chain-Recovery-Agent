"""Schemas for the admin endpoints."""

from datetime import datetime
from typing import Dict

from pydantic import Field

from app.schemas.common import ORMModel


class ResetResponse(ORMModel):
    """Result of ``POST /admin/reset``."""

    status: str = "reset"
    database_url: str
    reset_at: datetime
    counts: Dict[str, int]
    audit_log_id: int


class StateResponse(ORMModel):
    """Compact snapshot of the current state (counts per table)."""

    counts: Dict[str, int] = Field(default_factory=dict)
    warehouse_inventory: Dict[str, Dict[str, int]] = Field(default_factory=dict)
