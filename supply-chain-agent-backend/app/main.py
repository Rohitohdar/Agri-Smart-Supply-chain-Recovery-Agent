"""FastAPI application entry point.

Run it with::

    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.config import get_settings
from app.db.base import create_all
from app.db.session import SessionLocal, engine
from app.models import Product
from app.ratelimit import install_rate_limiting
from app.routers import (
    actions,
    admin,
    agent,
    audit,
    audit_logs,
    dealers,
    demand,
    inventory,
    optimize,
    products,
    routes,
    shipments,
    simulate,
    suppliers,
    vendors,
    warehouses,
)
from app.security import warn_if_writes_are_open
from app.services.errors import ConflictError, NotFoundError
from app.utils import utcnow

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the schema (and seed an empty DB) before serving traffic."""
    create_all(engine)
    if settings.auto_seed:
        with SessionLocal() as db:
            is_empty = db.scalar(select(func.count()).select_from(Product)) == 0
        if is_empty:
            from app.db.seed import reset_database

            reset_database()
    warn_if_writes_are_open()
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Data layer for the supply chain agent. Entities, validation and a "
        "resettable seed scenario; agent logic comes later."
    ),
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS is restricted to the configured frontend origins (never ``*``; the
# setting rejects a wildcard) and to the methods and headers the API actually
# uses, so the browser is only told to allow what the frontend needs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)

install_rate_limiting(app)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "entity": exc.entity, "id": exc.entity_id},
    )


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    """A well-formed action that is infeasible against current state."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "reason": exc.reason},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "Request conflicts with existing data", "error": str(exc.orig)},
    )


@app.get("/health", tags=["meta"], summary="Liveness probe")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        #: False means mutating endpoints are open (development demo mode).
        "writes_authenticated": bool(settings.api_key),
        "time": utcnow().isoformat(),
    }


# CRUD resources first, then the read-only views, the state-changing actions
# and finally admin operations.
for module in (
    products,
    suppliers,
    warehouses,
    dealers,
    routes,
    shipments,
    audit_logs,
    inventory,
    vendors,
    demand,
    actions,
    optimize,
    simulate,
    agent,
    audit,
    admin,
):
    app.include_router(module.router)
