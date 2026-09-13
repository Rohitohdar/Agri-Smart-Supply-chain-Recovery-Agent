"""Supplier model."""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Supplier(Base):
    """A source that can sell a product, with price/speed/carbon trade-offs."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )
    price_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_hours: Mapped[float] = mapped_column(Float, nullable=False)
    carbon_per_unit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Supplier id={self.id} name={self.name!r} price={self.price_per_unit}>"
