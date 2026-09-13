"""Product model."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    """A tradeable item, e.g. ``Urea`` measured in ``bag``."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Product id={self.id} name={self.name!r} unit={self.unit!r}>"
