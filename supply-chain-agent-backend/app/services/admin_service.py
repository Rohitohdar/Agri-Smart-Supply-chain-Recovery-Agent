"""Admin service: reset to the seeded starting state and report state."""

from typing import Any, Dict, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.db.seed import seed_database
from app.utils import utcnow

#: Tables reported by the reset/state endpoints, in a stable order.
TRACKED_TABLES: Tuple[Tuple[str, type], ...] = (
    ("products", models.Product),
    ("suppliers", models.Supplier),
    ("warehouses", models.Warehouse),
    ("dealers", models.Dealer),
    ("routes", models.Route),
    ("shipments", models.Shipment),
    ("audit_logs", models.AuditLog),
)


def reset_to_seed_state(db: Session) -> Dict[str, Any]:
    """Wipe and re-seed the database, returning a summary of what was created."""
    counts = seed_database(db)
    # The seed always appends one system entry; surface its id to the caller.
    newest_log_id = db.scalar(select(func.max(models.AuditLog.id))) or 0
    return {
        "status": "reset",
        "database_url": get_settings().database_url,
        "reset_at": utcnow(),
        "counts": counts,
        "audit_log_id": int(newest_log_id),
    }


def state_snapshot(db: Session) -> Dict[str, Any]:
    """Counts per table plus a per-warehouse inventory view."""
    counts = {
        name: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in TRACKED_TABLES
    }
    warehouses = db.scalars(select(models.Warehouse).order_by(models.Warehouse.id)).all()
    return {
        "counts": counts,
        "warehouse_inventory": {
            f"{warehouse.id}:{warehouse.name}": dict(warehouse.inventory)
            for warehouse in warehouses
        },
    }
