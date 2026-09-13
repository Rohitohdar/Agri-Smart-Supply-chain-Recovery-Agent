"""Inventory view schemas.

Stock is modelled per location kind instead of as one hedged shape: warehouses
hold a ``product_id -> quantity`` map, while a dealer holds a single aggregate
number (``Dealer.current_inventory`` is not tied to a product in the schema).
The two are returned as a discriminated union on ``location_type``.
"""

from datetime import datetime
from typing import Annotated, Dict, Iterable, Literal, Union

from pydantic import Field, computed_field

from app.locations import LocationKind
from app.models import Dealer, Warehouse
from app.schemas.common import ORMModel
from app.utils import utcnow


class LocationStock(ORMModel):
    """Fields shared by every inventory location."""

    location_id: int
    name: str
    location: str


class WarehouseStock(LocationStock):
    """Per-product stock held by a warehouse."""

    location_type: Literal[LocationKind.WAREHOUSE] = LocationKind.WAREHOUSE
    #: product_id -> quantity on hand.
    inventory: Dict[int, int] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_quantity(self) -> int:
        """Everything currently held in this warehouse."""
        return sum(self.inventory.values())

    @classmethod
    def from_warehouse(cls, warehouse: Warehouse) -> "WarehouseStock":
        return cls(
            location_id=warehouse.id,
            name=warehouse.name,
            location=warehouse.location,
            inventory=warehouse.inventory,
        )


class DealerStock(LocationStock):
    """Stock held by a dealer, reported as its single aggregate number."""

    location_type: Literal[LocationKind.DEALER] = LocationKind.DEALER
    current_inventory: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_quantity(self) -> int:
        return self.current_inventory

    @classmethod
    def from_dealer(cls, dealer: Dealer) -> "DealerStock":
        return cls(
            location_id=dealer.id,
            name=dealer.name,
            location=dealer.location,
            current_inventory=dealer.current_inventory,
        )


#: Any single inventory location. FastAPI documents this as ``oneOf``.
LocationInventory = Annotated[
    Union[WarehouseStock, DealerStock], Field(discriminator="location_type")
]


class InventoryOverview(ORMModel):
    """Inventory across every stock-holding location."""

    generated_at: datetime
    warehouses: list[WarehouseStock] = Field(default_factory=list)
    dealers: list[DealerStock] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_quantity(self) -> int:
        """Total stock across all warehouses and dealers."""
        return sum(stock.total_quantity for stock in [*self.warehouses, *self.dealers])

    @classmethod
    def from_locations(
        cls, warehouses: Iterable[Warehouse], dealers: Iterable[Dealer]
    ) -> "InventoryOverview":
        """Build the overview from ORM rows (shared by the endpoint and the agent)."""
        return cls(
            generated_at=utcnow(),
            warehouses=[WarehouseStock.from_warehouse(w) for w in warehouses],
            dealers=[DealerStock.from_dealer(d) for d in dealers],
        )


def build_location_inventory(kind: LocationKind, obj: object) -> LocationInventory:
    """Build the right inventory view for a resolved location."""
    if kind is LocationKind.WAREHOUSE and isinstance(obj, Warehouse):
        return WarehouseStock.from_warehouse(obj)
    if kind is LocationKind.DEALER and isinstance(obj, Dealer):
        return DealerStock.from_dealer(obj)
    raise TypeError(f"{kind} does not hold inventory")
