"""Validated, atomic state-changing operations.

This module is the **only** sanctioned way to mutate the supply chain. Every
public method follows the same contract:

1. it validates the request against the *current database state* — never
   against what the caller claims that state is;
2. it refuses an infeasible action with :class:`ConflictError` (HTTP 409) and a
   stable ``reason`` code (``insufficient_stock``, ``route_unavailable``, ...);
3. it applies the change and its audit entry inside a single transaction, so a
   rejected action leaves no trace and an accepted one can never land without
   its audit record;
4. it returns the new resulting state.

The agent layer must call these methods (or the matching action endpoints)
rather than writing rows directly, so the validation below can never be
bypassed from the caller side.

It also owns the *disruption triggers* (``/simulate/*``) used to break the
seeded scenario for demos; those follow the same contract and record a single
``disruption_injected`` audit entry each.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy.orm import Session

from app.locations import LocationKind, in_range, kind_of
from app.models import (
    TERMINAL_STATUSES,
    Actor,
    Dealer,
    Product,
    Shipment,
    ShipmentStatus,
    Warehouse,
)
from app.schemas.actions import (
    InventoryTransferRequest,
    InventoryTransferResponse,
    ShipmentCancelResponse,
    ShipmentRerouteRequest,
    ShipmentRerouteResponse,
    VendorPurchaseRequest,
    VendorPurchaseResponse,
)
from app.schemas.dealer import DealerRead
from app.schemas.inventory import DealerStock, LocationInventory, WarehouseStock
from app.schemas.route import RouteRead
from app.schemas.shipment import ShipmentRead
from app.schemas.simulate import (
    DemandSpikeRequest,
    DemandSpikeResponse,
    RouteBlockRequest,
    RouteBlockResponse,
    ShipmentDelayRequest,
    ShipmentDelayResponse,
    VendorFailureRequest,
    VendorFailureResponse,
)
from app.schemas.vendor import VendorRead
from app.services.audit_log_service import stage
from app.services.dealer_service import DealerService
from app.services.demand_service import DemandService
from app.services.errors import ConflictError
from app.services.product_service import ProductService
from app.services.route_service import RouteService
from app.services.shipment_service import ShipmentService
from app.services.supplier_service import SupplierService
from app.services.warehouse_service import WarehouseService
from app.utils import hours_from_now

#: A location that can hold stock.
StockLocation = Warehouse | Dealer


class ActionService:
    """State-changing operations, each validated and applied atomically."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.products = ProductService(db)
        self.suppliers = SupplierService(db)
        self.warehouses = WarehouseService(db)
        self.dealers = DealerService(db)
        self.routes = RouteService(db)
        self.shipments = ShipmentService(db)
        self.demand = DemandService(db)

    # --- transaction helper ------------------------------------------------
    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Commit on success, roll back completely on any failure.

        Validation happens before the block is entered, so a rejected action
        never mutates anything; this only guarantees that the change *and* its
        audit entry commit together or not at all.
        """
        try:
            yield
        except Exception:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    # --- validation helpers ------------------------------------------------
    def _resolve_product(self, product_id: int | None) -> Product:
        """The requested product, or the only one when the id is omitted."""
        if product_id is not None:
            return self.products.get_or_404(product_id)
        products = list(self.products.list(limit=self.products.max_limit))
        if not products:
            raise ConflictError(
                "No products exist; create one or POST /admin/reset",
                reason="no_product",
            )
        if len(products) > 1:
            raise ConflictError(
                "product_id is required when the catalogue holds more than one "
                "product",
                reason="ambiguous_product",
            )
        return products[0]

    def _stock_location(
        self, location_id: int, *, role: str
    ) -> tuple[LocationKind, StockLocation]:
        """Resolve a location id that must be able to hold stock.

        In-range ids that simply do not exist are a 404; ids that exist but can
        never hold inventory (suppliers) or fall outside the namespace are a 409
        explaining why the action is infeasible.
        """
        kind = kind_of(location_id)
        if kind is LocationKind.WAREHOUSE:
            return kind, self.warehouses.get_or_404(location_id)
        if kind is LocationKind.DEALER:
            return kind, self.dealers.get_or_404(location_id)
        if kind is LocationKind.SUPPLIER:
            raise ConflictError(
                f"{role} {location_id} is a supplier, which holds no inventory",
                reason="not_a_stock_location",
            )
        raise ConflictError(
            f"{role} {location_id} is outside the location id namespace "
            "(suppliers 1-99, warehouses 101-199, dealers 201-299)",
            reason="not_a_stock_location",
        )

    @staticmethod
    def _inventory_model(location: StockLocation) -> LocationInventory:
        """Snapshot one stock-holding location as its read model."""
        if isinstance(location, Warehouse):
            return WarehouseStock.from_warehouse(location)
        return DealerStock.from_dealer(location)

    # --- POST /inventory/transfer -----------------------------------------
    def transfer_inventory(
        self,
        payload: InventoryTransferRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> InventoryTransferResponse:
        """Move stock from a warehouse to another stock-holding location."""
        product = self._resolve_product(payload.product_id)

        if payload.from_warehouse_id == payload.to_id:
            raise ConflictError(
                "Source and destination are the same location",
                reason="same_location",
            )
        if not in_range(payload.from_warehouse_id, LocationKind.WAREHOUSE):
            raise ConflictError(
                f"from_warehouse_id {payload.from_warehouse_id} is not a warehouse "
                "(warehouses are 101-199)",
                reason="invalid_source_location",
            )

        source = self.warehouses.get_or_404(payload.from_warehouse_id)
        destination_kind, destination = self._stock_location(
            payload.to_id, role="Destination"
        )

        source_before = source.quantity_of(product.id)
        if source_before < payload.quantity:
            raise ConflictError(
                f"Warehouse {source.id} holds {source_before} of product "
                f"{product.id}; cannot transfer {payload.quantity}",
                reason="insufficient_stock",
            )
        destination_before = self._quantity_at(destination, product.id)

        with self._transaction():
            source_snapshot = WarehouseStock.from_warehouse(source)
            destination_snapshot = self._inventory_model(destination)

            source.set_quantity(product.id, source_before - payload.quantity)
            self._set_quantity(
                destination, product.id, destination_before + payload.quantity
            )

            entry = stage(
                self.db,
                actor=actor,
                action_type="inventory_transfer",
                details={
                    "product_id": product.id,
                    "quantity": payload.quantity,
                    "from": {
                        "location_id": source.id,
                        "location_type": LocationKind.WAREHOUSE.value,
                        "before": source_before,
                        "after": source_before - payload.quantity,
                    },
                    "to": {
                        "location_id": destination.id,
                        "location_type": destination_kind.value,
                        "before": destination_before,
                        "after": destination_before + payload.quantity,
                    },
                },
                result="success",
            )
            self.db.flush()

            return InventoryTransferResponse(
                product_id=product.id,
                quantity=payload.quantity,
                source_before=source_snapshot,
                source_after=WarehouseStock.from_warehouse(source),
                destination_before=destination_snapshot,
                destination_after=self._inventory_model(destination),
                audit_log_id=entry.id,
            )

    @staticmethod
    def _quantity_at(location: StockLocation, product_id: int) -> int:
        """Stock of one product at a location (a dealer's single number)."""
        if isinstance(location, Warehouse):
            return location.quantity_of(product_id)
        return location.current_inventory

    @staticmethod
    def _set_quantity(
        location: StockLocation, product_id: int, quantity: int
    ) -> None:
        """Overwrite one product's stock at a location."""
        if isinstance(location, Warehouse):
            location.set_quantity(product_id, quantity)
        else:
            location.current_inventory = quantity

    # --- POST /shipment/{id}/reroute --------------------------------------
    def reroute_shipment(
        self,
        shipment_id: int,
        payload: ShipmentRerouteRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> ShipmentRerouteResponse:
        """Send an in-flight shipment along a different (available) route.

        The route defines the new path: the shipment's origin becomes the
        route's origin and its ETA is recomputed from the route's travel time.
        The destination must not change, so a reroute can never quietly divert
        goods away from the location that is expecting them.
        """
        shipment = self.shipments.get_or_404(shipment_id)
        if shipment.status in TERMINAL_STATUSES:
            raise ConflictError(
                f"Shipment {shipment.id} is {shipment.status.value} and can no "
                "longer be rerouted",
                reason="shipment_not_reroutable",
            )

        route = self.routes.get_or_404(payload.new_route_id)
        if not route.is_available:
            raise ConflictError(
                f"Route {route.id} is not available", reason="route_unavailable"
            )
        if route.to_location_id != shipment.to_id:
            raise ConflictError(
                f"Route {route.id} ends at location {route.to_location_id}, but "
                f"shipment {shipment.id} is destined for {shipment.to_id}",
                reason="route_destination_mismatch",
            )

        with self._transaction():
            previous_from_id = shipment.from_id
            previous_to_id = shipment.to_id
            previous_expected_arrival = shipment.expected_arrival

            new_expected_arrival = hours_from_now(route.travel_time_hours)
            shipment.from_id = route.from_location_id
            shipment.expected_arrival = new_expected_arrival

            entry = stage(
                self.db,
                actor=actor,
                action_type="shipment_reroute",
                details={
                    "shipment_id": shipment.id,
                    "route_id": route.id,
                    "before": {
                        "from_id": previous_from_id,
                        "to_id": previous_to_id,
                        "expected_arrival": (
                            previous_expected_arrival.isoformat()
                            if previous_expected_arrival
                            else None
                        ),
                    },
                    "after": {
                        "from_id": route.from_location_id,
                        "to_id": route.to_location_id,
                        "expected_arrival": new_expected_arrival.isoformat(),
                    },
                },
                result="success",
            )
            self.db.flush()

            return ShipmentRerouteResponse(
                shipment=ShipmentRead.model_validate(shipment),
                route=RouteRead.model_validate(route),
                previous_from_id=previous_from_id,
                previous_to_id=previous_to_id,
                previous_expected_arrival=previous_expected_arrival,
                audit_log_id=entry.id,
            )

    # --- POST /vendor/{id}/purchase ---------------------------------------
    def purchase_from_vendor(
        self,
        vendor_id: int,
        payload: VendorPurchaseRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> VendorPurchaseResponse:
        """Buy stock from a supplier, reserving it and creating the shipment.

        The vendor's remaining availability is decremented so the same stock
        cannot be sold twice, and the new shipment is scheduled to arrive after
        the vendor's delivery time.
        """
        supplier = self.suppliers.get_or_404(vendor_id)
        if not supplier.is_available:
            raise ConflictError(
                f"Vendor {supplier.id} ({supplier.name}) is not available",
                reason="vendor_unavailable",
            )
        if supplier.available_quantity < payload.quantity:
            raise ConflictError(
                f"Vendor {supplier.id} has {supplier.available_quantity} available; "
                f"cannot purchase {payload.quantity}",
                reason="insufficient_supplier_stock",
            )

        product = self.products.get_or_404(supplier.product_id)
        destination = self.demand.dealer_or_default(None)

        with self._transaction():
            available_before = supplier.available_quantity
            supplier.available_quantity = available_before - payload.quantity

            expected_arrival = hours_from_now(supplier.delivery_hours)
            shipment = Shipment(
                product_id=product.id,
                from_id=supplier.id,
                to_id=destination.id,
                quantity=payload.quantity,
                status=ShipmentStatus.PENDING,
                expected_arrival=expected_arrival,
                actual_arrival=None,
                delay_hours=0.0,
            )
            self.db.add(shipment)
            self.db.flush()

            entry = stage(
                self.db,
                actor=actor,
                action_type="vendor_purchase",
                details={
                    "vendor_id": supplier.id,
                    "product_id": product.id,
                    "quantity": payload.quantity,
                    "unit_price": supplier.price_per_unit,
                    "total_price": round(supplier.price_per_unit * payload.quantity, 2),
                    "vendor_available": {
                        "before": available_before,
                        "after": supplier.available_quantity,
                    },
                    "shipment": {
                        "id": shipment.id,
                        "from_id": shipment.from_id,
                        "to_id": shipment.to_id,
                        "expected_arrival": expected_arrival.isoformat(),
                    },
                },
                result="success",
            )
            self.db.flush()

            return VendorPurchaseResponse(
                vendor=VendorRead.from_supplier(supplier, product),
                vendor_available_before=available_before,
                shipment=ShipmentRead.model_validate(shipment),
                audit_log_id=entry.id,
            )

    # --- POST /shipment/{id}/cancel ---------------------------------------
    def cancel_shipment(
        self,
        shipment_id: int,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> ShipmentCancelResponse:
        """Cancel a shipment that has not yet landed.

        Cancelling only changes the shipment's status; reserved supplier stock
        is *not* automatically returned (the audit entry records what was
        cancelled so that can be decided separately).
        """
        shipment = self.shipments.get_or_404(shipment_id)
        if shipment.status is ShipmentStatus.ARRIVED:
            raise ConflictError(
                f"Shipment {shipment.id} has already arrived and cannot be "
                "cancelled",
                reason="shipment_already_arrived",
            )
        if shipment.status is ShipmentStatus.CANCELLED:
            raise ConflictError(
                f"Shipment {shipment.id} is already cancelled",
                reason="shipment_already_cancelled",
            )

        with self._transaction():
            previous_status = shipment.status
            shipment.status = ShipmentStatus.CANCELLED

            entry = stage(
                self.db,
                actor=actor,
                action_type="shipment_cancel",
                details={
                    "shipment_id": shipment.id,
                    "product_id": shipment.product_id,
                    "quantity": shipment.quantity,
                    "from_id": shipment.from_id,
                    "to_id": shipment.to_id,
                    "status": {
                        "before": previous_status.value,
                        "after": ShipmentStatus.CANCELLED.value,
                    },
                },
                result="success",
            )
            self.db.flush()

            return ShipmentCancelResponse(
                shipment=ShipmentRead.model_validate(shipment),
                previous_status=previous_status,
                audit_log_id=entry.id,
            )

    # --- POST /simulate/* (disruption triggers) ---------------------------
    def inject_shipment_delay(
        self,
        payload: ShipmentDelayRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> ShipmentDelayResponse:
        """Delay a shipment, pushing its expected arrival further out.

        The delay compounds: calling this again adds to the running
        ``delay_hours`` and pushes the ETA from where it already was, so a demo
        can stack disruptions. A shipment that already landed (``ARRIVED``) or
        was cancelled cannot be delayed.
        """
        shipment = self.shipments.get_or_404(payload.shipment_id)
        if shipment.status in TERMINAL_STATUSES:
            raise ConflictError(
                f"Shipment {shipment.id} is {shipment.status.value}; a disruption "
                "cannot be applied to a shipment that has already ended",
                reason="shipment_not_delayable",
            )

        with self._transaction():
            previous_status = shipment.status
            previous_expected_arrival = shipment.expected_arrival

            shipment.status = ShipmentStatus.DELAYED
            shipment.delay_hours = round(shipment.delay_hours + payload.delay_hours, 2)
            if previous_expected_arrival is None:
                shipment.expected_arrival = hours_from_now(payload.delay_hours)
            else:
                shipment.expected_arrival = previous_expected_arrival + timedelta(
                    hours=payload.delay_hours
                )

            entry = stage(
                self.db,
                actor=actor,
                action_type="disruption_injected",
                details={
                    "disruption": "shipment_delay",
                    "shipment_id": shipment.id,
                    "delay_hours": payload.delay_hours,
                    "status": {
                        "before": previous_status.value,
                        "after": shipment.status.value,
                    },
                    "expected_arrival": {
                        "before": (
                            previous_expected_arrival.isoformat()
                            if previous_expected_arrival
                            else None
                        ),
                        "after": shipment.expected_arrival.isoformat(),
                    },
                    "total_delay_hours": shipment.delay_hours,
                },
                result="success",
            )
            self.db.flush()

            return ShipmentDelayResponse(
                shipment=ShipmentRead.model_validate(shipment),
                delay_hours=payload.delay_hours,
                previous_status=previous_status,
                previous_expected_arrival=previous_expected_arrival,
                audit_log_id=entry.id,
            )

    def inject_vendor_failure(
        self,
        payload: VendorFailureRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> VendorFailureResponse:
        """Take a supplier out of service by flagging it unavailable."""
        supplier = self.suppliers.get_or_404(payload.vendor_id)
        if not supplier.is_available:
            raise ConflictError(
                f"Vendor {supplier.id} ({supplier.name}) is already unavailable",
                reason="vendor_already_unavailable",
            )
        product = self.products.get(supplier.product_id)

        with self._transaction():
            supplier.is_available = False

            entry = stage(
                self.db,
                actor=actor,
                action_type="disruption_injected",
                details={
                    "disruption": "vendor_failure",
                    "vendor_id": supplier.id,
                    "vendor_name": supplier.name,
                    "is_available": {"before": True, "after": False},
                },
                result="success",
            )
            self.db.flush()

            return VendorFailureResponse(
                vendor=VendorRead.from_supplier(supplier, product),
                previous_is_available=True,
                audit_log_id=entry.id,
            )

    def inject_route_block(
        self,
        payload: RouteBlockRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> RouteBlockResponse:
        """Block a route by flagging it unavailable."""
        route = self.routes.get_or_404(payload.route_id)
        if not route.is_available:
            raise ConflictError(
                f"Route {route.id} is already blocked",
                reason="route_already_unavailable",
            )

        with self._transaction():
            route.is_available = False

            entry = stage(
                self.db,
                actor=actor,
                action_type="disruption_injected",
                details={
                    "disruption": "route_block",
                    "route_id": route.id,
                    "from_location_id": route.from_location_id,
                    "to_location_id": route.to_location_id,
                    "is_available": {"before": True, "after": False},
                },
                result="success",
            )
            self.db.flush()

            return RouteBlockResponse(
                route=RouteRead.model_validate(route),
                previous_is_available=True,
                audit_log_id=entry.id,
            )

    def inject_demand_spike(
        self,
        payload: DemandSpikeRequest,
        *,
        actor: Actor | str = Actor.SYSTEM,
    ) -> DemandSpikeResponse:
        """Raise a dealer's requirement, widening the gap it has to close."""
        dealer = self.dealers.get_or_404(payload.dealer_id)
        if payload.new_required_quantity <= dealer.required_quantity:
            raise ConflictError(
                f"Dealer {dealer.id} already requires {dealer.required_quantity}; "
                "a demand spike must raise it above that",
                reason="not_a_demand_spike",
            )

        with self._transaction():
            previous_required_quantity = dealer.required_quantity
            shortage_before = dealer.shortfall
            dealer.required_quantity = payload.new_required_quantity

            entry = stage(
                self.db,
                actor=actor,
                action_type="disruption_injected",
                details={
                    "disruption": "demand_spike",
                    "dealer_id": dealer.id,
                    "required_quantity": {
                        "before": previous_required_quantity,
                        "after": dealer.required_quantity,
                    },
                    "shortage": {"before": shortage_before, "after": dealer.shortfall},
                },
                result="success",
            )
            self.db.flush()

            return DemandSpikeResponse(
                dealer=DealerRead.model_validate(dealer),
                previous_required_quantity=previous_required_quantity,
                shortage_before=shortage_before,
                shortage_after=dealer.shortfall,
                audit_log_id=entry.id,
            )
