"""Route endpoints."""

from fastapi import APIRouter, Query, status

from app.routers.deps import LimitQuery, RouteServiceDep, SkipQuery
from app.schemas.route import RouteCreate, RouteRead, RouteUpdate
from app.security import WRITE_GUARD

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("", response_model=list[RouteRead], summary="List routes")
def list_routes(
    service: RouteServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    to_location_id: int | None = Query(
        default=None, gt=0, description="Filter by destination location"
    ),
    only_available: bool = Query(
        default=False, description="Return only routes flagged available"
    ),
):
    if only_available:
        return service.list_available(to_location_id=to_location_id)[skip : skip + limit]
    if to_location_id is not None:
        return [
            route
            for route in service.list(limit=service.max_limit)
            if route.to_location_id == to_location_id
        ][skip : skip + limit]
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=RouteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a route",
    dependencies=WRITE_GUARD,
)
def create_route(payload: RouteCreate, service: RouteServiceDep):
    return service.create(payload)


@router.get("/{route_id}", response_model=RouteRead, summary="Get a route")
def get_route(route_id: int, service: RouteServiceDep):
    return service.get_or_404(route_id)


@router.patch(
    "/{route_id}",
    response_model=RouteRead,
    summary="Update a route",
    dependencies=WRITE_GUARD,
)
def update_route(route_id: int, payload: RouteUpdate, service: RouteServiceDep):
    return service.update(route_id, payload)


@router.delete(
    "/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a route",
    dependencies=WRITE_GUARD,
)
def delete_route(route_id: int, service: RouteServiceDep) -> None:
    service.delete(route_id)
