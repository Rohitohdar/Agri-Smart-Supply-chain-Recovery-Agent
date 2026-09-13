"""Product schemas."""

from pydantic import Field

from app.schemas.common import ORMModel


class ProductBase(ORMModel):
    name: str = Field(min_length=1, max_length=120, examples=["Urea"])
    unit: str = Field(min_length=1, max_length=32, examples=["bag"])


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=32)


class ProductRead(ProductBase):
    id: int
