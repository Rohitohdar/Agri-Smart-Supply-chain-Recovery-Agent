"""Seed script — the single source of truth for the starting state.

Running this module directly (``python -m app.db.seed``) drops every table,
recreates the schema and loads the scenario below. ``POST /admin/reset`` calls
the exact same function, so the API and the CLI can never drift apart.

Starting state
--------------
* 1 product: ``Urea`` (unit ``bag``)
* 3 suppliers with different price / delivery speed / carbon profiles
* 3 warehouses with different starting inventory levels
* 1 dealer needing 1,000 bags before a deadline, holding 300
* 1 pending shipment of 700 bags landing before that deadline
* 4 available routes from warehouses/suppliers to the dealer

Location ids follow the shared namespace documented in ``app.models.route``:
suppliers use 1-99, warehouses 101-199, dealers 201-299. That keeps every
``from_id`` / ``to_id`` / ``from_location_id`` / ``to_location_id`` unambiguous.
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.base import create_all, drop_all
from app.models import (
    Actor,
    Dealer,
    Product,
    Route,
    Shipment,
    ShipmentStatus,
    Supplier,
    Warehouse,
)
from app.services.audit_log_service import record
from app.utils import hours_from_now, utcnow

# --- Location id namespace -------------------------------------------------
SUPPLIER_IDS = (1, 2, 3)
WAREHOUSE_IDS = (101, 102, 103)
DEALER_ID = 201

# --- Timing horizons (relative so the scenario is always "live") -----------
DEALER_DEADLINE_HOURS = 72.0  # deadline = seed time + 72h
SHIPMENT_ETA_HOURS = 24.0  # inbound shipment lands well before the deadline

# --- Product ---------------------------------------------------------------
PRODUCT: Dict[str, Any] = {"id": 1, "name": "Urea", "unit": "bag"}

# --- Suppliers: cheap-but-slow, fast-but-pricier, greenest-and-fastest -----
# Prices reflect approximate real-world subsidized/retail urea pricing in India
# (₹350–₹450 per 45 kg bag as of 2024–25). All other figures (delivery times,
# carbon, capacities) remain illustrative/simulated.
SUPPLIERS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "AgroChem Industries",
        "product_id": 1,
        "price_per_unit": 410.00,  # mid-high price, slowest and dirtiest
        "available_quantity": 800,
        "delivery_hours": 30.0,
        "carbon_per_unit": 6.5,
        "is_available": True,
    },
    {
        "id": 2,
        "name": "GreenFields Fertilizers",
        "product_id": 1,
        "price_per_unit": 380.00,  # mid price, fastest, lowest carbon
        "available_quantity": 500,
        "delivery_hours": 8.0,
        "carbon_per_unit": 2.8,
        "is_available": True,
    },
    {
        "id": 3,
        "name": "Bharat Urea Traders",
        "product_id": 1,
        "price_per_unit": 365.00,  # cheapest, large stock and quick
        "available_quantity": 1200,
        "delivery_hours": 12.0,
        "carbon_per_unit": 4.2,
        "is_available": True,
    },
]

# --- Warehouses: three very different stock levels -------------------------
WAREHOUSES: List[Dict[str, Any]] = [
    {"id": 101, "name": "Central Depot", "location": "Nagpur", "inventory": {"1": 450}},
    {"id": 102, "name": "North Hub", "location": "Ludhiana", "inventory": {"1": 120}},
    {"id": 103, "name": "East Yard", "location": "Kolkata", "inventory": {"1": 600}},
]

# --- Dealer: 1,000 bags required, 300 already on hand ----------------------
DEALER: Dict[str, Any] = {
    "id": DEALER_ID,
    "name": "Krishi Seva Kendra",
    "location": "Indore",
    "required_quantity": 1000,
    "current_inventory": 300,
}

# --- Pending inbound shipment: covers the 700 bag shortfall ----------------
SHIPMENT: Dict[str, Any] = {
    "id": 1,
    "product_id": 1,
    "from_id": 101,  # Central Depot
    "to_id": DEALER_ID,  # dealer
    "quantity": 700,
    "status": ShipmentStatus.PENDING,
}

# --- Routes into the dealer, all initially available -----------------------
ROUTES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "from_location_id": 101,  # Central Depot -> dealer
        "to_location_id": DEALER_ID,
        "distance_km": 480.0,
        "travel_time_hours": 9.5,
        "carbon_per_km": 0.12,
        "is_available": True,
    },
    {
        "id": 2,
        "from_location_id": 102,  # North Hub -> dealer
        "to_location_id": DEALER_ID,
        "distance_km": 1150.0,
        "travel_time_hours": 22.0,
        "carbon_per_km": 0.14,
        "is_available": True,
    },
    {
        "id": 3,
        "from_location_id": 103,  # East Yard -> dealer
        "to_location_id": DEALER_ID,
        "distance_km": 1450.0,
        "travel_time_hours": 27.0,
        "carbon_per_km": 0.16,
        "is_available": True,
    },
    {
        "id": 4,
        "from_location_id": 2,  # GreenFields (supplier) -> dealer
        "to_location_id": DEALER_ID,
        "distance_km": 620.0,
        "travel_time_hours": 11.0,
        "carbon_per_km": 0.10,
        "is_available": True,
    },
]


def seed_database(db: Session, *, reset: bool = True) -> Dict[str, int]:
    """Load the starting state and return a count per table.

    With ``reset=True`` (the default) the schema is dropped and recreated first,
    so the result is byte-for-byte the same starting state every time.
    """
    if reset:
        db.rollback()
        engine = db.get_bind()
        drop_all(engine)
        create_all(engine)

    created_at = utcnow()
    dealer_deadline = hours_from_now(DEALER_DEADLINE_HOURS)
    shipment_eta = hours_from_now(SHIPMENT_ETA_HOURS)

    db.add(Product(**PRODUCT))
    db.add_all(Supplier(**row) for row in SUPPLIERS)
    db.add_all(Warehouse(**row) for row in WAREHOUSES)
    db.add(
        Dealer(**DEALER, deadline=dealer_deadline),
    )
    db.add_all(Route(**row) for row in ROUTES)
    db.add(
        Shipment(
            **SHIPMENT,
            expected_arrival=shipment_eta,
            actual_arrival=None,
            delay_hours=0.0,
        )
    )
    db.flush()

    # One audit entry so the trail shows where the current state came from.
    record(
        db,
        actor=Actor.SYSTEM,
        action_type="database_reset",
        details={
            "seeded_at": created_at.isoformat(),
            "dealer_deadline": dealer_deadline.isoformat(),
            "shipment_expected_arrival": shipment_eta.isoformat(),
            "dealer_shortfall": DEALER["required_quantity"] - DEALER["current_inventory"],
            "location_namespace": {
                "suppliers": list(SUPPLIER_IDS),
                "warehouses": list(WAREHOUSE_IDS),
                "dealers": [DEALER_ID],
            },
        },
        result="success",
    )
    db.commit()

    return {
        "products": 1,
        "suppliers": len(SUPPLIERS),
        "warehouses": len(WAREHOUSES),
        "dealers": 1,
        "routes": len(ROUTES),
        "shipments": 1,
        "audit_logs": 1,
    }


def reset_database() -> Dict[str, int]:
    """Convenience wrapper that opens its own session (used by the CLI)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return seed_database(db)
    finally:
        db.close()


def main() -> None:  # pragma: no cover - CLI entry point
    counts = reset_database()
    print("Database reset to the seeded starting state:")
    for table, count in counts.items():
        print(f"  {table:<12} {count}")


if __name__ == "__main__":  # pragma: no cover
    main()
