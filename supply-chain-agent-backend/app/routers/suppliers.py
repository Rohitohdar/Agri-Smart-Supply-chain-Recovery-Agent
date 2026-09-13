"""Supplier endpoints."""

from fastapi import APIRouter, Query, status

from app.routers.deps import LimitQuery, SkipQuery, SupplierServiceDep
from app.schemas.supplier import SupplierCreate, SupplierRead, SupplierUpdate
from app.security import WRITE_GUARD

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierRead], summary="List suppliers")
def list_suppliers(
    service: SupplierServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    product_id: int | None = Query(default=None, gt=0, description="Filter by product"),
    only_available: bool = Query(
        default=False, description="Return only suppliers flagged available"
    ),
):
    if only_available:
        suppliers = service.list_available(product_id=product_id)
        return suppliers[skip : skip + limit]
    if product_id is not None:
        suppliers = [
            supplier
            for supplier in service.list(limit=service.max_limit)
            if supplier.product_id == product_id
        ]
        return suppliers[skip : skip + limit]
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a supplier",
    dependencies=WRITE_GUARD,
)
def create_supplier(payload: SupplierCreate, service: SupplierServiceDep):
    return service.create(payload)


@router.get("/{supplier_id}", response_model=SupplierRead, summary="Get a supplier")
def get_supplier(supplier_id: int, service: SupplierServiceDep):
    return service.get_or_404(supplier_id)


@router.patch(
    "/{supplier_id}",
    response_model=SupplierRead,
    summary="Update a supplier",
    dependencies=WRITE_GUARD,
)
def update_supplier(
    supplier_id: int, payload: SupplierUpdate, service: SupplierServiceDep
):
    return service.update(supplier_id, payload)


@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a supplier",
    dependencies=WRITE_GUARD,
)
def delete_supplier(supplier_id: int, service: SupplierServiceDep) -> None:
    service.delete(supplier_id)
