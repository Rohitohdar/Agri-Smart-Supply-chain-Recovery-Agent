"""Service backing ``GET /debug/would-choose``.

Reads the current demand, runs the optimizer, and builds a disruption target
that points at the exact entity the top-ranked option depends on.  The caller
can then disable that entity before running the agent so the recorded demo
shows a clear before-vs-after change in the chosen action.
"""

from sqlalchemy.orm import Session

from app.optimizer import RecoveryAction
from app.schemas.debug import (
    DisruptionTarget,
    RouteDisruptionTarget,
    ShipmentDisruptionTarget,
    VendorDisruptionTarget,
    WouldChooseResponse,
)
from app.schemas.demand import DemandResponse
from app.schemas.optimize import RankedOptionRead
from app.services.demand_service import DemandService
from app.services.optimizer_service import OptimizerService
from app.services.supplier_service import SupplierService


class WouldChooseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.demand = DemandService(db)
        self.optimizer = OptimizerService(db)
        self.suppliers = SupplierService(db)

    def would_choose(self) -> WouldChooseResponse:
        dealer = self.demand.dealer_or_default(None)
        active = self.demand.active_shipments(dealer.id)
        demand = DemandResponse.from_dealer(dealer, list(active))

        plan = self.optimizer.plan(
            shortage_quantity=demand.shortage,
            deadline=demand.deadline,
        )

        options = list(plan.options)
        top_option = RankedOptionRead.from_option(options[0]) if options else None
        target = self._disruption_target(top_option) if top_option else None

        return WouldChooseResponse(
            shortage_quantity=plan.shortage_quantity,
            deadline=demand.deadline.isoformat(),
            hours_available=plan.hours_available,
            top_option=top_option,
            feasible_count=len(options),
            disruption_target=target,
            demo_instruction=self._instruction(top_option, target),
        )

    # --- helpers -----------------------------------------------------------

    def _disruption_target(
        self, option: RankedOptionRead
    ) -> DisruptionTarget | None:
        if option.action == RecoveryAction.VENDOR_PURCHASE:
            # Look up the vendor name from the supplier record.
            supplier = self.suppliers.get_or_404(option.reference_id)
            return VendorDisruptionTarget(
                vendor_id=option.reference_id,
                vendor_name=supplier.name,
                payload={"vendor_id": option.reference_id},
            )

        if option.action == RecoveryAction.WAREHOUSE_TRANSFER:
            # The route the transfer depends on is stored on the option.
            if option.route_id is None:
                return None
            return RouteDisruptionTarget(
                route_id=option.route_id,
                payload={"route_id": option.route_id},
            )

        if option.action == RecoveryAction.REROUTE_SHIPMENT:
            return ShipmentDisruptionTarget(
                shipment_id=option.reference_id,
                payload={"shipment_id": option.reference_id, "delay_hours": 72},
            )

        return None

    @staticmethod
    def _instruction(
        option: RankedOptionRead | None,
        target: DisruptionTarget | None,
    ) -> str:
        if option is None:
            return (
                "No feasible option exists right now — the agent would already "
                "refuse to act. Reset the scenario before recording."
            )
        if target is None:
            return (
                f"Top option is {option.action} (ref {option.reference_id}) but "
                "no disruption target could be identified. Check the scenario state."
            )

        if target.kind == "vendor_failure":
            return (
                f"POST {target.endpoint} with {target.payload} to disable "
                f"{target.vendor_name} (vendor {target.vendor_id}). "
                "The agent will then be forced to choose a different vendor or action."
            )
        if target.kind == "route_block":
            return (
                f"POST {target.endpoint} with {target.payload} to block "
                f"route {target.route_id}. "
                "The agent will then be unable to use the warehouse transfer "
                "and will fall back to a vendor purchase or reroute."
            )
        if target.kind == "shipment_delay":
            return (
                f"POST {target.endpoint} with {target.payload} to delay "
                f"shipment {target.shipment_id} past the deadline. "
                "The agent will then reroute or purchase instead."
            )
        return "Apply the disruption shown in disruption_target before recording."
