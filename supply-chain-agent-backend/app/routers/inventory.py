"""Read-only inventory endpoints."""

from fastapi import APIRouter

from app.routers.deps import InventoryServiceDep
from app.schemas.inventory import (
    InventoryOverview,
    LocationInventory,
    build_location_inventory,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get(
    "",
    response_model=InventoryOverview,
    summary="Inventory for every warehouse and the dealer",
)
def get_inventory(service: InventoryServiceDep):
    return InventoryOverview.from_locations(*service.overview())


@router.get(
    "/{location_id}",
    response_model=LocationInventory,
    summary="Inventory for one location",
    description=(
        "Resolves the id through the shared location namespace (warehouses "
        "101-199, dealers 201-299). Supplier ids are locations too but hold no "
        "inventory, so they return 404 pointing at /vendors/{id}."
    ),
)
def get_location_inventory(location_id: int, service: InventoryServiceDep):
    kind, location = service.resolve(location_id)
    return build_location_inventory(kind, location)
