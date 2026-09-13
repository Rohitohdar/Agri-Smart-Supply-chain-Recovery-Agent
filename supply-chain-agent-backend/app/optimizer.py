"""Deterministic recovery optimization — no LLM, no database, no clock.

Given the current situation (a shortage, a deadline, and what is available to
cover it) this module enumerates candidate recovery actions, prices each one,
drops the infeasible ones and ranks what is left. It is pure: the same
:class:`RecoveryState` always produces exactly the same
:class:`RecoveryPlan` — ``now`` is an input, not a call to the clock, and every
iteration runs over an id-sorted sequence.

Candidate model
---------------
* ``warehouse_transfer(warehouse_id, quantity)`` — goods already owned move from
  a warehouse to the dealer, so the cost is freight: the best (fastest)
  available route from that warehouse to the dealer is used for distance, travel
  time and carbon. ``TRANSPORT_COST_PER_KM`` converts distance into cost; goods
  still have to travel, and a vendor's price already includes delivery, so this
  is what makes the two candidate types comparable.
* ``vendor_purchase(vendor_id, quantity)`` — cost is ``price_per_unit *
  quantity``, delivery time is the vendor's ``delivery_hours`` and carbon is
  ``carbon_per_unit * quantity``.

Every candidate is sized to exactly the shortage, so "can it cover the
shortage?" is a stock comparison.

Feasibility
-----------
A candidate survives when it holds enough stock (``available_quantity >=
shortage``) *and* it lands on time (``delivery_hours <= hours_available``).
Warehouses with no available route to the dealer are infeasible too. Everything
that is dropped is reported with the raw numbers that dropped it, under a
stable reason code.

Scoring
-------
Each metric is min-max normalized across the *feasible* candidates only (lower
is better, so the best value becomes 0 and the worst 1; when every candidate
shares a value that metric contributes 0 to everyone). The score is the weighted
sum

    score = 0.4 * cost + 0.4 * delivery_hours + 0.2 * carbon

so a lower score is better and the best possible score is 0. Ties are broken
deterministically by cost, then delivery time, then carbon, then the action name
and its reference id — so the ranking never depends on dictionary or set order.

If only one candidate is feasible it scores 0: normalization is relative to the
options actually available, so a lone option is trivially the best one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Sequence

#: Freight cost per kilometre used to price a warehouse transfer (see the module
#: docstring). A module constant keeps the module pure and deterministic.
TRANSPORT_COST_PER_KM: float = 30.0

_COST_DIGITS = 2
_HOURS_DIGITS = 2
_CARBON_DIGITS = 3
_SCORE_DIGITS = 6


class RecoveryAction(str, enum.Enum):
    """The kinds of recovery action this module can propose."""

    WAREHOUSE_TRANSFER = "warehouse_transfer"
    VENDOR_PURCHASE = "vendor_purchase"
    REROUTE_SHIPMENT = "reroute_shipment"


class ExclusionReason(str, enum.Enum):
    """Why a candidate could not be proposed."""

    NO_AVAILABLE_ROUTE = "no_available_route"
    INSUFFICIENT_QUANTITY = "insufficient_quantity"
    MISSES_DEADLINE = "misses_deadline"


# --- inputs ----------------------------------------------------------------


@dataclass(frozen=True)
class WarehouseSupply:
    """Stock sitting in a warehouse."""

    warehouse_id: int
    name: str
    available_quantity: int


@dataclass(frozen=True)
class SupplierSupply:
    """What an available vendor can sell, and on what terms."""

    supplier_id: int
    name: str
    available_quantity: int
    price_per_unit: float
    delivery_hours: float
    carbon_per_unit: float


@dataclass(frozen=True)
class RouteSupply:
    """An available route between two locations."""

    route_id: int
    from_location_id: int
    to_location_id: int
    distance_km: float
    travel_time_hours: float
    carbon_per_km: float


@dataclass(frozen=True)
class ShipmentSupply:
    """An in-transit or pending shipment that could be rerouted."""

    shipment_id: int
    from_location_id: int
    to_location_id: int
    quantity: int
    expected_arrival: Optional[datetime]
    current_route_id: Optional[int]


@dataclass(frozen=True)
class RecoveryState:
    """Everything the optimizer needs, already narrowed to what is available."""

    shortage_quantity: int
    deadline: datetime
    now: datetime
    destination_location_id: int
    warehouses: Sequence[WarehouseSupply] = ()
    suppliers: Sequence[SupplierSupply] = ()
    routes: Sequence[RouteSupply] = ()
    shipments: Sequence[ShipmentSupply] = ()


@dataclass(frozen=True)
class Weights:
    """Relative importance of each metric (they are not required to sum to 1)."""

    cost: float = 0.4
    delivery_hours: float = 0.4
    carbon: float = 0.2

    def total(self) -> float:
        return self.cost + self.delivery_hours + self.carbon


DEFAULT_WEIGHTS = Weights()


# --- outputs ---------------------------------------------------------------


@dataclass(frozen=True)
class RankedOption:
    """One feasible recovery action, with the numbers behind its rank."""

    rank: int
    action: RecoveryAction
    reference_id: int
    label: str
    quantity: int
    route_id: Optional[int]
    total_cost: float
    total_delivery_hours: float
    total_carbon: float
    normalized_cost: float
    normalized_delivery_hours: float
    normalized_carbon: float
    cost_contribution: float
    delivery_contribution: float
    carbon_contribution: float
    score: float


@dataclass(frozen=True)
class ExcludedCandidate:
    """A candidate that was filtered out, and the numbers that filtered it."""

    action: RecoveryAction
    reference_id: int
    label: str
    quantity: int
    reason: ExclusionReason
    available_quantity: int
    delivery_hours: Optional[float] = None
    hours_available: Optional[float] = None


@dataclass(frozen=True)
class RecoveryPlan:
    """The full result: the ranked feasible options plus what was dropped."""

    shortage_quantity: int
    deadline: datetime
    hours_available: float
    weights: Weights
    options: Sequence[RankedOption]
    excluded: Sequence[ExcludedCandidate]
    #: Reroute candidates that improve delivery time, ranked separately.
    #: These do not add supply — they change when existing supply arrives —
    #: so they are not mixed into the main shortage-filling ranking.
    reroute_options: Sequence[RankedOption] = ()


# --- internals -------------------------------------------------------------


@dataclass
class _Candidate:
    action: RecoveryAction
    reference_id: int
    label: str
    quantity: int
    route_id: Optional[int]
    total_cost: float
    total_delivery_hours: float
    total_carbon: float
    available_quantity: int
    #: For reroute candidates: the current delivery duration in hours.
    #: ``None`` for warehouse_transfer and vendor_purchase.
    current_delivery_hours: Optional[float] = None


def _hours_available(state: RecoveryState) -> float:
    return (state.deadline - state.now).total_seconds() / 3600.0


def _best_route(state: RecoveryState, warehouse_id: int) -> Optional[RouteSupply]:
    """Fastest available route from ``warehouse_id`` to the dealer.

    Fastest first, then shortest, then greenest, then lowest id, so the choice
    is stable when several routes connect the same pair of locations.
    """
    matching = [
        route
        for route in state.routes
        if route.from_location_id == warehouse_id
        and route.to_location_id == state.destination_location_id
    ]
    if not matching:
        return None
    return min(
        matching,
        key=lambda route: (
            route.travel_time_hours,
            route.distance_km,
            route.carbon_per_km,
            route.route_id,
        ),
    )


def _warehouse_candidate(
    state: RecoveryState, warehouse: WarehouseSupply
) -> "_Candidate | ExcludedCandidate":
    route = _best_route(state, warehouse.warehouse_id)
    if route is None:
        return ExcludedCandidate(
            action=RecoveryAction.WAREHOUSE_TRANSFER,
            reference_id=warehouse.warehouse_id,
            label=warehouse.name,
            quantity=state.shortage_quantity,
            reason=ExclusionReason.NO_AVAILABLE_ROUTE,
            available_quantity=warehouse.available_quantity,
        )
    return _Candidate(
        action=RecoveryAction.WAREHOUSE_TRANSFER,
        reference_id=warehouse.warehouse_id,
        label=warehouse.name,
        quantity=state.shortage_quantity,
        route_id=route.route_id,
        total_cost=round(route.distance_km * TRANSPORT_COST_PER_KM, _COST_DIGITS),
        total_delivery_hours=round(route.travel_time_hours, _HOURS_DIGITS),
        total_carbon=round(route.distance_km * route.carbon_per_km, _CARBON_DIGITS),
        available_quantity=warehouse.available_quantity,
    )


def _supplier_candidate(state: RecoveryState, supplier: SupplierSupply) -> _Candidate:
    quantity = state.shortage_quantity
    return _Candidate(
        action=RecoveryAction.VENDOR_PURCHASE,
        reference_id=supplier.supplier_id,
        label=supplier.name,
        quantity=quantity,
        route_id=None,
        total_cost=round(supplier.price_per_unit * quantity, _COST_DIGITS),
        total_delivery_hours=round(supplier.delivery_hours, _HOURS_DIGITS),
        total_carbon=round(supplier.carbon_per_unit * quantity, _CARBON_DIGITS),
        available_quantity=supplier.available_quantity,
    )


def _reroute_candidates(
    state: RecoveryState,
) -> "tuple[list[_Candidate], list[ExcludedCandidate]]":
    """Generate reroute candidates for in-transit shipments to the dealer.

    Each candidate represents putting an existing shipment on a faster
    alternative route. The cost is freight on the new route; delivery hours
    is the new route's travel time. A candidate is only generated when an
    alternative route to the same destination exists.
    """
    candidates: list[_Candidate] = []
    excluded: list[ExcludedCandidate] = []

    for shipment in sorted(state.shipments, key=lambda s: s.shipment_id):
        if shipment.to_location_id != state.destination_location_id:
            continue

        # Compute current delivery duration for comparison.
        current_hours: Optional[float] = None
        if shipment.expected_arrival is not None:
            current_hours = max(
                (shipment.expected_arrival - state.now).total_seconds() / 3600.0, 0.0
            )

        # Find alternative routes to the same destination from any origin.
        alternative_routes = [
            route
            for route in state.routes
            if route.to_location_id == state.destination_location_id
            and route.route_id != shipment.current_route_id
        ]

        if not alternative_routes:
            excluded.append(
                ExcludedCandidate(
                    action=RecoveryAction.REROUTE_SHIPMENT,
                    reference_id=shipment.shipment_id,
                    label=f"Shipment {shipment.shipment_id}",
                    quantity=shipment.quantity,
                    reason=ExclusionReason.NO_AVAILABLE_ROUTE,
                    available_quantity=shipment.quantity,
                    delivery_hours=current_hours,
                    hours_available=round(
                        _hours_available(state), _HOURS_DIGITS
                    ),
                )
            )
            continue

        for route in sorted(
            alternative_routes,
            key=lambda r: (r.travel_time_hours, r.distance_km, r.carbon_per_km, r.route_id),
        ):
            candidates.append(
                _Candidate(
                    action=RecoveryAction.REROUTE_SHIPMENT,
                    reference_id=shipment.shipment_id,
                    label=f"Shipment {shipment.shipment_id}",
                    quantity=shipment.quantity,
                    route_id=route.route_id,
                    total_cost=round(
                        route.distance_km * TRANSPORT_COST_PER_KM, _COST_DIGITS
                    ),
                    total_delivery_hours=round(route.travel_time_hours, _HOURS_DIGITS),
                    total_carbon=round(
                        route.distance_km * route.carbon_per_km, _CARBON_DIGITS
                    ),
                    available_quantity=shipment.quantity,
                    current_delivery_hours=current_hours,
                )
            )

    return candidates, excluded


def _generate(
    state: RecoveryState,
) -> "tuple[list[_Candidate], list[ExcludedCandidate]]":
    """Build every candidate in a deterministic order."""
    candidates: list[_Candidate] = []
    excluded: list[ExcludedCandidate] = []

    for warehouse in sorted(state.warehouses, key=lambda w: w.warehouse_id):
        outcome = _warehouse_candidate(state, warehouse)
        if isinstance(outcome, ExcludedCandidate):
            excluded.append(outcome)
        else:
            candidates.append(outcome)

    for supplier in sorted(state.suppliers, key=lambda s: s.supplier_id):
        candidates.append(_supplier_candidate(state, supplier))

    reroute_cands, reroute_excluded = _reroute_candidates(state)
    candidates.extend(reroute_cands)
    excluded.extend(reroute_excluded)

    return candidates, excluded


def _feasibility(
    candidate: _Candidate, hours_available: float
) -> Optional[ExcludedCandidate]:
    """Return the reason this candidate is infeasible, or ``None``."""
    if candidate.available_quantity < candidate.quantity:
        return ExcludedCandidate(
            action=candidate.action,
            reference_id=candidate.reference_id,
            label=candidate.label,
            quantity=candidate.quantity,
            reason=ExclusionReason.INSUFFICIENT_QUANTITY,
            available_quantity=candidate.available_quantity,
            delivery_hours=candidate.total_delivery_hours,
            hours_available=round(hours_available, _HOURS_DIGITS),
        )
    if candidate.total_delivery_hours > hours_available:
        return ExcludedCandidate(
            action=candidate.action,
            reference_id=candidate.reference_id,
            label=candidate.label,
            quantity=candidate.quantity,
            reason=ExclusionReason.MISSES_DEADLINE,
            available_quantity=candidate.available_quantity,
            delivery_hours=candidate.total_delivery_hours,
            hours_available=round(hours_available, _HOURS_DIGITS),
        )
    # For reroute candidates, the new route must be faster than the current one.
    if (
        candidate.action == RecoveryAction.REROUTE_SHIPMENT
        and candidate.current_delivery_hours is not None
        and candidate.total_delivery_hours >= candidate.current_delivery_hours
    ):
        return ExcludedCandidate(
            action=candidate.action,
            reference_id=candidate.reference_id,
            label=candidate.label,
            quantity=candidate.quantity,
            reason=ExclusionReason.MISSES_DEADLINE,
            available_quantity=candidate.available_quantity,
            delivery_hours=candidate.total_delivery_hours,
            hours_available=round(candidate.current_delivery_hours, _HOURS_DIGITS),
        )
    return None


def _normalize(values: Sequence[float], value: float) -> float:
    """Min-max normalize ``value`` against ``values`` (lower is better)."""
    lowest = min(values)
    highest = max(values)
    if highest == lowest:
        return 0.0
    return (value - lowest) / (highest - lowest)


def _rank(
    candidates: Sequence[_Candidate], weights: Weights
) -> tuple[RankedOption, ...]:
    costs = [candidate.total_cost for candidate in candidates]
    deliveries = [candidate.total_delivery_hours for candidate in candidates]
    carbons = [candidate.total_carbon for candidate in candidates]

    scored: list[RankedOption] = []
    for candidate in candidates:
        normalized_cost = round(_normalize(costs, candidate.total_cost), _SCORE_DIGITS)
        normalized_delivery = round(
            _normalize(deliveries, candidate.total_delivery_hours), _SCORE_DIGITS
        )
        normalized_carbon = round(
            _normalize(carbons, candidate.total_carbon), _SCORE_DIGITS
        )
        cost_contribution = round(weights.cost * normalized_cost, _SCORE_DIGITS)
        delivery_contribution = round(
            weights.delivery_hours * normalized_delivery, _SCORE_DIGITS
        )
        carbon_contribution = round(weights.carbon * normalized_carbon, _SCORE_DIGITS)
        scored.append(
            RankedOption(
                rank=0,
                action=candidate.action,
                reference_id=candidate.reference_id,
                label=candidate.label,
                quantity=candidate.quantity,
                route_id=candidate.route_id,
                total_cost=candidate.total_cost,
                total_delivery_hours=candidate.total_delivery_hours,
                total_carbon=candidate.total_carbon,
                normalized_cost=normalized_cost,
                normalized_delivery_hours=normalized_delivery,
                normalized_carbon=normalized_carbon,
                cost_contribution=cost_contribution,
                delivery_contribution=delivery_contribution,
                carbon_contribution=carbon_contribution,
                score=round(
                    cost_contribution + delivery_contribution + carbon_contribution,
                    _SCORE_DIGITS,
                ),
            )
        )

    # Lower score wins; the rest is a stable, documented tie-break.
    scored.sort(
        key=lambda option: (
            option.score,
            option.total_cost,
            option.total_delivery_hours,
            option.total_carbon,
            option.action.value,
            option.reference_id,
        )
    )
    return tuple(replace(option, rank=index + 1) for index, option in enumerate(scored))


# --- public API ------------------------------------------------------------


def evaluate_recovery(
    state: RecoveryState, weights: Weights = DEFAULT_WEIGHTS
) -> RecoveryPlan:
    """Rank every feasible candidate and report the excluded ones."""
    hours_available = _hours_available(state)

    if state.shortage_quantity <= 0:
        return RecoveryPlan(
            shortage_quantity=state.shortage_quantity,
            deadline=state.deadline,
            hours_available=round(hours_available, _HOURS_DIGITS),
            weights=weights,
            options=(),
            excluded=(),
            reroute_options=(),
        )

    candidates, excluded = _generate(state)

    # Separate reroute candidates from shortage-filling candidates.
    reroute_cands: list[_Candidate] = []
    shortage_cands: list[_Candidate] = []
    for candidate in candidates:
        if candidate.action == RecoveryAction.REROUTE_SHIPMENT:
            reroute_cands.append(candidate)
        else:
            shortage_cands.append(candidate)

    # Rank shortage-filling candidates.
    feasible: list[_Candidate] = []
    for candidate in shortage_cands:
        rejection = _feasibility(candidate, hours_available)
        if rejection is None:
            feasible.append(candidate)
        else:
            excluded.append(rejection)

    # Rank reroute candidates separately.  A reroute is feasible only when the
    # new route delivers faster than the current ETA (the shipment is delayed
    # or on a suboptimal path).
    reroute_feasible: list[_Candidate] = []
    for candidate in reroute_cands:
        # Always check deadline feasibility.
        rejection = _feasibility(candidate, hours_available)
        if rejection is not None:
            excluded.append(rejection)
            continue
        # Reroute must improve on the current ETA.
        if (
            candidate.current_delivery_hours is not None
            and candidate.total_delivery_hours >= candidate.current_delivery_hours
        ):
            excluded.append(
                ExcludedCandidate(
                    action=candidate.action,
                    reference_id=candidate.reference_id,
                    label=candidate.label,
                    quantity=candidate.quantity,
                    reason=ExclusionReason.MISSES_DEADLINE,
                    available_quantity=candidate.available_quantity,
                    delivery_hours=candidate.total_delivery_hours,
                    hours_available=round(candidate.current_delivery_hours, _HOURS_DIGITS),
                )
            )
            continue
        reroute_feasible.append(candidate)

    excluded.sort(key=lambda item: (item.action.value, item.reference_id))
    return RecoveryPlan(
        shortage_quantity=state.shortage_quantity,
        deadline=state.deadline,
        hours_available=round(hours_available, _HOURS_DIGITS),
        weights=weights,
        options=_rank(feasible, weights),
        excluded=tuple(excluded),
        reroute_options=_rank(reroute_feasible, weights),
    )


def optimize_recovery(
    state: RecoveryState, weights: Weights = DEFAULT_WEIGHTS
) -> list[RankedOption]:
    """Return feasible recovery actions, best first.

    The required entry point: a ranked list of feasible options only. Use
    :func:`evaluate_recovery` when the excluded candidates matter too.
    """
    return list(evaluate_recovery(state, weights).options)
