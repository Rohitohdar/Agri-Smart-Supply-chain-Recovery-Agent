"""ORM models. Importing this package registers every table on ``Base``."""

from app.models.audit_log import Actor, AuditLog
from app.models.dealer import Dealer
from app.models.product import Product
from app.models.route import Route
from app.models.shipment import Shipment, ShipmentStatus, TERMINAL_STATUSES
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse

__all__ = [
    "Actor",
    "AuditLog",
    "Dealer",
    "Product",
    "Route",
    "Shipment",
    "ShipmentStatus",
    "TERMINAL_STATUSES",
    "Supplier",
    "Warehouse",
]
