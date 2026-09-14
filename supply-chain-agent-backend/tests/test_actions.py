"""State-changing actions: transfer, reroute, purchase and cancel.

Each action is checked for its happy path (including the returned resulting
state and audit entry) and for every way it can be refused. Refusals must leave
the database exactly as it was and must not append an audit entry.
"""

from datetime import datetime, timedelta

import pytest

from app.utils import utcnow


def _iso_close_to(value: str, expected: timedelta, *, tolerance_seconds: int = 300) -> bool:
    """Whether an ISO timestamp from the API is about ``now + expected``."""
    return abs((datetime.fromisoformat(value) - (utcnow() + expected)).total_seconds()) < tolerance_seconds


# --- POST /inventory/transfer ---------------------------------------------


def test_transfer_between_warehouses_returns_before_and_after(seeded_client):
    response = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 103, "quantity": 50},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["product_id"] == 1
    assert body["quantity"] == 50
    assert body["source_before"] == {
        "location_id": 101,
        "name": "Central Depot",
        "location": "Nagpur",
        "location_type": "warehouse",
        "inventory": {"1": 450},
        "total_quantity": 450,
    }
    assert body["source_after"]["inventory"] == {"1": 400}
    assert body["source_after"]["total_quantity"] == 400
    assert body["destination_before"]["inventory"] == {"1": 600}
    assert body["destination_after"]["inventory"] == {"1": 650}
    assert body["destination_after"]["location_type"] == "warehouse"
    assert body["audit_log_id"] > 0

    assert seeded_client.get("/warehouses/101/inventory/1").json()["quantity"] == 400
    assert seeded_client.get("/warehouses/103/inventory/1").json()["quantity"] == 650


def test_transfer_to_the_dealer_uses_the_dealer_shape(seeded_client):
    body = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 201, "quantity": 100},
    ).json()

    assert body["source_after"]["total_quantity"] == 350
    assert body["destination_before"] == {
        "location_id": 201,
        "name": "Krishi Seva Kendra",
        "location": "Indore",
        "location_type": "dealer",
        "current_inventory": 300,
        "total_quantity": 300,
    }
    assert body["destination_after"]["current_inventory"] == 400

    demand = seeded_client.get("/demand").json()
    assert demand["available_quantity"] == 400
    assert demand["shortage"] == 600


def test_transfer_rejects_insufficient_stock_and_changes_nothing(seeded_client):
    response = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 103, "to_id": 101, "quantity": 601},
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "insufficient_stock"

    assert seeded_client.get("/warehouses/103/inventory/1").json()["quantity"] == 600
    assert seeded_client.get("/warehouses/101/inventory/1").json()["quantity"] == 450
    assert len(seeded_client.get("/audit-logs").json()) == 1


def test_transfer_rejects_a_same_location_move(seeded_client):
    response = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 101, "quantity": 10},
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "same_location"


def test_transfer_rejects_a_non_warehouse_source(seeded_client):
    response = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 201, "to_id": 103, "quantity": 10},
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "invalid_source_location"


def test_transfer_rejects_a_supplier_destination(seeded_client):
    response = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 2, "quantity": 10},
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "not_a_stock_location"
    assert "supplier" in response.json()["detail"]


def test_transfer_rejects_a_non_positive_quantity(seeded_client):
    assert (
        seeded_client.post(
            "/inventory/transfer",
            json={"from_warehouse_id": 101, "to_id": 103, "quantity": 0},
        ).status_code
        == 422
    )


def test_transfer_404s_for_unknown_in_range_locations(seeded_client):
    assert (
        seeded_client.post(
            "/inventory/transfer",
            json={"from_warehouse_id": 150, "to_id": 103, "quantity": 10},
        ).status_code
        == 404
    )
    assert (
        seeded_client.post(
            "/inventory/transfer",
            json={"from_warehouse_id": 101, "to_id": 199, "quantity": 10},
        ).status_code
        == 404
    )


def test_transfer_accepts_an_explicit_product_and_404s_on_unknown(seeded_client):
    ok = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 103, "quantity": 10, "product_id": 1},
    )
    assert ok.status_code == 200
    assert ok.json()["product_id"] == 1

    assert (
        seeded_client.post(
            "/inventory/transfer",
            json={"from_warehouse_id": 101, "to_id": 103, "quantity": 10, "product_id": 99},
        ).status_code
        == 404
    )


def test_transfer_requires_a_product_when_the_catalogue_is_ambiguous(seeded_client):
    seeded_client.post("/products", json={"name": "DAP", "unit": "bag"})

    ambiguous = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 103, "quantity": 10},
    )
    assert ambiguous.status_code == 409
    assert ambiguous.json()["reason"] == "ambiguous_product"

    explicit = seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 103, "quantity": 10, "product_id": 1},
    )
    assert explicit.status_code == 200


# --- POST /shipment/{id}/reroute ------------------------------------------


def test_reroute_switches_origin_and_recomputes_the_eta(seeded_client):
    response = seeded_client.post("/shipment/1/reroute", json={"new_route_id": 2})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["shipment"]["from_id"] == 102
    assert body["shipment"]["to_id"] == 201
    assert body["shipment"]["status"] == "PENDING"
    assert body["route"]["id"] == 2
    assert body["previous_from_id"] == 101
    assert body["previous_to_id"] == 201
    assert body["previous_expected_arrival"] is not None
    assert body["audit_log_id"] > 0

    # Route 2 takes 22 h, so the new ETA is ~22 h from now, not the seeded 24 h.
    assert _iso_close_to(body["shipment"]["expected_arrival"], timedelta(hours=22))

    assert seeded_client.get("/shipments/1").json()["from_id"] == 102


def test_reroute_rejects_an_unavailable_route(seeded_client):
    seeded_client.patch("/routes/3", json={"is_available": False})

    response = seeded_client.post("/shipment/1/reroute", json={"new_route_id": 3})
    assert response.status_code == 409
    assert response.json()["reason"] == "route_unavailable"
    assert seeded_client.get("/shipments/1").json()["from_id"] == 101


def test_reroute_rejects_a_route_that_ends_elsewhere(seeded_client):
    created = seeded_client.post(
        "/routes",
        json={
            "from_location_id": 101,
            "to_location_id": 102,
            "distance_km": 100,
            "travel_time_hours": 2,
            "carbon_per_km": 0.1,
        },
    ).json()

    response = seeded_client.post(
        "/shipment/1/reroute", json={"new_route_id": created["id"]}
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "route_destination_mismatch"


def test_reroute_404s_for_unknown_shipment_and_route(seeded_client):
    assert (
        seeded_client.post("/shipment/999/reroute", json={"new_route_id": 1}).status_code
        == 404
    )
    assert (
        seeded_client.post("/shipment/1/reroute", json={"new_route_id": 999}).status_code
        == 404
    )


def test_reroute_rejects_a_terminal_shipment(seeded_client):
    seeded_client.patch("/shipments/1/status", json={"status": "ARRIVED"})
    arrived = seeded_client.post("/shipment/1/reroute", json={"new_route_id": 2})
    assert arrived.status_code == 409
    assert arrived.json()["reason"] == "shipment_not_reroutable"

    seeded_client.post("/admin/reset")
    seeded_client.post("/shipment/1/cancel")
    cancelled = seeded_client.post("/shipment/1/reroute", json={"new_route_id": 2})
    assert cancelled.status_code == 409
    assert cancelled.json()["reason"] == "shipment_not_reroutable"


# --- POST /vendor/{id}/purchase -------------------------------------------


def test_purchase_reserves_vendor_stock_and_creates_a_shipment(seeded_client):
    response = seeded_client.post("/vendor/1/purchase", json={"quantity": 200})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["vendor"]["id"] == 1
    assert body["vendor_available_before"] == 800
    assert body["vendor"]["available_quantity"] == 600
    assert body["shipment"]["from_id"] == 1
    assert body["shipment"]["to_id"] == 201
    assert body["shipment"]["quantity"] == 200
    assert body["shipment"]["status"] == "PENDING"
    assert body["audit_log_id"] > 0

    # Vendor 1 delivers in 30 h, so the new shipment lands ~30 h out.
    assert _iso_close_to(body["shipment"]["expected_arrival"], timedelta(hours=30))

    assert seeded_client.get("/suppliers/1").json()["available_quantity"] == 600
    demand = seeded_client.get("/demand").json()
    assert demand["active_shipment_quantity"] == 900
    assert len(demand["active_shipments"]) == 2


def test_purchase_rejects_more_than_the_vendor_has(seeded_client):
    response = seeded_client.post("/vendor/1/purchase", json={"quantity": 900})
    assert response.status_code == 409
    assert response.json()["reason"] == "insufficient_supplier_stock"

    assert seeded_client.get("/suppliers/1").json()["available_quantity"] == 800
    assert len(seeded_client.get("/shipments").json()) == 1
    assert len(seeded_client.get("/audit-logs").json()) == 1


def test_purchase_rejects_an_unavailable_vendor(seeded_client):
    seeded_client.patch("/suppliers/2", json={"is_available": False})

    response = seeded_client.post("/vendor/2/purchase", json={"quantity": 10})
    assert response.status_code == 409
    assert response.json()["reason"] == "vendor_unavailable"


def test_purchase_404s_for_unknown_vendor_and_422_for_bad_quantity(seeded_client):
    assert seeded_client.post("/vendor/999/purchase", json={"quantity": 10}).status_code == 404
    assert seeded_client.post("/vendor/1/purchase", json={"quantity": 0}).status_code == 422


# --- POST /shipment/{id}/cancel -------------------------------------------


def test_cancel_marks_the_shipment_and_frees_inbound_demand(seeded_client):
    response = seeded_client.post("/shipment/1/cancel")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["shipment"]["status"] == "CANCELLED"
    assert body["previous_status"] == "PENDING"
    assert body["audit_log_id"] > 0

    assert seeded_client.get("/shipments/1").json()["status"] == "CANCELLED"
    assert seeded_client.get("/shipments", params={"to_id": 201}).json() == []
    assert len(seeded_client.get("/shipments", params={"status": "CANCELLED"}).json()) == 1

    demand = seeded_client.get("/demand").json()
    assert demand["active_shipments"] == []
    assert demand["active_shipment_quantity"] == 0
    assert demand["constraint_violations"] == [
        "coverage shortfall of 700 units (300 of 1000 covered by on-hand + inbound-by-deadline)"
    ]


def test_cancelling_twice_is_refused(seeded_client):
    assert seeded_client.post("/shipment/1/cancel").status_code == 200

    again = seeded_client.post("/shipment/1/cancel")
    assert again.status_code == 409
    assert again.json()["reason"] == "shipment_already_cancelled"


def test_cancel_refuses_an_arrived_shipment(seeded_client):
    seeded_client.patch("/shipments/1/status", json={"status": "ARRIVED"})

    response = seeded_client.post("/shipment/1/cancel")
    assert response.status_code == 409
    assert response.json()["reason"] == "shipment_already_arrived"
    assert seeded_client.get("/shipments/1").json()["status"] == "ARRIVED"


def test_cancel_404s_for_an_unknown_shipment(seeded_client):
    assert seeded_client.post("/shipment/999/cancel").status_code == 404


# --- audit trail -----------------------------------------------------------


def test_every_action_records_before_and_after_in_the_audit_trail(seeded_client):
    seeded_client.post(
        "/inventory/transfer",
        json={"from_warehouse_id": 101, "to_id": 103, "quantity": 50},
    )
    seeded_client.post("/shipment/1/reroute", json={"new_route_id": 2})
    seeded_client.post("/vendor/1/purchase", json={"quantity": 100})
    seeded_client.post("/shipment/1/cancel")

    logs = seeded_client.get("/audit-logs/recent", params={"limit": 10}).json()
    by_action = {log["action_type"]: log for log in logs}
    assert {
        "inventory_transfer",
        "shipment_reroute",
        "vendor_purchase",
        "shipment_cancel",
    } <= set(by_action)

    transfer = by_action["inventory_transfer"]
    assert transfer["actor"] == "system"
    assert transfer["result"] == "success"
    assert transfer["details"]["from"]["before"] == 450
    assert transfer["details"]["from"]["after"] == 400
    assert transfer["details"]["to"]["before"] == 600
    assert transfer["details"]["to"]["after"] == 650

    reroute = by_action["shipment_reroute"]
    assert reroute["details"]["route_id"] == 2
    assert reroute["details"]["before"]["from_id"] == 101
    assert reroute["details"]["after"]["from_id"] == 102

    purchase = by_action["vendor_purchase"]
    assert purchase["details"]["vendor_available"] == {"before": 800, "after": 700}
    assert purchase["details"]["quantity"] == 100
    assert purchase["details"]["total_price"] == 41000.0  # 410 * 100

    cancel = by_action["shipment_cancel"]
    assert cancel["details"]["status"] == {"before": "PENDING", "after": "CANCELLED"}


def test_change_and_audit_commit_together_or_not_at_all(session_factory, monkeypatch):
    """If the audit write fails, the stock movement must roll back with it."""
    import app.services.action_service as action_module
    from app.db.seed import seed_database
    from app.models import Warehouse
    from app.schemas.actions import InventoryTransferRequest
    from app.services.action_service import ActionService

    db = session_factory()
    seed_database(db)

    def boom(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(action_module, "stage", boom)

    service = ActionService(db)
    with pytest.raises(RuntimeError):
        service.transfer_inventory(
            InventoryTransferRequest(from_warehouse_id=101, to_id=103, quantity=50)
        )

    db.expire_all()
    assert db.get(Warehouse, 101).quantity_of(1) == 450
    assert db.get(Warehouse, 103).quantity_of(1) == 600
    db.close()


def test_failed_actions_leave_no_audit_trail(seeded_client):
    before = len(seeded_client.get("/audit-logs").json())
    assert before == 1

    assert (
        seeded_client.post(
            "/inventory/transfer",
            json={"from_warehouse_id": 102, "to_id": 103, "quantity": 121},
        ).status_code
        == 409
    )
    assert seeded_client.post("/vendor/1/purchase", json={"quantity": 9999}).status_code == 409
    assert seeded_client.post("/shipment/1/reroute", json={"new_route_id": 999}).status_code == 404

    assert len(seeded_client.get("/audit-logs").json()) == before
    assert seeded_client.get("/warehouses/102/inventory/1").json()["quantity"] == 120


# --- contract: typed, documented, and aliased ------------------------------


def test_actions_are_documented_as_typed_post_endpoints(seeded_client):
    spec = seeded_client.get("/openapi.json").json()
    paths = spec["paths"]
    expected = {
        "/inventory/transfer": "InventoryTransferResponse",
        "/shipment/{shipment_id}/reroute": "ShipmentRerouteResponse",
        "/vendor/{vendor_id}/purchase": "VendorPurchaseResponse",
        "/shipment/{shipment_id}/cancel": "ShipmentCancelResponse",
    }
    for path, schema in expected.items():
        assert path in paths, f"{path} missing from OpenAPI"
        assert "post" in paths[path]
        content = paths[path]["post"]["responses"]["200"]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith(schema)


def test_plural_aliases_mirror_the_singular_action_paths(seeded_client):
    assert seeded_client.post("/shipments/1/cancel").status_code == 200

    seeded_client.post("/admin/reset")
    assert (
        seeded_client.post("/vendors/1/purchase", json={"quantity": 10}).status_code
        == 200
    )

    seeded_client.post("/admin/reset")
    assert (
        seeded_client.post("/shipments/1/reroute", json={"new_route_id": 2}).status_code
        == 200
    )
