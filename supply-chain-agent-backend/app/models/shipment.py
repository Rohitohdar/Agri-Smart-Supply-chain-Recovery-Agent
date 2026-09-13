"""Shipment model."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShipmentStatus(str, enum.Enum):
    """Lifecycle of a shipment."""

    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    ARRIVED = "ARRIVED"
    #: Added in the action milestone so ``POST /shipment/{id}/cancel`` has a
    #: representable outcome: a cancelled shipment keeps its row (and therefore
    #: its audit history) but stops counting as active demand.
    CANCELLED = "CANCELLED"


#: Statuses that end a shipment's life. A terminal shipment can no longer be
#: rerouted or cancelled, and it no longer counts towards inbound supply.
TERMINAL_STATUSES: frozenset["ShipmentStatus"] = frozenset(
    {ShipmentStatus.ARRIVED, ShipmentStatus.CANCELLED}
)


class Shipment(Base):
    """A movement of goods between two location nodes.

    ``from_id`` / ``to_id`` follow the same location namespace as ``Route``
    (suppliers 1-99, warehouses 101-199, dealers 201-299).
    """

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )
    from_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    to_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=ShipmentStatus.PENDING,
    )
    expected_arrival: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    actual_arrival: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delay_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    @property
    def is_active(self) -> bool:
        """Whether this shipment is still expected to land."""
        return self.status not in TERMINAL_STATUSES

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<Shipment id={self.id} qty={self.quantity} status={self.status.value}>"
        )
