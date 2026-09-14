"""The recovery optimizer: pure, deterministic, and easy to reason about.

Most of these exercise ``app.optimizer`` directly with hand-built state, so the
numbers are known exactly and no clock or database is involved. A few probes at
the end check the endpoint wires the same module to the live database.
"""

from datetime import datetime, timedelta

from app.optimizer import (
    DEFAULT_WEIGHTS,
    TRANSPORT_COST_PER_KM,
    ExclusionReason,
    RecoveryAction,
    RecoveryState,
    RouteSupply,
    SupplierSupply,
    WarehouseSupply,
    evaluate_recovery,
    optimize_recovery,
)
from app.utils import utcnow

NOW = datetime(2026, 1, 1, 0, 0, 0)
DEALER = 201


def state(
    shortage: int,
    *,
    hours: float = 72.0,
    warehouses=(),
    suppliers=(),
    routes=(),
) -> RecoveryState:
    return RecoveryState(
        shortage_quantity=shortage,
        deadline=NOW + timedelta(hours=hours),
        now=NOW,
        destination_location_id=DEALER,
        warehouses=tuple(warehouses),
        suppliers=tuple(suppliers),
        routes=tuple(routes),
    )


def warehouse(warehouse_id: int, quantity: int) -> WarehouseSupply:
    return WarehouseSupply(warehouse_id, f"Warehouse {warehouse_id}", quantity)


def supplier(
    supplier_id: int,
    quantity: int,
    *,
    price: float,
    delivery: float,
    carbon: float,
) -> SupplierSupply:
    return SupplierSupply(supplier_id, f"Vendor {supplier_id}", quantity, price, delivery, carbon)


def route(
    route_id: int, source: int, *, km: float, hours: float, carbon_per_km: float = 0.1
) -> RouteSupply:
    return RouteSupply(route_id, source, DEALER, km, hours, carbon_per_km)


def options_by_id(shortage: int, **kwargs) -> dict:
    return {option.reference_id: option for option in optimize_recovery(state(shortage, **kwargs))}


# --- no feasible option ----------------------------------------------------


def test_no_feasible_option_when_nobody_can_cover_the_shortage():
    plan_state = state(
        500,
        warehouses=[warehouse(101, 100)],
        suppliers=[supplier(1, 200, price=10, delivery=5, carbon=1)],
        routes=[route(1, 101, km=50, hours=4)],
    )

    plan = evaluate_recovery(plan_state)

    assert plan.options == ()
    assert optimize_recovery(plan_state) == []
    assert {item.reason for item in plan.excluded} == {
        ExclusionReason.INSUFFICIENT_QUANTITY
    }
    assert {item.reference_id for item in plan.excluded} == {101, 1}


def test_no_shortage_means_nothing_to_recover():
    plan = evaluate_recovery(state(0, suppliers=[supplier(1, 999, price=1, delivery=1, carbon=1)]))
    assert plan.options == ()
    assert plan.excluded == ()


def test_a_passed_deadline_excludes_every_candidate():
    plan = evaluate_recovery(
        state(
            100,
            hours=-5,
            suppliers=[
                supplier(1, 1000, price=1, delivery=1, carbon=1),
                supplier(2, 1000, price=1, delivery=2, carbon=1),
            ],
        )
    )
    assert plan.options == ()
    assert {item.reason for item in plan.excluded} == {ExclusionReason.MISSES_DEADLINE}


# --- one clearly best option ----------------------------------------------


def test_one_clearly_best_option_dominates_and_scores_zero():
    options = options_by_id(
        500,
        warehouses=[warehouse(101, 1000)],
        suppliers=[
            supplier(1, 1000, price=50, delivery=40, carbon=9),
            supplier(2, 1000, price=30, delivery=30, carbon=5),
        ],
        routes=[route(1, 101, km=100, hours=10, carbon_per_km=0.1)],
    )

    best = options[101]
    assert best.action is RecoveryAction.WAREHOUSE_TRANSFER
    assert best.rank == 1
    assert best.score == 0.0
    # Best on all three metrics, so every normalized value and contribution is 0.
    assert (best.normalized_cost, best.normalized_delivery_hours, best.normalized_carbon) == (
        0.0,
        0.0,
        0.0,
    )
    assert (best.cost_contribution, best.delivery_contribution, best.carbon_contribution) == (
        0.0,
        0.0,
        0.0,
    )
    # Warehouse 101: 100 km * 30 = 3000, 10 h, 100 km * 0.1 = 10 kg.
    assert best.total_cost == 100 * TRANSPORT_COST_PER_KM == 3000.0
    assert best.total_delivery_hours == 10.0
    assert best.total_carbon == 10.0
    # The other two candidates are still ranked, below it.
    assert sorted(option.rank for option in options.values()) == [1, 2, 3]


# --- scoring ---------------------------------------------------------------


def test_score_is_the_weighted_sum_of_the_normalized_metrics():
    options = options_by_id(
        100,
        suppliers=[
            supplier(1, 1000, price=1.0, delivery=10, carbon=0.05),
            supplier(2, 1000, price=2.0, delivery=5, carbon=0.15),
            supplier(3, 1000, price=3.0, delivery=7, carbon=0.10),
        ],
    )

    first, second, third = options[1], options[2], options[3]

    # Raw metrics: cost = price * 100, carbon = carbon_per_unit * 100.
    assert (first.total_cost, first.total_delivery_hours, first.total_carbon) == (100.0, 10.0, 5.0)
    assert (second.total_cost, second.total_delivery_hours, second.total_carbon) == (200.0, 5.0, 15.0)
    assert (third.total_cost, third.total_delivery_hours, third.total_carbon) == (300.0, 7.0, 10.0)

    assert first.normalized_cost == 0.0 and first.normalized_delivery_hours == 1.0
    assert second.normalized_cost == 0.5 and second.normalized_delivery_hours == 0.0
    assert third.normalized_cost == 1.0 and third.normalized_delivery_hours == 0.4

    # score = 0.4 * cost + 0.4 * delivery + 0.2 * carbon
    assert first.score == 0.4 and first.delivery_contribution == 0.4
    assert second.score == 0.4 and second.cost_contribution == 0.2
    assert second.carbon_contribution == 0.2
    assert third.score == 0.66

    # Weights are the documented 0.4 / 0.4 / 0.2 default.
    assert (DEFAULT_WEIGHTS.cost, DEFAULT_WEIGHTS.delivery_hours, DEFAULT_WEIGHTS.carbon) == (
        0.4,
        0.4,
        0.2,
    )
    assert DEFAULT_WEIGHTS.total() == 1.0


def test_normalization_only_uses_the_feasible_candidates():
    plan = evaluate_recovery(
        state(
            100,
            hours=48,
            suppliers=[
                supplier(9, 1000, price=0.5, delivery=100, carbon=1),  # cheapest, too slow
                supplier(1, 1000, price=2.0, delivery=10, carbon=1),
                supplier(2, 1000, price=4.0, delivery=20, carbon=2),
            ],
        )
    )

    assert [item.reference_id for item in plan.excluded] == [9]
    assert plan.excluded[0].reason is ExclusionReason.MISSES_DEADLINE

    cheapest_feasible = plan.options[0]
    assert cheapest_feasible.reference_id == 1
    # 0.0 proves the excluded 50.0 (cheapest overall) did not set the minimum.
    assert cheapest_feasible.normalized_cost == 0.0


# --- tie-breaking ----------------------------------------------------------


def test_identical_candidates_tie_break_on_reference_id():
    options = optimize_recovery(
        state(
            500,
            warehouses=[warehouse(102, 1000), warehouse(101, 1000)],
            routes=[
                route(1, 101, km=100, hours=10),
                route(2, 102, km=100, hours=10),
            ],
        )
    )

    assert [option.reference_id for option in options] == [101, 102]
    assert all(option.score == 0.0 for option in options)


def test_score_tie_breaks_on_cost():
    options = optimize_recovery(
        state(
            100,
            suppliers=[
                supplier(1, 1000, price=1.0, delivery=10, carbon=0.05),
                supplier(2, 1000, price=2.0, delivery=5, carbon=0.15),
                supplier(3, 1000, price=3.0, delivery=7, carbon=0.10),
            ],
        )
    )

    # Options 1 and 2 both score 0.4; the cheaper one (100.0 vs 200.0) wins.
    assert options[0].reference_id == 1 and options[1].reference_id == 2
    assert options[0].score == options[1].score == 0.4
    assert options[0].total_cost < options[1].total_cost
    assert options[2].score > 0.4


# --- deadline feasibility --------------------------------------------------


def test_cheapest_option_is_infeasible_when_it_misses_the_deadline():
    plan = evaluate_recovery(
        state(
            500,
            hours=48,
            suppliers=[
                supplier(1, 1000, price=10, delivery=100, carbon=1),  # cheapest, far too slow
                supplier(2, 1000, price=20, delivery=10, carbon=2),
            ],
        )
    )

    assert [item.reference_id for item in plan.excluded] == [1]
    rejected = plan.excluded[0]
    assert rejected.reason is ExclusionReason.MISSES_DEADLINE
    assert rejected.delivery_hours == 100.0
    assert rejected.hours_available == 48.0

    assert [option.reference_id for option in plan.options] == [2]
    assert plan.options[0].rank == 1
    # A lone feasible option: single_feasible_option is set and score is 0.
    assert plan.options[0].single_feasible_option is True
    assert plan.options[0].score == 0.0


def test_single_feasible_option_flag_and_raw_metrics():
    """When exactly one candidate survives filtering, single_feasible_option is
    True and the raw cost/delivery/carbon figures are preserved unchanged."""
    plan = evaluate_recovery(
        state(
            100,
            hours=48,
            suppliers=[
                supplier(1, 1000, price=10, delivery=100, carbon=1),  # too slow
                supplier(2, 1000, price=25, delivery=20, carbon=3),   # only survivor
                supplier(3, 50,   price=5,  delivery=10, carbon=1),   # insufficient stock
            ],
        )
    )

    assert len(plan.options) == 1
    option = plan.options[0]
    assert option.reference_id == 2
    assert option.single_feasible_option is True
    # Raw metrics are the vendor's own numbers, not normalized.
    assert option.total_cost == 25 * 100  # price_per_unit * shortage_quantity
    assert option.total_delivery_hours == 20.0
    assert option.total_carbon == 3 * 100  # carbon_per_unit * shortage_quantity
    # Normalized values and contributions are all 0 (no comparison possible).
    assert option.normalized_cost == 0.0
    assert option.normalized_delivery_hours == 0.0
    assert option.normalized_carbon == 0.0
    assert option.score == 0.0
    # Two candidates were excluded.
    assert len(plan.excluded) == 2


def test_single_feasible_option_flag_absent_with_multiple_candidates():
    """single_feasible_option is False when more than one candidate is feasible."""
    options = optimize_recovery(
        state(
            100,
            suppliers=[
                supplier(1, 1000, price=10, delivery=10, carbon=1),
                supplier(2, 1000, price=20, delivery=5,  carbon=2),
            ],
        )
    )

    assert len(options) == 2
    assert all(not option.single_feasible_option for option in options)


def test_a_candidate_landing_exactly_on_the_deadline_is_feasible():
    plan = evaluate_recovery(
        state(100, hours=12, suppliers=[supplier(1, 1000, price=5, delivery=12, carbon=1)])
    )
    assert [option.reference_id for option in plan.options] == [1]


# --- warehouse specifics ---------------------------------------------------


def test_warehouse_without_a_route_is_excluded():
    plan = evaluate_recovery(
        state(
            100,
            warehouses=[warehouse(101, 1000)],
            suppliers=[supplier(1, 1000, price=5, delivery=5, carbon=1)],
            routes=[],
        )
    )

    assert [item.reason for item in plan.excluded] == [ExclusionReason.NO_AVAILABLE_ROUTE]
    assert plan.excluded[0].reference_id == 101
    assert [option.action for option in plan.options] == [RecoveryAction.VENDOR_PURCHASE]


def test_warehouse_transfer_prices_freight_from_the_route():
    options = optimize_recovery(
        state(
            100,
            warehouses=[warehouse(101, 1000)],
            routes=[route(7, 101, km=200, hours=8, carbon_per_km=0.25)],
        )
    )
    option = options[0]
    assert option.action is RecoveryAction.WAREHOUSE_TRANSFER
    assert option.route_id == 7
    assert option.total_cost == 200 * TRANSPORT_COST_PER_KM == 6000.0
    assert option.total_delivery_hours == 8.0
    assert option.total_carbon == 50.0


def test_warehouse_uses_its_fastest_route_to_the_dealer():
    options = optimize_recovery(
        state(
            100,
            warehouses=[warehouse(101, 1000)],
            routes=[
                route(1, 101, km=900, hours=30),
                route(2, 101, km=200, hours=8, carbon_per_km=0.25),
            ],
        )
    )
    assert options[0].route_id == 2
    assert options[0].total_delivery_hours == 8.0


# --- determinism -----------------------------------------------------------


def test_same_state_always_produces_the_same_plan():
    build = dict(
        warehouses=[warehouse(101, 1000)],
        suppliers=[supplier(1, 1000, price=2, delivery=30, carbon=3)],
        routes=[route(1, 101, km=100, hours=10)],
    )
    assert optimize_recovery(state(500, **build)) == optimize_recovery(state(500, **build))


def test_candidate_order_does_not_affect_the_ranking():
    warehouses = [warehouse(101, 1000), warehouse(102, 1000)]
    suppliers = [
        supplier(1, 1000, price=2, delivery=30, carbon=3),
        supplier(2, 1000, price=4, delivery=5, carbon=1),
    ]
    routes = [route(1, 101, km=400, hours=9), route(2, 102, km=200, hours=11)]

    forward = evaluate_recovery(state(500, warehouses=warehouses, suppliers=suppliers, routes=routes))
    reversed_inputs = evaluate_recovery(
        state(500, warehouses=warehouses[::-1], suppliers=suppliers[::-1], routes=routes[::-1])
    )
    assert forward == reversed_inputs


# --- HTTP endpoint ---------------------------------------------------------


def _deadline(hours: float = 72.0) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


def test_endpoint_ranks_the_seeded_vendors(seeded_client):
    response = seeded_client.post(
        "/optimize/recovery", json={"shortage_quantity": 700, "deadline": _deadline()}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["hours_available"] == 72.0
    assert body["weights"] == {"cost": 0.4, "delivery_hours": 0.4, "carbon": 0.2}

    # Reroute shipment #1 via route #4 (11 h, 620 km * 30 = 18600, 62 kg carbon)
    # beats both vendor_purchase options on cost and delivery, so it ranks first.
    # Multiple reroute alternatives (routes #2, #3) and vendor options follow.
    actions = [(o["action"], o["reference_id"]) for o in body["options"]]
    assert actions[0] == ("reroute_shipment", 1)  # via route #4, cheapest and fastest

    top = body["options"][0]
    assert top["action"] == "reroute_shipment"
    assert top["total_cost"] == 18600.0
    assert top["total_delivery_hours"] == 11.0
    assert top["score"] == 0.0  # best on all metrics

    # Vendor options are present and ranked after the reroute.
    vendor_actions = [o for o in body["options"] if o["action"] == "vendor_purchase"]
    assert any(o["reference_id"] == 3 for o in vendor_actions)  # Bharat Urea Traders


def test_endpoint_reports_no_feasible_options(seeded_client):
    # With shortage=5000, warehouses and vendors are excluded on quantity.
    # Reroute of shipment #1 (700 units) can still be feasible since it delivers
    # what the shipment has — it is not required to cover the full shortage.
    # To get a truly empty options list, use a passed deadline.
    body = seeded_client.post(
        "/optimize/recovery",
        json={"shortage_quantity": 5000, "deadline": (utcnow() + timedelta(hours=1)).isoformat()},
    ).json()

    assert body["options"] == []
    shortage_reasons = {
        item["reason"]
        for item in body["excluded"]
        if item["action"] != "reroute_shipment"
    }
    assert shortage_reasons == {"insufficient_quantity"}


def test_endpoint_reflects_current_database_state(seeded_client):
    request = {"shortage_quantity": 700, "deadline": _deadline()}
    options = seeded_client.post("/optimize/recovery", json=request).json()["options"]
    # Reroute shipment #1 ranks first; vendor_purchase options follow.
    assert options[0]["action"] == "reroute_shipment"
    assert options[0]["reference_id"] == 1

    # Block all routes so reroute is excluded; only vendor_purchase options remain.
    for route_id in [1, 2, 3, 4]:
        seeded_client.post("/simulate/route-block", json={"route_id": route_id})
    options_no_routes = seeded_client.post("/optimize/recovery", json=request).json()["options"]
    assert all(o["action"] == "vendor_purchase" for o in options_no_routes)
    assert options_no_routes[0]["reference_id"] == 3  # Bharat Urea Traders


def test_endpoint_is_typed_and_validated(seeded_client):
    spec = seeded_client.get("/openapi.json").json()
    post = spec["paths"]["/optimize/recovery"]["post"]
    content = post["responses"]["200"]["content"]["application/json"]
    assert content["schema"]["$ref"].endswith("RecoveryPlanResponse")

    assert (
        seeded_client.post(
            "/optimize/recovery", json={"shortage_quantity": 0, "deadline": _deadline()}
        ).status_code
        == 422
    )
