"""CRUD, validation and error-handling behaviour of the API."""


def test_health_endpoint(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"]


def test_missing_entity_returns_404_with_context(seeded_client):
    response = seeded_client.get("/products/999")
    assert response.status_code == 404
    assert response.json()["entity"] == "Product"
    assert response.json()["id"] == 999


def test_invalid_payload_returns_422(seeded_client):
    response = seeded_client.post("/products", json={"name": "DAP"})
    assert response.status_code == 422


def test_negative_quantity_is_rejected(seeded_client):
    response = seeded_client.patch("/suppliers/1", json={"available_quantity": -5})
    assert response.status_code == 422


def test_duplicate_product_name_returns_409(seeded_client):
    response = seeded_client.post("/products", json={"name": "Urea", "unit": "bag"})
    assert response.status_code == 409


def test_product_lifecycle(seeded_client):
    created = seeded_client.post("/products", json={"name": "DAP", "unit": "bag"})
    assert created.status_code == 201
    product_id = created.json()["id"]

    updated = seeded_client.patch(f"/products/{product_id}", json={"unit": "tonne"})
    assert updated.json()["unit"] == "tonne"

    assert seeded_client.delete(f"/products/{product_id}").status_code == 204
    assert seeded_client.get(f"/products/{product_id}").status_code == 404


def test_warehouse_inventory_read_and_write(seeded_client):
    current = seeded_client.get("/warehouses/101/inventory/1").json()
    assert current == {"warehouse_id": 101, "product_id": 1, "quantity": 450}

    updated = seeded_client.put("/warehouses/101/inventory/1", json={"quantity": 275})
    assert updated.status_code == 200
    assert updated.json()["inventory"]["1"] == 275

    # Unknown products report zero rather than erroring.
    assert seeded_client.get("/warehouses/101/inventory/42").json()["quantity"] == 0


def test_supplier_and_route_filters(seeded_client):
    available = seeded_client.get("/suppliers", params={"only_available": "true"}).json()
    assert len(available) == 3
    assert available == sorted(available, key=lambda s: s["price_per_unit"])

    routes = seeded_client.get("/routes", params={"only_available": "true"}).json()
    assert len(routes) == 4
    assert routes == sorted(routes, key=lambda r: r["travel_time_hours"])


def test_shipment_status_transition_records_delay(seeded_client):
    arrived = seeded_client.patch(
        "/shipments/1/status", json={"status": "ARRIVED"}
    ).json()
    assert arrived["status"] == "ARRIVED"
    assert arrived["actual_arrival"] is not None
    assert arrived["delay_hours"] >= 0

    delayed = seeded_client.patch(
        "/shipments/1/status", json={"status": "DELAYED", "delay_hours": 6}
    ).json()
    assert delayed["status"] == "DELAYED"
    assert delayed["delay_hours"] == 6

    inbound = seeded_client.get("/shipments", params={"to_id": 201}).json()
    assert len(inbound) == 1


def test_shipment_listing_by_status(seeded_client):
    pending = seeded_client.get("/shipments", params={"status": "PENDING"}).json()
    assert len(pending) == 1
    settled = seeded_client.get("/shipments", params={"status": "ARRIVED"}).json()
    assert settled == []


def test_agent_audit_entries_can_be_appended(seeded_client):
    created = seeded_client.post(
        "/audit-logs",
        json={
            "actor": "agent",
            "action_type": "evaluate_suppliers",
            "details": {"product_id": 1},
            "result": "3 suppliers ranked",
        },
    )
    assert created.status_code == 201

    agent_logs = seeded_client.get("/audit-logs", params={"actor": "agent"}).json()
    assert len(agent_logs) == 1
    assert agent_logs[0]["action_type"] == "evaluate_suppliers"

    recent = seeded_client.get("/audit-logs/recent", params={"limit": 5}).json()
    assert len(recent) == 2


def test_create_warehouse_normalises_inventory_keys(seeded_client):
    created = seeded_client.post(
        "/warehouses",
        json={"name": "South Shed", "location": "Chennai", "inventory": {"1": 25}},
    )
    assert created.status_code == 201
    warehouse = created.json()
    assert warehouse["inventory"] == {"1": 25}
    assert seeded_client.get(
        f"/warehouses/{warehouse['id']}/inventory/1"
    ).json()["quantity"] == 25

    bad = seeded_client.post(
        "/warehouses", json={"name": "X", "location": "Y", "inventory": {"1": -3}}
    )
    assert bad.status_code == 422


def test_created_supplier_drops_out_of_the_available_filter(seeded_client):
    created = seeded_client.post(
        "/suppliers",
        json={
            "name": "Late Arrivals Ltd",
            "product_id": 1,
            "price_per_unit": 20.0,
            "available_quantity": 100,
            "delivery_hours": 90,
            "carbon_per_unit": 9.0,
        },
    )
    assert created.status_code == 201
    supplier_id = created.json()["id"]

    seeded_client.patch(f"/suppliers/{supplier_id}", json={"is_available": False})
    available = seeded_client.get("/suppliers", params={"only_available": "true"}).json()
    assert len(available) == 3
    assert supplier_id not in {supplier["id"] for supplier in available}


def test_create_dealer_and_route_and_shipment(seeded_client):
    dealer = seeded_client.post(
        "/dealers",
        json={
            "name": "Second Dealer",
            "location": "Pune",
            "required_quantity": 500,
            "deadline": "2030-01-01T00:00:00",
            "current_inventory": 0,
        },
    )
    assert dealer.status_code == 201
    assert dealer.json()["shortfall"] == 500

    route = seeded_client.post(
        "/routes",
        json={
            "from_location_id": 101,
            "to_location_id": dealer.json()["id"],
            "distance_km": 300,
            "travel_time_hours": 6,
            "carbon_per_km": 0.2,
        },
    )
    assert route.status_code == 201
    assert route.json()["is_available"] is True
    assert route.json()["carbon_emission"] == 60.0

    shipment = seeded_client.post(
        "/shipments",
        json={
            "product_id": 1,
            "from_id": 101,
            "to_id": dealer.json()["id"],
            "quantity": 500,
            "expected_arrival": "2030-01-02T00:00:00",
        },
    )
    assert shipment.status_code == 201
    assert shipment.json()["status"] == "PENDING"
    assert shipment.json()["delay_hours"] == 0

    assert seeded_client.post(
        "/routes",
        json={
            "from_location_id": 101,
            "to_location_id": 201,
            "distance_km": 0,
            "travel_time_hours": 6,
            "carbon_per_km": 0.2,
        },
    ).status_code == 422


def test_invalid_audit_actor_returns_422(seeded_client):
    response = seeded_client.post(
        "/audit-logs",
        json={"actor": "robot", "action_type": "x", "result": "y"},
    )
    assert response.status_code == 422
