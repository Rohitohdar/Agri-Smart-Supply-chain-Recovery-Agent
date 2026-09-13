"""Warehouse model."""

from typing import Dict

from sqlalchemy import JSON, String
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Warehouse(Base):
    """A storage location holding stock per product.

    ``inventory`` maps ``product_id -> quantity``. JSON object keys are always
    strings, so helpers below coerce ids to keep call sites honest.
    """

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    # MutableDict so in-place edits are detected by the ORM.
    inventory: Mapped[Dict[str, int]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=False, default=dict
    )

    def quantity_of(self, product_id: int) -> int:
        """Quantity on hand for ``product_id`` (0 when the product is absent)."""
        return int(self.inventory.get(str(product_id), 0))

    def set_quantity(self, product_id: int, quantity: int) -> None:
        """Set the quantity for ``product_id`` (reassigning keeps change tracking)."""
        updated = dict(self.inventory)
        updated[str(product_id)] = int(quantity)
        self.inventory = updated

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Warehouse id={self.id} name={self.name!r} inventory={self.inventory}>"
