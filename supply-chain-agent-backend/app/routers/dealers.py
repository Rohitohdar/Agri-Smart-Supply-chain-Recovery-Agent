"""Dealer endpoints."""

from fastapi import APIRouter, status

from app.routers.deps import DealerServiceDep, LimitQuery, SkipQuery
from app.schemas.dealer import DealerCreate, DealerRead, DealerUpdate
from app.security import WRITE_GUARD

router = APIRouter(prefix="/dealers", tags=["dealers"])


@router.get("", response_model=list[DealerRead], summary="List dealers")
def list_dealers(service: DealerServiceDep, skip: SkipQuery = 0, limit: LimitQuery = 100):
    return service.list(skip=skip, limit=limit)


@router.post(
    "",
    response_model=DealerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dealer",
    dependencies=WRITE_GUARD,
)
def create_dealer(payload: DealerCreate, service: DealerServiceDep):
    return service.create(payload)


@router.get("/{dealer_id}", response_model=DealerRead, summary="Get a dealer")
def get_dealer(dealer_id: int, service: DealerServiceDep):
    return service.get_or_404(dealer_id)


@router.patch(
    "/{dealer_id}",
    response_model=DealerRead,
    summary="Update a dealer",
    dependencies=WRITE_GUARD,
)
def update_dealer(dealer_id: int, payload: DealerUpdate, service: DealerServiceDep):
    return service.update(dealer_id, payload)


@router.delete(
    "/{dealer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dealer",
    dependencies=WRITE_GUARD,
)
def delete_dealer(dealer_id: int, service: DealerServiceDep) -> None:
    service.delete(dealer_id)
