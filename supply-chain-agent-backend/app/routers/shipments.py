"""Shipment endpoints."""

from fastapi import APIRouter, Query, status

from app.models import ShipmentStatus
from app.routers.deps import LimitQuery, ShipmentServiceDep, SkipQuery
from app.schemas.shipment import (
    ShipmentCreate,
    ShipmentRead,
    ShipmentStatusUpdate,
    ShipmentUpdate,
)
from app.security import WRITE_GUARD

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=list[ShipmentRead], summary="List shipments")
def list_shipments(
    service: ShipmentServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    status_filter: ShipmentStatus | None = Query(
        default=None, alias="status", description="Filter by shipment status"
    ),
    to_id: int | None = Query(default=None, gt=0, description="Destination location"),
):
    if status_filter is not None:
        return service.list_by_status(status_filter)[skip : skip + limit]
    if to_id is not None:
        return service.inbound_to(to_id)[skip : skip + limit]
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=ShipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shipment",
    dependencies=WRITE_GUARD,
)
def create_shipment(payload: ShipmentCreate, service: ShipmentServiceDep):
    return service.create(payload)


@router.get("/{shipment_id}", response_model=ShipmentRead, summary="Get a shipment")
def get_shipment(shipment_id: int, service: ShipmentServiceDep):
    return service.get_or_404(shipment_id)


@router.patch(
    "/{shipment_id}",
    response_model=ShipmentRead,
    summary="Update a shipment",
    dependencies=WRITE_GUARD,
)
def update_shipment(
    shipment_id: int, payload: ShipmentUpdate, service: ShipmentServiceDep
):
    return service.update(shipment_id, payload)


@router.patch(
    "/{shipment_id}/status",
    response_model=ShipmentRead,
    summary="Transition a shipment's status",
    dependencies=WRITE_GUARD,
)
def set_shipment_status(
    shipment_id: int, payload: ShipmentStatusUpdate, service: ShipmentServiceDep
):
    return service.set_status(shipment_id, payload)


@router.delete(
    "/{shipment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a shipment",
    dependencies=WRITE_GUARD,
)
def delete_shipment(shipment_id: int, service: ShipmentServiceDep) -> None:
    service.delete(shipment_id)
