"""Dealer schemas."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import MAX_QUANTITY, ORMModel


class DealerBase(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)
    required_quantity: int = Field(gt=0, le=MAX_QUANTITY)
    deadline: datetime
    current_inventory: int = Field(ge=0, le=MAX_QUANTITY)


class DealerCreate(DealerBase):
    pass


class DealerUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, min_length=1, max_length=120)
    required_quantity: int | None = Field(default=None, gt=0, le=MAX_QUANTITY)
    deadline: datetime | None = None
    current_inventory: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)


class DealerRead(DealerBase):
    id: int
    shortfall: int
