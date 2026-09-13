"""Warehouse service, including inventory helpers."""

from app.models import Warehouse
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate
from app.services.base import CRUDService


class WarehouseService(CRUDService[Warehouse, WarehouseCreate, WarehouseUpdate]):
    model = Warehouse
    label = "Warehouse"

    def quantity_of(self, warehouse_id: int, product_id: int) -> int:
        """Quantity of one product held by a warehouse."""
        return self.get_or_404(warehouse_id).quantity_of(product_id)

    def set_quantity(self, warehouse_id: int, product_id: int, quantity: int) -> Warehouse:
        """Overwrite the stock level for one product."""
        warehouse = self.get_or_404(warehouse_id)
        warehouse.set_quantity(product_id, quantity)
        self.db.commit()
        self.db.refresh(warehouse)
        return warehouse

    def adjust_quantity(
        self, warehouse_id: int, product_id: int, delta: int
    ) -> Warehouse:
        """Add (or subtract) stock, never going below zero."""
        warehouse = self.get_or_404(warehouse_id)
        warehouse.set_quantity(product_id, max(warehouse.quantity_of(product_id) + delta, 0))
        self.db.commit()
        self.db.refresh(warehouse)
        return warehouse

    def inventory_of(self, product_id: int) -> dict[int, int]:
        """Available stock per warehouse id for one product."""
        return {
            warehouse.id: warehouse.quantity_of(product_id)
            for warehouse in self.list(limit=self.max_limit)
        }
