"""SQLAlchemy declarative base."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for every ORM model in ``app.models``."""


def import_models() -> None:
    """Import every model module so ``Base.metadata`` is fully populated."""
    from app import models  # noqa: F401  (side effect: registers the tables)


def create_all(engine) -> None:  # type: ignore[no-untyped-def]
    """Create any missing tables."""
    import_models()
    Base.metadata.create_all(bind=engine)


def drop_all(engine) -> None:  # type: ignore[no-untyped-def]
    """Drop every table (used by the reset endpoint)."""
    import_models()
    Base.metadata.drop_all(bind=engine)
