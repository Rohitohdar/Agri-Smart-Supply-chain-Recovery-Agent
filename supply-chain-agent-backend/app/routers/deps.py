"""FastAPI dependencies: one provider per service, all annotated for reuse."""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.action_service import ActionService
from app.services.audit_log_service import AuditLogService
from app.services.dealer_service import DealerService
from app.services.demand_service import DemandService
from app.services.inventory_service import InventoryService
from app.services.optimizer_service import OptimizerService
from app.services.product_service import ProductService
from app.services.route_service import RouteService
from app.services.shipment_service import ShipmentService
from app.services.supplier_service import SupplierService
from app.services.vendor_service import VendorService
from app.services.warehouse_service import WarehouseService

DbSession = Annotated[Session, Depends(get_db)]


def get_product_service(db: DbSession) -> ProductService:
    return ProductService(db)


def get_supplier_service(db: DbSession) -> SupplierService:
    return SupplierService(db)


def get_warehouse_service(db: DbSession) -> WarehouseService:
    return WarehouseService(db)


def get_dealer_service(db: DbSession) -> DealerService:
    return DealerService(db)


def get_route_service(db: DbSession) -> RouteService:
    return RouteService(db)


def get_shipment_service(db: DbSession) -> ShipmentService:
    return ShipmentService(db)


def get_audit_log_service(db: DbSession) -> AuditLogService:
    return AuditLogService(db)


def get_inventory_service(db: DbSession) -> InventoryService:
    return InventoryService(db)


def get_vendor_service(db: DbSession) -> VendorService:
    return VendorService(db)


def get_demand_service(db: DbSession) -> DemandService:
    return DemandService(db)


def get_action_service(db: DbSession) -> ActionService:
    return ActionService(db)


def get_optimizer_service(db: DbSession) -> OptimizerService:
    return OptimizerService(db)


ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
SupplierServiceDep = Annotated[SupplierService, Depends(get_supplier_service)]
WarehouseServiceDep = Annotated[WarehouseService, Depends(get_warehouse_service)]
DealerServiceDep = Annotated[DealerService, Depends(get_dealer_service)]
RouteServiceDep = Annotated[RouteService, Depends(get_route_service)]
ShipmentServiceDep = Annotated[ShipmentService, Depends(get_shipment_service)]
AuditLogServiceDep = Annotated[AuditLogService, Depends(get_audit_log_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]
VendorServiceDep = Annotated[VendorService, Depends(get_vendor_service)]
DemandServiceDep = Annotated[DemandService, Depends(get_demand_service)]
ActionServiceDep = Annotated[ActionService, Depends(get_action_service)]
OptimizerServiceDep = Annotated[OptimizerService, Depends(get_optimizer_service)]

#: Query parameters shared by list endpoints.
SkipQuery = Annotated[int, Query(ge=0, description="Rows to skip")]
LimitQuery = Annotated[int, Query(ge=1, le=500, description="Max rows to return")]
