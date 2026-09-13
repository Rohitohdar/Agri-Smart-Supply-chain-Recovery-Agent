"""The agent's tools.

Every tool is a *thin* wrapper: it calls the same service function the matching
REST endpoint calls, builds the same response schema and returns
``model_dump(mode="json")``. No tool reimplements a rule, and none of them
compute cost, delivery or carbon — those numbers exist only in the Step 5
optimizer, which ``optimize_recovery`` delegates to.

===========================  ==========================================
Tool                         Backend endpoint it wraps
===========================  ==========================================
``get_inventory``            ``GET /inventory``
``get_vendors``              ``GET /vendors``
``get_shipments``            ``GET /shipments``
``get_routes``               ``GET /routes``
``get_demand``               ``GET /demand``
``optimize_recovery``        ``POST /optimize/recovery``
``transfer_inventory``       ``POST /inventory/transfer``
``purchase_from_vendor``     ``POST /vendor/{id}/purchase``
``reroute_shipment``         ``POST /shipment/{id}/reroute``
``verify_state``             ``GET /demand`` + ``GET /routes``
===========================  ==========================================

Mutating tools go through :class:`~app.services.action_service.ActionService`,
so the agent inherits the same validation and the same atomic audit entry as any
other caller — and those audit rows are attributed to ``agent``.

``verify_state`` is the one composite tool. It combines fields the backend has
*already computed* (``available_quantity``, ``active_shipments[].quantity``,
``expected_arrival``, ``required_quantity``) into a coverage verdict. It derives
no cost, delivery or carbon metric.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.orm import Session

from app.models import Actor
from app.optimizer import RecoveryPlan
from app.schemas.actions import (
    InventoryTransferRequest,
    InventoryTransferResponse,
    ShipmentRerouteRequest,
    VendorPurchaseRequest,
    VendorPurchaseResponse,
)
from app.schemas.demand import DemandResponse
from app.schemas.inventory import InventoryOverview
from app.schemas.optimize import RecoveryPlanResponse
from app.schemas.route import RouteRead
from app.schemas.shipment import ShipmentRead
from app.schemas.vendor import VendorRead
from app.services.action_service import ActionService
from app.services.demand_service import DemandService
from app.services.errors import ServiceError
from app.services.inventory_service import InventoryService
from app.services.optimizer_service import OptimizerService
from app.services.route_service import RouteService
from app.services.shipment_service import ShipmentService
from app.services.vendor_service import VendorService

#: name -> (human description, backend endpoint). Shared with ``GET /agent/tools``.
TOOL_SPECS: Dict[str, tuple[str, str]] = {
    "get_inventory": (
        "Current stock for every warehouse and the dealer.",
        "GET /inventory",
    ),
    "get_vendors": (
        "Every vendor with availability, price, delivery time and carbon.",
        "GET /vendors",
    ),
    "get_shipments": ("Every shipment with its status.", "GET /shipments"),
    "get_routes": ("Every route with its availability.", "GET /routes"),
    "get_demand": (
        "Dealer requirement, stock, deadline, shortage and constraint status.",
        "GET /demand",
    ),
    "optimize_recovery": (
        "Rank feasible recovery actions for a shortage/deadline. The only place "
        "cost, delivery and carbon are computed.",
        "POST /optimize/recovery",
    ),
    "transfer_inventory": (
        "Move stock from a warehouse to another location (validated, atomic).",
        "POST /inventory/transfer",
    ),
    "purchase_from_vendor": (
        "Reserve vendor stock and create an inbound shipment (validated, atomic).",
        "POST /vendor/{id}/purchase",
    ),
    "reroute_shipment": (
        "Put a shipment on a different available route (validated, atomic).",
        "POST /shipment/{id}/reroute",
    ),
    "verify_state": (
        "Re-read demand and routes and report whether the requirement is covered.",
        "GET /demand + GET /routes",
    ),
}

#: Tools that change state (everything else is read-only).
MUTATING_TOOLS = frozenset(
    {"transfer_inventory", "purchase_from_vendor", "reroute_shipment"}
)


@dataclass
class ToolResult:
    """The outcome of one tool call, raw result included."""

    name: str
    ok: bool
    data: Any = None
    error: Optional[str] = None
    #: Machine-readable refusal code for a rejected action.
    reason: Optional[str] = None


class Toolbox:
    """All ten tools, bound to one database session."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.vendors = VendorService(db)
        self.shipments = ShipmentService(db)
        self.routes = RouteService(db)
        self.demand = DemandService(db)
        self.optimizer = OptimizerService(db)
        self.actions = ActionService(db)

    # --- dispatch ----------------------------------------------------------
    def call(self, name: str, **arguments: Any) -> ToolResult:
        """Invoke a tool by name, turning a refusal into a failed result.

        Domain errors (a 409/404 from the action layer) are *returned*, not
        raised: the loop replans on them instead of crashing.
        """
        if name not in TOOL_SPECS:
            raise KeyError(f"unknown tool {name!r}")
        method = getattr(self, name)
        try:
            return ToolResult(name=name, ok=True, data=method(**arguments))
        except ServiceError as exc:
            return ToolResult(
                name=name,
                ok=False,
                error=str(exc),
                reason=getattr(exc, "reason", None),
            )

    # --- read-only tools ---------------------------------------------------
    def get_inventory(self) -> Dict[str, Any]:
        warehouses, dealers = self.inventory.overview()
        return InventoryOverview.from_locations(warehouses, dealers).model_dump(
            mode="json"
        )

    def get_vendors(self) -> List[Dict[str, Any]]:
        return [
            VendorRead.from_supplier(supplier, product).model_dump(mode="json")
            for supplier, product in self.vendors.list()
        ]

    def get_shipments(self) -> List[Dict[str, Any]]:
        return [
            ShipmentRead.model_validate(shipment).model_dump(mode="json")
            for shipment in self.shipments.list(limit=self.shipments.max_limit)
        ]

    def get_routes(self) -> List[Dict[str, Any]]:
        return [
            RouteRead.model_validate(route).model_dump(mode="json")
            for route in self.routes.list(limit=self.routes.max_limit)
        ]

    def get_demand(self) -> Dict[str, Any]:
        dealer = self.demand.dealer_or_default(None)
        active = self.demand.active_shipments(dealer.id)
        return DemandResponse.from_dealer(dealer, list(active)).model_dump(mode="json")

    # --- optimizer (the only source of cost/delivery/carbon) ---------------
    def optimize_recovery(
        self, shortage_quantity: int, deadline: Union[datetime, str]
    ) -> Dict[str, Any]:
        """Rank recovery options. ``deadline`` is passed through from ``get_demand``."""
        moment = (
            deadline
            if isinstance(deadline, datetime)
            else datetime.fromisoformat(deadline)
        )
        plan: RecoveryPlan = self.optimizer.plan(
            shortage_quantity=shortage_quantity, deadline=moment
        )
        return RecoveryPlanResponse.from_plan(plan).model_dump(mode="json")

    # --- mutating tools ----------------------------------------------------
    def transfer_inventory(
        self, from_id: int, to_id: int, quantity: int
    ) -> Dict[str, Any]:
        response: InventoryTransferResponse = self.actions.transfer_inventory(
            InventoryTransferRequest(
                from_warehouse_id=from_id, to_id=to_id, quantity=quantity
            ),
            actor=Actor.AGENT,
        )
        return response.model_dump(mode="json")

    def purchase_from_vendor(self, vendor_id: int, quantity: int) -> Dict[str, Any]:
        response: VendorPurchaseResponse = self.actions.purchase_from_vendor(
            vendor_id, VendorPurchaseRequest(quantity=quantity), actor=Actor.AGENT
        )
        return response.model_dump(mode="json")

    def reroute_shipment(self, shipment_id: int, new_route_id: int) -> Dict[str, Any]:
        response = self.actions.reroute_shipment(
            shipment_id,
            ShipmentRerouteRequest(new_route_id=new_route_id),
            actor=Actor.AGENT,
        )
        return response.model_dump(mode="json")

    # --- composite verification -------------------------------------------
    def verify_state(self) -> Dict[str, Any]:
        """Re-read demand and routes and decide whether the requirement is met.

        The verdict uses only backend-computed numbers: the dealer is covered
        when stock on hand plus the inbound quantity arriving *by the deadline*
        reaches the requirement.
        """
        demand = self.get_demand()
        routes = self.get_routes()
        return {**self._coverage(demand), "demand": demand, "routes": routes}

    @staticmethod
    def _coverage(demand: Dict[str, Any]) -> Dict[str, Any]:
        deadline = datetime.fromisoformat(demand["deadline"])
        required = demand["required_quantity"]
        available = demand["available_quantity"]

        on_time = 0
        late: List[int] = []
        unknown_eta: List[int] = []
        for shipment in demand["active_shipments"]:
            expected = shipment.get("expected_arrival")
            if expected is None:
                unknown_eta.append(shipment["id"])
            elif datetime.fromisoformat(expected) <= deadline:
                on_time += shipment["quantity"]
            else:
                late.append(shipment["id"])

        covered = available + on_time
        return {
            "required_quantity": required,
            "available_quantity": available,
            "on_time_inbound_quantity": on_time,
            "covered_quantity": covered,
            "satisfied": covered >= required,
            "late_shipment_ids": late,
            "unknown_eta_shipment_ids": unknown_eta,
            # The raw backend verdict, reported unchanged for comparison.
            "constraint_violated": demand["constraint_violated"],
            "shortage": demand["shortage"],
        }


def tool_catalogue() -> List[Dict[str, str]]:
    """Name, description and endpoint for every tool (for ``GET /agent/tools``)."""
    return [
        {"name": name, "description": description, "endpoint": endpoint}
        for name, (description, endpoint) in TOOL_SPECS.items()
    ]
