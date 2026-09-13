"""Generic CRUD service.

Every entity service subclasses :class:`CRUDService` with its own model and
create/update schemas, then adds entity specific queries.
"""

from collections.abc import Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.services.errors import NotFoundError

ModelT = TypeVar("ModelT", bound=Base)
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)


class CRUDService(Generic[ModelT, CreateT, UpdateT]):
    model: type[ModelT]
    label: str = "Object"
    default_limit: int = 100
    max_limit: int = 500

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- reads -------------------------------------------------------------
    def list(self, skip: int = 0, limit: int | None = None) -> Sequence[ModelT]:
        limit = min(limit or self.default_limit, self.max_limit)
        stmt = (
            select(self.model)
            .order_by(self.model.id)  # type: ignore[attr-defined]
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get(self, entity_id: int) -> ModelT | None:
        return self.db.get(self.model, entity_id)

    def get_or_404(self, entity_id: int) -> ModelT:
        obj = self.get(entity_id)
        if obj is None:
            raise NotFoundError(self.label, entity_id)
        return obj

    def count(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(self.model)) or 0)

    # --- writes ------------------------------------------------------------
    def create(self, data: CreateT) -> ModelT:
        obj = self.model(**data.model_dump())
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, entity_id: int, data: UpdateT) -> ModelT:
        obj = self.get_or_404(entity_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, entity_id: int) -> None:
        obj = self.get_or_404(entity_id)
        self.db.delete(obj)
        self.db.commit()
