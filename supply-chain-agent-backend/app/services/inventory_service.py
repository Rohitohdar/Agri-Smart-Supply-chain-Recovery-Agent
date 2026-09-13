"""Inventory service.

Resolves location ids from the shared namespace (``app.locations``) and returns
the ORM object behind them; building the HTTP read model is the router's job.
"""

from typing import Tuple, Union

from sqlalchemy.orm import Session

from app.locations import LocationKind, kind_of
from app.models import Dealer, Warehouse
from app.services.dealer_service import DealerService
from app.services.errors import NotFoundError
from app.services.warehouse_service import WarehouseService

#: A location that can hold stock.
StockLocation = Union[Warehouse, Dealer]


class InventoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.warehouses = WarehouseService(db)
        self.dealers = DealerService(db)

    def overview(self) -> Tuple[list[Warehouse], list[Dealer]]:
        """Every warehouse and every dealer."""
        return (
            list(self.warehouses.list(limit=self.warehouses.max_limit)),
            list(self.dealers.list(limit=self.dealers.max_limit)),
        )

    def resolve(self, location_id: int) -> Tuple[LocationKind, StockLocation]:
        """Map a location id onto ``(kind, warehouse or dealer)``.

        Suppliers are locations in the shipping graph but hold no inventory, so
        they are rejected with a pointer to the vendor view. Ids outside every
        reserved range are a plain 404.
        """
        kind = kind_of(location_id)
        if kind is LocationKind.WAREHOUSE:
            return kind, self.warehouses.get_or_404(location_id)
        if kind is LocationKind.DEALER:
            return kind, self.dealers.get_or_404(location_id)
        if kind is LocationKind.SUPPLIER:
            raise NotFoundError(
                "Location",
                location_id,
                detail=(
                    f"Location {location_id} is a supplier, which holds no inventory; "
                    f"supplier availability is at /vendors/{location_id}"
                ),
            )
        raise NotFoundError(
            "Location",
            location_id,
            detail=(
                f"Location {location_id} is outside the location id namespace "
                "(suppliers 1-99, warehouses 101-199, dealers 201-299)"
            ),
        )
