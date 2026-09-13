"""Bridge between the database and the pure optimizer.

This is the only place that touches the ORM; ``app.optimizer`` stays pure. The
service snapshots the current situation (what the dealer is short of, what
warehouses hold, which vendors can supply and which routes are open) into a
:class:`~app.optimizer.RecoveryState` and hands it to the optimizer.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Product
from app.optimizer import (
    RecoveryPlan,
    RecoveryState,
    RouteSupply,
    ShipmentSupply,
    SupplierSupply,
    WarehouseSupply,
    evaluate_recovery,
)
from app.services.dealer_service import DealerService
from app.services.demand_service import DemandService
from app.services.errors import ConflictError
from app.services.product_service import ProductService
from app.services.route_service import RouteService
from app.services.shipment_service import ShipmentService
from app.services.supplier_service import SupplierService
from app.services.warehouse_service import WarehouseService
from app.utils import utcnow


class OptimizerService:
    """Build recovery state from the current database and rank the options."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.products = ProductService(db)
        self.warehouses = WarehouseService(db)
        self.suppliers = SupplierService(db)
        self.routes = RouteService(db)
        self.shipments = ShipmentService(db)
        self.dealers = DealerService(db)
        self.demand = DemandService(db)

    def _product(self) -> Product:
        """The product shortage is measured in.

        Stock is tracked per product and the request names none, so the
        catalogue's first product is used (the seeded scenario has exactly one).
        """
        products = list(self.products.list(limit=self.products.max_limit))
        if not products:
            raise ConflictError(
                "No products exist; create one or POST /admin/reset",
                reason="no_product",
            )
        return products[0]

    def build_state(
        self,
        *,
        shortage_quantity: int,
        deadline: datetime,
        now: Optional[datetime] = None,
    ) -> RecoveryState:
        """Snapshot the current supply situation into an optimizer state."""
        dealer = self.demand.dealer_or_default(None)
        product = self._product()

        warehouses = tuple(
            WarehouseSupply(
                warehouse_id=warehouse.id,
                name=warehouse.name,
                available_quantity=warehouse.quantity_of(product.id),
            )
            for warehouse in sorted(
                self.warehouses.list(limit=self.warehouses.max_limit),
                key=lambda warehouse: warehouse.id,
            )
        )
        suppliers = tuple(
            SupplierSupply(
                supplier_id=supplier.id,
                name=supplier.name,
                available_quantity=supplier.available_quantity,
                price_per_unit=supplier.price_per_unit,
                delivery_hours=supplier.delivery_hours,
                carbon_per_unit=supplier.carbon_per_unit,
            )
            for supplier in sorted(
                self.suppliers.list_available(), key=lambda supplier: supplier.id
            )
        )
        routes = tuple(
            RouteSupply(
                route_id=route.id,
                from_location_id=route.from_location_id,
                to_location_id=route.to_location_id,
                distance_km=route.distance_km,
                travel_time_hours=route.travel_time_hours,
                carbon_per_km=route.carbon_per_km,
            )
            for route in sorted(self.routes.list_available(), key=lambda route: route.id)
        )

        # Snapshot active (non-terminal) shipments for reroute candidates.
        all_routes = list(self.routes.list(limit=self.routes.max_limit))

        def _best_route_for_shipment(
            from_id: int, to_id: int
        ) -> Optional[RouteSupply]:
            """Find the fastest available route matching a shipment's current path."""
            matching = [
                r
                for r in all_routes
                if r.from_location_id == from_id
                and r.to_location_id == to_id
                and r.is_available
            ]
            if not matching:
                return None
            best = min(
                matching,
                key=lambda r: (
                    r.travel_time_hours,
                    r.distance_km,
                    r.carbon_per_km,
                    r.id,
                ),
            )
            return RouteSupply(
                route_id=best.id,
                from_location_id=best.from_location_id,
                to_location_id=best.to_location_id,
                distance_km=best.distance_km,
                travel_time_hours=best.travel_time_hours,
                carbon_per_km=best.carbon_per_km,
            )

        active_shipments = self.shipments.inbound_to(dealer.id)
        shipments = tuple(
            ShipmentSupply(
                shipment_id=shipment.id,
                from_location_id=shipment.from_id,
                to_location_id=shipment.to_id,
                quantity=shipment.quantity,
                expected_arrival=shipment.expected_arrival,
                current_route_id=(
                    route.route_id
                    if (route := _best_route_for_shipment(shipment.from_id, shipment.to_id))
                    else None
                ),
            )
            for shipment in active_shipments
        )

        return RecoveryState(
            shortage_quantity=shortage_quantity,
            deadline=deadline,
            now=now or utcnow(),
            destination_location_id=dealer.id,
            warehouses=warehouses,
            suppliers=suppliers,
            routes=routes,
            shipments=shipments,
        )

    def plan(
        self,
        *,
        shortage_quantity: int,
        deadline: datetime,
        now: Optional[datetime] = None,
    ) -> RecoveryPlan:
        """Rank recovery options for the current database state."""
        state = self.build_state(
            shortage_quantity=shortage_quantity, deadline=deadline, now=now
        )
        return evaluate_recovery(state)
