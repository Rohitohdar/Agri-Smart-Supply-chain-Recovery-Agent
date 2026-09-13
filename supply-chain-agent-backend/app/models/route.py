"""Route model.

``from_location_id`` / ``to_location_id`` are *location node ids*, not foreign
keys to a single table, because a route can connect a supplier, a warehouse or a
dealer. ``app.locations`` is the canonical definition of that namespace:

===============  =======================  =========================
Location kind    Id range                 Example
===============  =======================  =========================
Supplier         1 – 99                   supplier id 1, 2, 3
Warehouse        101 – 199                warehouse id 101, 102, 103
Dealer           201 – 299                dealer id 201
===============  =======================  =========================

Keeping the ranges disjoint means an endpoint id always resolves to exactly one
entity, so no extra ``location_type`` column is needed.
"""

from sqlalchemy import Boolean, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Route(Base):
    """A transport link between two location nodes."""

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_location_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    to_location_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    travel_time_hours: Mapped[float] = mapped_column(Float, nullable=False)
    carbon_per_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def carbon_emission(self) -> float:
        """Total emissions for travelling this route."""
        return round(self.distance_km * self.carbon_per_km, 3)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<Route id={self.id} {self.from_location_id}->{self.to_location_id} "
            f"{self.distance_km}km>"
        )
