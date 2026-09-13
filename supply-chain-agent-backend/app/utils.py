"""Small shared helpers."""

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime.

    SQLite has no native timezone support, so every timestamp in this project is
    stored as naive UTC. Keeping the convention in one place avoids
    "can't compare offset-naive and offset-aware datetimes" errors downstream.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hours_from_now(hours: float) -> datetime:
    """Naive UTC timestamp ``hours`` in the future (accepts fractional hours)."""
    return utcnow() + timedelta(hours=hours)
