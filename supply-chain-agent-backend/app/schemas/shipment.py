"""Shipment schemas."""

from datetime import datetime

from pydantic import Field

from app.models.shipment import ShipmentStatus
from app.schemas.common import MAX_HOURS, MAX_QUANTITY, ORMModel


class ShipmentBase(ORMModel):
    product_id: int = Field(gt=0)
    from_id: int = Field(gt=0)
    to_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    status: ShipmentStatus = ShipmentStatus.PENDING
    expected_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    delay_hours: float = Field(default=0.0, ge=0, le=MAX_HOURS)


class ShipmentCreate(ShipmentBase):
    pass


class ShipmentUpdate(ORMModel):
    product_id: int | None = Field(default=None, gt=0)
    from_id: int | None = Field(default=None, gt=0)
    to_id: int | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0, le=MAX_QUANTITY)
    status: ShipmentStatus | None = None
    expected_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    delay_hours: float | None = Field(default=None, ge=0, le=MAX_HOURS)


class ShipmentStatusUpdate(ORMModel):
    """Body for the dedicated status transition endpoint."""

    status: ShipmentStatus
    delay_hours: float | None = Field(default=None, ge=0, le=MAX_HOURS)
    actual_arrival: datetime | None = None


class ShipmentRead(ShipmentBase):
    id: int
