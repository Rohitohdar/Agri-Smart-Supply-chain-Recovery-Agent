"""Supplier service."""

from collections.abc import Sequence

from sqlalchemy import select

from app.models import Supplier
from app.schemas.supplier import SupplierCreate, SupplierUpdate
from app.services.base import CRUDService


class SupplierService(CRUDService[Supplier, SupplierCreate, SupplierUpdate]):
    model = Supplier
    label = "Supplier"

    def list_available(self, product_id: int | None = None) -> Sequence[Supplier]:
        """Available suppliers, optionally narrowed to one product."""
        stmt = select(Supplier).where(Supplier.is_available.is_(True))
        if product_id is not None:
            stmt = stmt.where(Supplier.product_id == product_id)
        return list(self.db.scalars(stmt.order_by(Supplier.price_per_unit)).all())

    def cheapest_available(self, product_id: int, quantity: int = 1) -> Supplier | None:
        """Cheapest available supplier that can cover ``quantity``."""
        stmt = (
            select(Supplier)
            .where(
                Supplier.product_id == product_id,
                Supplier.is_available.is_(True),
                Supplier.available_quantity >= quantity,
            )
            .order_by(Supplier.price_per_unit)
            .limit(1)
        )
        return self.db.scalars(stmt).first()
