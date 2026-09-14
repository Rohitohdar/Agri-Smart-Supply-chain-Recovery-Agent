"""Disruption triggers: shipment delay, vendor failure, route block, demand spike.

Beyond each endpoint's happy path and its audit entry, these tests check the
guarantee that makes the triggers useful for demos: a rejected trigger changes
nothing and adds no audit entry.
"""

from datetime import datetime, timedelta

from app.utils import utcnow


def _iso_close_to(value: str, expected: timedelta, *, tolerance_seconds: int = 300) -> bool:
    return (
        abs((datetime.fromisoformat(value) - (utcnow() + expected)).total_seconds())
        < tolerance_seconds
    )


# --- POST /simulate/shipment-delay ----------------------------------------


def test_shipment_delay_marks_delayed_and_pushes_the_eta(seeded_client):
    response = seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 12}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["shipment"]["status"] == "DELAYED"
    assert body["shipment"]["delay_hours"] == 12.0
    assert body["delay_hours"] == 12.0
    assert body["previous_status"] == "PENDING"
    assert body["audit_log_id"] > 0

    # ETA moves from the seeded ~24 h out to ~36 h out.
    assert _iso_close_to(body["shipment"]["expected_arrival"], timedelta(hours=36))
    assert _iso_close_to(body["previous_expected_arrival"], timedelta(hours=24))

    assert seeded_client.get("/shipments/1").json()["status"] == "DELAYED"


def test_repeated_delays_compound(seeded_client):
    seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 12}
    )
    second = seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 12}
    ).json()

    assert second["shipment"]["delay_hours"] == 24.0
    assert second["previous_status"] == "DELAYED"
    assert _iso_close_to(second["shipment"]["expected_arrival"], timedelta(hours=48))


def test_delay_that_pushes_past_the_deadline_violates_the_constraint(seeded_client):
    seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 50}
    )

    demand = seeded_client.get("/demand").json()
    assert demand["constraint_violated"] is True
    assert any("after the deadline" in reason for reason in demand["constraint_violations"])


def test_shipment_delay_refuses_a_terminal_shipment(seeded_client):
    seeded_client.patch("/shipments/1/status", json={"status": "ARRIVED"})
    arrived = seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 5}
    )
    assert arrived.status_code == 409
    assert arrived.json()["reason"] == "shipment_not_delayable"

    seeded_client.post("/admin/reset")
    seeded_client.post("/shipment/1/cancel")
    cancelled = seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 5}
    )
    assert cancelled.status_code == 409
    assert cancelled.json()["reason"] == "shipment_not_delayable"


def test_shipment_delay_rejects_a_bad_request_and_unknown_shipment(seeded_client):
    assert (
        seeded_client.post(
            "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 0}
        ).status_code
        == 422
    )
    assert (
        seeded_client.post(
            "/simulate/shipment-delay", json={"shipment_id": 999, "delay_hours": 5}
        ).status_code
        == 404
    )


# --- POST /simulate/vendor-failure ----------------------------------------


def test_vendor_failure_takes_the_vendor_out_of_service(seeded_client):
    response = seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 2})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["vendor"]["id"] == 2
    assert body["vendor"]["is_available"] is False
    assert body["vendor"]["product_name"] == "Urea"
    assert body["previous_is_available"] is True
    assert body["audit_log_id"] > 0

    assert seeded_client.get("/suppliers/2").json()["is_available"] is False
    available = seeded_client.get("/vendors", params={"only_available": "true"}).json()
    assert [vendor["id"] for vendor in available] == [3, 1]  # Bharat (365) then AgroChem (410)


def test_vendor_failure_is_refused_twice(seeded_client):
    assert seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 2}).status_code == 200

    again = seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 2})
    assert again.status_code == 409
    assert again.json()["reason"] == "vendor_already_unavailable"


def test_vendor_failure_404s_for_an_unknown_vendor(seeded_client):
    assert (
        seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 999}).status_code
        == 404
    )


# --- POST /simulate/route-block -------------------------------------------


def test_route_block_marks_the_route_unavailable(seeded_client):
    response = seeded_client.post("/simulate/route-block", json={"route_id": 3})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["route"]["id"] == 3
    assert body["route"]["is_available"] is False
    assert body["previous_is_available"] is True
    assert body["audit_log_id"] > 0

    assert seeded_client.get("/routes/3").json()["is_available"] is False
    available = seeded_client.get("/routes", params={"only_available": "true"}).json()
    assert sorted(route["id"] for route in available) == [1, 2, 4]


def test_route_block_is_refused_twice_and_404s_when_unknown(seeded_client):
    assert seeded_client.post("/simulate/route-block", json={"route_id": 3}).status_code == 200
    again = seeded_client.post("/simulate/route-block", json={"route_id": 3})
    assert again.status_code == 409
    assert again.json()["reason"] == "route_already_unavailable"

    assert seeded_client.post("/simulate/route-block", json={"route_id": 999}).status_code == 404


def test_blocked_route_cannot_be_used_to_reroute(seeded_client):
    seeded_client.post("/simulate/route-block", json={"route_id": 2})

    response = seeded_client.post("/shipment/1/reroute", json={"new_route_id": 2})
    assert response.status_code == 409
    assert response.json()["reason"] == "route_unavailable"
    assert seeded_client.get("/shipments/1").json()["from_id"] == 101


# --- POST /simulate/demand-spike ------------------------------------------


def test_demand_spike_raises_the_requirement_and_the_shortage(seeded_client):
    response = seeded_client.post(
        "/simulate/demand-spike",
        json={"dealer_id": 201, "new_required_quantity": 1500},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["dealer"]["required_quantity"] == 1500
    assert body["dealer"]["shortfall"] == 1200
    assert body["previous_required_quantity"] == 1000
    assert body["shortage_before"] == 700
    assert body["shortage_after"] == 1200
    assert body["audit_log_id"] > 0

    demand = seeded_client.get("/demand").json()
    assert demand["required_quantity"] == 1500
    assert demand["shortage"] == 1200
    assert demand["on_hand_shortfall"] == 1200
    assert demand["covered_quantity"] == 1000  # 300 on hand + 700 inbound
    assert demand["constraint_violated"] is True


def test_demand_spike_must_actually_raise_the_requirement(seeded_client):
    for value in (1000, 500):
        response = seeded_client.post(
            "/simulate/demand-spike",
            json={"dealer_id": 201, "new_required_quantity": value},
        )
        assert response.status_code == 409
        assert response.json()["reason"] == "not_a_demand_spike"

    assert seeded_client.get("/dealers/201").json()["required_quantity"] == 1000


def test_demand_spike_rejects_a_bad_value_and_unknown_dealer(seeded_client):
    assert (
        seeded_client.post(
            "/simulate/demand-spike",
            json={"dealer_id": 201, "new_required_quantity": 0},
        ).status_code
        == 422
    )
    assert (
        seeded_client.post(
            "/simulate/demand-spike",
            json={"dealer_id": 999, "new_required_quantity": 2000},
        ).status_code
        == 404
    )


# --- audit trail and contract ---------------------------------------------


def test_all_disruptions_share_the_disruption_injected_action_type(seeded_client):
    seeded_client.post(
        "/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 6}
    )
    seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 2})
    seeded_client.post("/simulate/route-block", json={"route_id": 3})
    seeded_client.post(
        "/simulate/demand-spike", json={"dealer_id": 201, "new_required_quantity": 1500}
    )

    logs = seeded_client.get("/audit-logs/recent", params={"limit": 20}).json()
    disruptions = [log for log in logs if log["action_type"] == "disruption_injected"]
    assert len(disruptions) == 4
    assert {log["details"]["disruption"] for log in disruptions} == {
        "shipment_delay",
        "vendor_failure",
        "route_block",
        "demand_spike",
    }

    by_kind = {log["details"]["disruption"]: log for log in disruptions}
    assert by_kind["shipment_delay"]["details"]["status"] == {
        "before": "PENDING",
        "after": "DELAYED",
    }
    assert by_kind["vendor_failure"]["details"]["is_available"] == {
        "before": True,
        "after": False,
    }
    assert by_kind["route_block"]["details"]["is_available"] == {
        "before": True,
        "after": False,
    }
    assert by_kind["demand_spike"]["details"]["shortage"] == {
        "before": 700,
        "after": 1200,
    }


def test_rejected_disruptions_leave_no_audit_trail(seeded_client):
    before = len(seeded_client.get("/audit-logs").json())
    assert before == 1

    assert seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 999}).status_code == 404
    assert (
        seeded_client.post(
            "/simulate/demand-spike",
            json={"dealer_id": 201, "new_required_quantity": 1000},
        ).status_code
        == 409
    )

    assert len(seeded_client.get("/audit-logs").json()) == before
    assert seeded_client.get("/dealers/201").json()["required_quantity"] == 1000


def test_disruptions_are_documented_as_typed_post_endpoints(seeded_client):
    spec = seeded_client.get("/openapi.json").json()
    paths = spec["paths"]
    expected = {
        "/simulate/shipment-delay": "ShipmentDelayResponse",
        "/simulate/vendor-failure": "VendorFailureResponse",
        "/simulate/route-block": "RouteBlockResponse",
        "/simulate/demand-spike": "DemandSpikeResponse",
    }
    for path, schema in expected.items():
        assert path in paths, f"{path} missing from OpenAPI"
        assert "post" in paths[path]
        content = paths[path]["post"]["responses"]["200"]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith(schema)
