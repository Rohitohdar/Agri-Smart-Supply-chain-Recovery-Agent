"""Dealer model."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Dealer(Base):
    """A buyer with a demand target (``required_quantity``) and a ``deadline``."""

    __tablename__ = "dealers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    required_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stored as naive UTC (see app.utils.utcnow).
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_inventory: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @property
    def shortfall(self) -> int:
        """Units still needed to meet the requirement."""
        return max(self.required_quantity - self.current_inventory, 0)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Dealer id={self.id} name={self.name!r} shortfall={self.shortfall}>"
