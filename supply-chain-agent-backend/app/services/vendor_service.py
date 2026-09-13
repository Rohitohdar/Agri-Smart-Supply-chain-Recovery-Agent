"""Vendor service: suppliers paired with the product they sell."""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Product, Supplier
from app.services.product_service import ProductService
from app.services.supplier_service import SupplierService

#: A supplier paired with its product (``None`` if the product row is missing).
VendorRow = Tuple[Supplier, Optional[Product]]


class VendorService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.suppliers = SupplierService(db)
        self.products = ProductService(db)

    def list(
        self,
        *,
        skip: int = 0,
        limit: int | None = None,
        only_available: bool = False,
        product_id: int | None = None,
    ) -> list[VendorRow]:
        """Vendors ordered by price per unit, cheapest first."""
        limit = min(limit or self.suppliers.default_limit, self.suppliers.max_limit)
        if only_available:
            candidates = list(self.suppliers.list_available(product_id=product_id))
        else:
            candidates = [
                supplier
                for supplier in self.suppliers.list(limit=self.suppliers.max_limit)
                if product_id is None or supplier.product_id == product_id
            ]

        candidates.sort(key=lambda supplier: (supplier.price_per_unit, supplier.id))
        products = {
            product.id: product
            for product in self.products.list(limit=self.products.max_limit)
        }
        page = candidates[skip : skip + limit]
        return [(supplier, products.get(supplier.product_id)) for supplier in page]

    def get(self, vendor_id: int) -> VendorRow:
        """One vendor, or a 404 when the supplier id does not exist."""
        supplier = self.suppliers.get_or_404(vendor_id)
        return supplier, self.products.get(supplier.product_id)
