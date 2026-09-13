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
    # A lone feasible option is trivially the best: every metric normalizes to 0.
    assert plan.options[0].score == 0.0


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

    # No warehouse holds 700, and GreenFields only has 500, so only the two
    # vendors that can cover the shortage are ranked.
    assert [(option["rank"], option["reference_id"], option["action"]) for option in body["options"]] == [
        (1, 3, "vendor_purchase"),
        (2, 1, "vendor_purchase"),
    ]
    fastest = body["options"][0]
    assert fastest["label"] == "Bharat Urea Traders"
    assert fastest["score"] == 0.4
    assert fastest["total_cost"] == 19950.0
    assert fastest["normalized_cost"] == 1.0

    cheapest = body["options"][1]
    assert cheapest["label"] == "AgroChem Industries"
    assert cheapest["score"] == 0.6
    assert cheapest["delivery_contribution"] == 0.4
    assert cheapest["carbon_contribution"] == 0.2

    excluded = {(item["action"], item["reference_id"]): item["reason"] for item in body["excluded"]}
    assert excluded[("vendor_purchase", 2)] == "insufficient_quantity"
    assert excluded[("warehouse_transfer", 103)] == "insufficient_quantity"


def test_endpoint_reports_no_feasible_options(seeded_client):
    body = seeded_client.post(
        "/optimize/recovery", json={"shortage_quantity": 5000, "deadline": _deadline()}
    ).json()

    assert body["options"] == []
    assert len(body["excluded"]) == 7  # 3 warehouses + 3 vendors + 1 reroute
    # Warehouses and vendors fail on quantity; the reroute doesn't improve ETA.
    shortage_reasons = {
        item["reason"]
        for item in body["excluded"]
        if item["action"] != "reroute_shipment"
    }
    assert shortage_reasons == {"insufficient_quantity"}
    reroute_items = [
        item for item in body["excluded"] if item["action"] == "reroute_shipment"
    ]
    assert len(reroute_items) == 1


def test_endpoint_reflects_current_database_state(seeded_client):
    request = {"shortage_quantity": 700, "deadline": _deadline()}
    assert [o["reference_id"] for o in seeded_client.post("/optimize/recovery", json=request).json()["options"]] == [3, 1]

    # Failing the winning vendor leaves only AgroChem.
    seeded_client.post("/simulate/vendor-failure", json={"vendor_id": 3})
    assert [o["reference_id"] for o in seeded_client.post("/optimize/recovery", json=request).json()["options"]] == [1]


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
