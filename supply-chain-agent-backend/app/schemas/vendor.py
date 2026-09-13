"""Vendor read model.

A *vendor* is the read-only view of a ``Supplier`` enriched with the details of
the product it sells — the shape the agent and the UI want for comparisons.
"""

from typing import Optional

from app.models import Product, Supplier
from app.schemas.common import ORMModel


class VendorRead(ORMModel):
    """One supplier with availability, price, delivery time and carbon."""

    id: int
    name: str
    product_id: int
    product_name: Optional[str] = None
    unit: Optional[str] = None
    price_per_unit: float
    available_quantity: int
    delivery_hours: float
    carbon_per_unit: float
    is_available: bool

    @classmethod
    def from_supplier(
        cls, supplier: Supplier, product: Optional[Product] = None
    ) -> "VendorRead":
        return cls(
            id=supplier.id,
            name=supplier.name,
            product_id=supplier.product_id,
            product_name=product.name if product else None,
            unit=product.unit if product else None,
            price_per_unit=supplier.price_per_unit,
            available_quantity=supplier.available_quantity,
            delivery_hours=supplier.delivery_hours,
            carbon_per_unit=supplier.carbon_per_unit,
            is_available=supplier.is_available,
        )
