"""Warehouse endpoints, including per-product inventory access."""

from fastapi import APIRouter, status

from app.routers.deps import LimitQuery, SkipQuery, WarehouseServiceDep
from app.schemas.warehouse import (
    InventoryQuantityRead,
    InventorySetRequest,
    WarehouseCreate,
    WarehouseRead,
    WarehouseUpdate,
)
from app.security import WRITE_GUARD

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get("", response_model=list[WarehouseRead], summary="List warehouses")
def list_warehouses(
    service: WarehouseServiceDep, skip: SkipQuery = 0, limit: LimitQuery = 100
):
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=WarehouseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a warehouse",
    dependencies=WRITE_GUARD,
)
def create_warehouse(payload: WarehouseCreate, service: WarehouseServiceDep):
    return service.create(payload)


@router.get("/{warehouse_id}", response_model=WarehouseRead, summary="Get a warehouse")
def get_warehouse(warehouse_id: int, service: WarehouseServiceDep):
    return service.get_or_404(warehouse_id)


@router.patch(
    "/{warehouse_id}",
    response_model=WarehouseRead,
    summary="Update a warehouse",
    dependencies=WRITE_GUARD,
)
def update_warehouse(
    warehouse_id: int, payload: WarehouseUpdate, service: WarehouseServiceDep
):
    return service.update(warehouse_id, payload)


@router.delete(
    "/{warehouse_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a warehouse",
    dependencies=WRITE_GUARD,
)
def delete_warehouse(warehouse_id: int, service: WarehouseServiceDep) -> None:
    service.delete(warehouse_id)


@router.get(
    "/{warehouse_id}/inventory/{product_id}",
    response_model=InventoryQuantityRead,
    summary="Read one stock level",
)
def get_inventory_quantity(
    warehouse_id: int, product_id: int, service: WarehouseServiceDep
):
    return InventoryQuantityRead(
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=service.quantity_of(warehouse_id, product_id),
    )


@router.put(
    "/{warehouse_id}/inventory/{product_id}",
    response_model=WarehouseRead,
    summary="Set one stock level",
    dependencies=WRITE_GUARD,
)
def set_inventory_quantity(
    warehouse_id: int,
    product_id: int,
    payload: InventorySetRequest,
    service: WarehouseServiceDep,
):
    return service.set_quantity(warehouse_id, product_id, payload.quantity)
