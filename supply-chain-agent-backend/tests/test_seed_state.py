"""The seed must always produce the exact documented starting state."""

from datetime import datetime

from app.utils import utcnow


def test_reset_reports_the_seeded_counts(seeded_client):
    body = seeded_client.post("/admin/reset").json()
    assert body["status"] == "reset"
    assert body["counts"] == {
        "products": 1,
        "suppliers": 3,
        "warehouses": 3,
        "dealers": 1,
        "routes": 4,
        "shipments": 1,
        "audit_logs": 1,
    }
    assert body["audit_log_id"] > 0


def test_state_counts_match_the_seeded_state(seeded_client):
    state = seeded_client.get("/admin/state").json()
    assert state["counts"] == {
        "products": 1,
        "suppliers": 3,
        "warehouses": 3,
        "dealers": 1,
        "routes": 4,
        "shipments": 1,
        "audit_logs": 1,
    }


def test_single_product_is_urea_measured_in_bags(seeded_client):
    products = seeded_client.get("/products").json()
    assert len(products) == 1
    assert products[0]["name"] == "Urea"
    assert products[0]["unit"] == "bag"


def test_three_suppliers_with_distinct_profiles(seeded_client):
    suppliers = seeded_client.get("/suppliers").json()
    assert len(suppliers) == 3
    assert len({s["price_per_unit"] for s in suppliers}) == 3
    assert len({s["delivery_hours"] for s in suppliers}) == 3
    assert len({s["carbon_per_unit"] for s in suppliers}) == 3
    assert all(s["is_available"] is True for s in suppliers)
    assert all(s["product_id"] == 1 for s in suppliers)

    # The cheapest option is deliberately the slowest and dirtiest.
    cheapest = min(suppliers, key=lambda s: s["price_per_unit"])
    greenest = min(suppliers, key=lambda s: s["carbon_per_unit"])
    assert cheapest["delivery_hours"] > greenest["delivery_hours"]
    assert cheapest["carbon_per_unit"] > greenest["carbon_per_unit"]


def test_three_warehouses_with_different_inventory_levels(seeded_client):
    warehouses = seeded_client.get("/warehouses").json()
    assert len(warehouses) == 3
    assert [w["id"] for w in warehouses] == [101, 102, 103]

    levels = [w["inventory"]["1"] for w in warehouses]
    assert len(set(levels)) == 3, "warehouses should start with different stock"
    assert levels == [450, 120, 600]
    assert all(w["location"] for w in warehouses)


def test_dealer_needs_a_thousand_bags_and_holds_three_hundred(seeded_client):
    dealers = seeded_client.get("/dealers").json()
    assert len(dealers) == 1
    dealer = dealers[0]
    assert dealer["id"] == 201
    assert dealer["required_quantity"] == 1000
    assert dealer["current_inventory"] == 300
    assert dealer["shortfall"] == 700
    assert datetime.fromisoformat(dealer["deadline"]) > utcnow()


def test_one_pending_shipment_of_700_bags_lands_before_the_deadline(seeded_client):
    shipments = seeded_client.get("/shipments").json()
    assert len(shipments) == 1
    shipment = shipments[0]
    assert shipment["quantity"] == 700
    assert shipment["status"] == "PENDING"
    assert shipment["actual_arrival"] is None
    assert shipment["delay_hours"] == 0
    assert shipment["to_id"] == 201

    dealer = seeded_client.get("/dealers/201").json()
    assert datetime.fromisoformat(shipment["expected_arrival"]) < datetime.fromisoformat(
        dealer["deadline"]
    )


def test_routes_connect_supply_to_the_dealer_and_are_all_available(seeded_client):
    routes = seeded_client.get("/routes").json()
    assert len(routes) == 4
    assert all(route["is_available"] is True for route in routes)
    assert all(route["to_location_id"] == 201 for route in routes)
    assert all(route["distance_km"] > 0 for route in routes)
    assert all(route["travel_time_hours"] > 0 for route in routes)
    # Three warehouses plus one supplier feed the dealer.
    sources = {route["from_location_id"] for route in routes}
    assert sources == {101, 102, 103, 2}


def test_reset_is_repeatable_and_restores_mutated_state(seeded_client):
    seeded_client.patch("/shipments/1", json={"status": "DELAYED", "delay_hours": 5})
    seeded_client.patch("/dealers/201", json={"current_inventory": 999})
    seeded_client.delete("/routes/1")

    seeded_client.post("/admin/reset")

    shipment = seeded_client.get("/shipments/1").json()
    dealer = seeded_client.get("/dealers/201").json()
    assert shipment["status"] == "PENDING"
    assert shipment["delay_hours"] == 0
    assert dealer["current_inventory"] == 300
    assert len(seeded_client.get("/routes").json()) == 4


def test_follow_up_resets_produce_identical_counts_and_inventory(seeded_client):
    first = seeded_client.get("/admin/state").json()
    seeded_client.patch("/warehouses/101/inventory/1", json={"quantity": 7})
    seeded_client.post("/admin/reset")
    second = seeded_client.get("/admin/state").json()
    assert first["counts"] == second["counts"]
    assert first["warehouse_inventory"] == second["warehouse_inventory"]


def test_reset_writes_a_system_audit_entry(seeded_client):
    logs = seeded_client.get("/audit-logs").json()
    assert len(logs) == 1
    entry = logs[0]
    assert entry["actor"] == "system"
    assert entry["action_type"] == "database_reset"
    assert entry["result"] == "success"
    assert entry["details"]["dealer_shortfall"] == 700
    assert entry["details"]["location_namespace"]["dealers"] == [201]
