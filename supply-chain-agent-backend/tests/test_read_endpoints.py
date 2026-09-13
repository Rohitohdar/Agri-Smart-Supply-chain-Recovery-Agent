"""Read-only view endpoints: /inventory, /vendors and /demand."""

from datetime import timedelta

from app.utils import utcnow


# --- /inventory ------------------------------------------------------------


def test_inventory_lists_warehouses_and_the_dealer_with_totals(seeded_client):
    body = seeded_client.get("/inventory").json()

    assert [w["location_id"] for w in body["warehouses"]] == [101, 102, 103]
    assert [w["location_type"] for w in body["warehouses"]] == ["warehouse"] * 3
    assert [w["inventory"] for w in body["warehouses"]] == [
        {"1": 450},
        {"1": 120},
        {"1": 600},
    ]
    assert [w["total_quantity"] for w in body["warehouses"]] == [450, 120, 600]

    assert len(body["dealers"]) == 1
    assert body["dealers"][0]["location_type"] == "dealer"
    assert body["dealers"][0]["current_inventory"] == 300

    assert body["total_quantity"] == 1470
    assert body["generated_at"]


def test_inventory_for_one_warehouse(seeded_client):
    body = seeded_client.get("/inventory/101").json()
    assert body == {
        "location_id": 101,
        "name": "Central Depot",
        "location": "Nagpur",
        "location_type": "warehouse",
        "inventory": {"1": 450},
        "total_quantity": 450,
    }


def test_inventory_for_one_dealer(seeded_client):
    body = seeded_client.get("/inventory/201").json()
    assert body["location_type"] == "dealer"
    assert body["name"] == "Krishi Seva Kendra"
    assert body["current_inventory"] == 300
    assert body["total_quantity"] == 300
    assert "inventory" not in body


def test_inventory_reflects_stock_changes(seeded_client):
    seeded_client.put("/warehouses/102/inventory/1", json={"quantity": 5})
    assert seeded_client.get("/inventory/102").json()["total_quantity"] == 5
    assert seeded_client.get("/inventory").json()["total_quantity"] == 1355


def test_inventory_rejects_supplier_ids_with_a_pointer_to_vendors(seeded_client):
    response = seeded_client.get("/inventory/1")
    assert response.status_code == 404
    assert "/vendors/1" in response.json()["detail"]


def test_inventory_rejects_ids_outside_the_namespace(seeded_client):
    response = seeded_client.get("/inventory/999")
    assert response.status_code == 404
    assert "namespace" in response.json()["detail"]


def test_inventory_404s_for_a_missing_warehouse_in_range(seeded_client):
    assert seeded_client.get("/inventory/150").status_code == 404


# --- /vendors --------------------------------------------------------------


def test_vendors_return_price_delivery_and_carbon_cheapest_first(seeded_client):
    vendors = seeded_client.get("/vendors").json()
    assert len(vendors) == 3
    assert [v["id"] for v in vendors] == [1, 2, 3]
    assert [v["price_per_unit"] for v in vendors] == [24.9, 26.75, 28.5]
    assert all(v["product_name"] == "Urea" and v["unit"] == "bag" for v in vendors)
    assert all(v["is_available"] is True for v in vendors)
    assert {v["delivery_hours"] for v in vendors} == {30.0, 8.0, 12.0}

    cheapest = vendors[0]
    assert cheapest["available_quantity"] == 800
    assert cheapest["carbon_per_unit"] == 6.5


def test_vendors_can_be_filtered_to_available_only(seeded_client):
    seeded_client.patch("/suppliers/1", json={"is_available": False})
    vendors = seeded_client.get("/vendors", params={"only_available": "true"}).json()
    assert [v["id"] for v in vendors] == [2, 3]
    assert len(seeded_client.get("/vendors").json()) == 3


def test_vendor_detail_and_missing_vendor(seeded_client):
    vendor = seeded_client.get("/vendors/2").json()
    assert vendor["name"] == "GreenFields Fertilizers"
    assert vendor["delivery_hours"] == 8.0
    assert seeded_client.get("/vendors/999").status_code == 404


# --- /demand ---------------------------------------------------------------


def test_demand_reports_the_seeded_shortfall_as_a_violation(seeded_client):
    body = seeded_client.get("/demand").json()

    assert body["dealer_id"] == 201
    assert body["dealer_name"] == "Krishi Seva Kendra"
    assert body["required_quantity"] == 1000
    assert body["available_quantity"] == 300
    assert body["shortage"] == 700
    assert body["deadline"]

    assert len(body["active_shipments"]) == 1
    assert body["active_shipments"][0]["id"] == 1
    assert body["active_shipment_quantity"] == 700

    assert body["constraint_violated"] is True
    assert body["constraint_violations"] == ["shortage of 700 units (300 of 1000 on hand)"]


def test_demand_is_satisfied_when_stock_covers_the_requirement(seeded_client):
    seeded_client.patch("/dealers/201", json={"required_quantity": 300})
    body = seeded_client.get("/demand").json()
    assert body["shortage"] == 0
    assert body["constraint_violations"] == []
    assert body["constraint_violated"] is False


def test_demand_flags_a_shipment_arriving_after_the_deadline(seeded_client):
    # Full stock, so the only possible violation is the late shipment.
    seeded_client.patch(
        "/dealers/201",
        json={
            "required_quantity": 300,
            "deadline": (utcnow() - timedelta(hours=1)).isoformat(),
        },
    )
    body = seeded_client.get("/demand").json()
    assert body["shortage"] == 0
    assert body["constraint_violated"] is True
    assert len(body["constraint_violations"]) == 1
    assert "shipment 1" in body["constraint_violations"][0]
    assert "after the deadline" in body["constraint_violations"][0]


def test_demand_ignores_arrived_shipments(seeded_client):
    seeded_client.patch(
        "/dealers/201",
        json={
            "required_quantity": 300,
            "deadline": (utcnow() - timedelta(hours=1)).isoformat(),
        },
    )
    assert seeded_client.get("/demand").json()["constraint_violated"] is True

    seeded_client.patch("/shipments/1/status", json={"status": "ARRIVED"})
    body = seeded_client.get("/demand").json()
    assert body["active_shipments"] == []
    assert body["active_shipment_quantity"] == 0
    assert body["constraint_violated"] is False


def test_demand_shortage_is_never_negative(seeded_client):
    seeded_client.patch(
        "/dealers/201", json={"required_quantity": 1, "current_inventory": 500}
    )
    assert seeded_client.get("/demand").json()["shortage"] == 0


def test_demand_accepts_an_explicit_dealer_and_404s_on_unknown(seeded_client):
    assert seeded_client.get("/demand", params={"dealer_id": 201}).json()["dealer_id"] == 201
    assert seeded_client.get("/demand", params={"dealer_id": 999}).status_code == 404


def test_demand_404s_when_no_dealer_exists(seeded_client):
    seeded_client.delete("/dealers/201")
    response = seeded_client.get("/demand")
    assert response.status_code == 404
    assert "No dealers exist" in response.json()["detail"]


# --- typed, documented responses ------------------------------------------


def test_new_paths_are_read_only_and_typed_in_the_openapi_schema(seeded_client):
    spec = seeded_client.get("/openapi.json").json()
    paths = spec["paths"]

    for path in ("/inventory", "/inventory/{location_id}", "/vendors", "/vendors/{vendor_id}", "/demand"):
        assert path in paths, f"{path} missing from OpenAPI"
        assert set(paths[path]) == {"get"}, f"{path} should be GET-only"
        assert "200" in paths[path]["get"]["responses"]

    # Every one of them declares a concrete schema rather than a free-form object.
    for path in ("/inventory", "/inventory/{location_id}", "/vendors", "/vendors/{vendor_id}", "/demand"):
        content = paths[path]["get"]["responses"]["200"]["content"]["application/json"]
        assert "schema" in content

    demand = spec["components"]["schemas"]["DemandResponse"]
    assert {"shortage", "constraint_violated", "constraint_violations"} <= set(
        demand["properties"]
    )
    assert demand["properties"]["constraint_violated"]["readOnly"] is True

    inventory = spec["components"]["schemas"]["InventoryOverview"]
    assert {"warehouses", "dealers", "total_quantity", "generated_at"} <= set(
        inventory["properties"]
    )

    vendor = spec["components"]["schemas"]["VendorRead"]
    assert {
        "price_per_unit",
        "available_quantity",
        "delivery_hours",
        "carbon_per_unit",
        "is_available",
        "product_name",
    } <= set(vendor["properties"])
