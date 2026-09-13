"""Route service."""

from collections.abc import Sequence

from sqlalchemy import select

from app.models import Route
from app.schemas.route import RouteCreate, RouteUpdate
from app.services.base import CRUDService


class RouteService(CRUDService[Route, RouteCreate, RouteUpdate]):
    model = Route
    label = "Route"

    def list_available(self, to_location_id: int | None = None) -> Sequence[Route]:
        """Available routes, optionally those arriving at one location."""
        stmt = select(Route).where(Route.is_available.is_(True))
        if to_location_id is not None:
            stmt = stmt.where(Route.to_location_id == to_location_id)
        return list(self.db.scalars(stmt.order_by(Route.travel_time_hours)).all())

    def between(self, from_location_id: int, to_location_id: int) -> Sequence[Route]:
        """All routes linking two locations."""
        stmt = select(Route).where(
            Route.from_location_id == from_location_id,
            Route.to_location_id == to_location_id,
        )
        return list(self.db.scalars(stmt).all())
