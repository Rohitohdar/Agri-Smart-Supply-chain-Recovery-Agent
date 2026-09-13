"""Product endpoints."""

from fastapi import APIRouter, status

from app.routers.deps import LimitQuery, ProductServiceDep, SkipQuery
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.security import WRITE_GUARD

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead], summary="List products")
def list_products(service: ProductServiceDep, skip: SkipQuery = 0, limit: LimitQuery = 100):
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    dependencies=WRITE_GUARD,
)
def create_product(payload: ProductCreate, service: ProductServiceDep):
    return service.create(payload)


@router.get("/{product_id}", response_model=ProductRead, summary="Get a product")
def get_product(product_id: int, service: ProductServiceDep):
    return service.get_or_404(product_id)


@router.patch(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update a product",
    dependencies=WRITE_GUARD,
)
def update_product(
    product_id: int, payload: ProductUpdate, service: ProductServiceDep
):
    return service.update(product_id, payload)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product",
    dependencies=WRITE_GUARD,
)
def delete_product(product_id: int, service: ProductServiceDep) -> None:
    service.delete(product_id)
