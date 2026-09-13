"""Read-only vendor endpoints.

``/vendors`` is the supplier *view* used for comparisons; ``/suppliers`` remains
the CRUD resource.
"""

from fastapi import APIRouter, Query

from app.routers.deps import LimitQuery, SkipQuery, VendorServiceDep
from app.schemas.vendor import VendorRead

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get(
    "",
    response_model=list[VendorRead],
    summary="All vendors with availability, price, delivery time and carbon",
)
def list_vendors(
    service: VendorServiceDep,
    skip: SkipQuery = 0,
    limit: LimitQuery = 100,
    only_available: bool = Query(
        default=False, description="Return only vendors flagged available"
    ),
    product_id: int | None = Query(default=None, gt=0, description="Filter by product"),
):
    rows = service.list(
        skip=skip,
        limit=limit,
        only_available=only_available,
        product_id=product_id,
    )
    return [VendorRead.from_supplier(supplier, product) for supplier, product in rows]


@router.get("/{vendor_id}", response_model=VendorRead, summary="Vendor detail")
def get_vendor(vendor_id: int, service: VendorServiceDep):
    supplier, product = service.get(vendor_id)
    return VendorRead.from_supplier(supplier, product)
