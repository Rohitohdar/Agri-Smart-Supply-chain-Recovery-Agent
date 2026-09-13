"""Supplier schemas."""

from pydantic import Field

from app.schemas.common import (
    MAX_HOURS,
    MAX_QUANTITY,
    MAX_RATE,
    ORMModel,
)


class SupplierBase(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    product_id: int = Field(gt=0)
    price_per_unit: float = Field(gt=0, le=MAX_RATE)
    available_quantity: int = Field(ge=0, le=MAX_QUANTITY)
    delivery_hours: float = Field(gt=0, le=MAX_HOURS)
    carbon_per_unit: float = Field(ge=0, le=MAX_RATE)
    is_available: bool = True


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    product_id: int | None = Field(default=None, gt=0)
    price_per_unit: float | None = Field(default=None, gt=0, le=MAX_RATE)
    available_quantity: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    delivery_hours: float | None = Field(default=None, gt=0, le=MAX_HOURS)
    carbon_per_unit: float | None = Field(default=None, ge=0, le=MAX_RATE)
    is_available: bool | None = None


class SupplierRead(SupplierBase):
    id: int
