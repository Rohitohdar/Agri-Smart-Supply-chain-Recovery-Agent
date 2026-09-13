"""Route schemas."""

from pydantic import Field

from app.schemas.common import MAX_DISTANCE_KM, MAX_HOURS, MAX_RATE, ORMModel


class RouteBase(ORMModel):
    from_location_id: int = Field(gt=0)
    to_location_id: int = Field(gt=0)
    distance_km: float = Field(gt=0, le=MAX_DISTANCE_KM)
    travel_time_hours: float = Field(gt=0, le=MAX_HOURS)
    carbon_per_km: float = Field(ge=0, le=MAX_RATE)
    is_available: bool = True


class RouteCreate(RouteBase):
    pass


class RouteUpdate(ORMModel):
    from_location_id: int | None = Field(default=None, gt=0)
    to_location_id: int | None = Field(default=None, gt=0)
    distance_km: float | None = Field(default=None, gt=0, le=MAX_DISTANCE_KM)
    travel_time_hours: float | None = Field(default=None, gt=0, le=MAX_HOURS)
    carbon_per_km: float | None = Field(default=None, ge=0, le=MAX_RATE)
    is_available: bool | None = None


class RouteRead(RouteBase):
    id: int
    carbon_emission: float
