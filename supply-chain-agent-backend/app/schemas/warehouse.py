"""Warehouse schemas."""

from typing import Dict, Optional

from pydantic import Field, field_validator

from app.schemas.common import MAX_QUANTITY, ORMModel


def _check_inventory(value: Optional[Dict[int, int]]) -> Optional[Dict[int, int]]:
    """Apply the same bounds whether the inventory is set or patched."""
    for product_id, quantity in (value or {}).items():
        if product_id <= 0:
            raise ValueError("inventory keys must be positive product ids")
        if quantity < 0:
            raise ValueError("inventory quantities must be >= 0")
        if quantity > MAX_QUANTITY:
            raise ValueError(f"inventory quantities must be <= {MAX_QUANTITY}")
    return value


class WarehouseBase(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)
    #: product_id -> quantity on hand.
    inventory: Dict[int, int] = Field(default_factory=dict)

    @field_validator("inventory")
    @classmethod
    def _within_bounds(cls, value: Dict[int, int]) -> Dict[int, int]:
        return _check_inventory(value) or {}


class WarehouseCreate(WarehouseBase):
    pass


class WarehouseUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, min_length=1, max_length=120)
    inventory: Dict[int, int] | None = None

    @field_validator("inventory")
    @classmethod
    def _within_bounds(cls, value: Optional[Dict[int, int]]) -> Optional[Dict[int, int]]:
        return _check_inventory(value)


class WarehouseRead(WarehouseBase):
    id: int


class InventoryQuantityRead(ORMModel):
    """Stock level of a single product in a single warehouse."""

    warehouse_id: int
    product_id: int
    quantity: int


class InventorySetRequest(ORMModel):
    """Body for overwriting one stock level."""

    quantity: int = Field(ge=0, le=MAX_QUANTITY)
