"""Request and response schemas for the recovery optimizer.

The response mirrors the optimizer's dataclasses field for field, so every
number behind a rank is visible: the raw metrics, their min-max normalized
values, the weighted contribution each one made and the final score.
"""

from datetime import datetime

from pydantic import Field

from app.optimizer import (
    ExclusionReason,
    RankedOption,
    RecoveryAction,
    RecoveryPlan,
    Weights,
)
from app.schemas.common import MAX_QUANTITY, ORMModel


class RecoveryOptimizeRequest(ORMModel):
    """Body for ``POST /optimize/recovery``."""

    shortage_quantity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
        description="Units still needed; every candidate is sized to exactly this",
    )
    deadline: datetime = Field(description="Latest acceptable arrival (naive UTC)")


class WeightsRead(ORMModel):
    """The weights the score was computed with."""

    cost: float
    delivery_hours: float
    carbon: float


class RankedOptionRead(ORMModel):
    """One feasible recovery action and the numbers behind its rank."""

    rank: int
    action: RecoveryAction
    reference_id: int
    label: str
    quantity: int
    route_id: int | None = None
    #: Raw metrics.
    total_cost: float
    total_delivery_hours: float
    total_carbon: float
    #: Metrics min-max normalized across the feasible candidates (lower better).
    normalized_cost: float
    normalized_delivery_hours: float
    normalized_carbon: float
    #: Weighted contribution of each normalized metric to the score.
    cost_contribution: float
    delivery_contribution: float
    carbon_contribution: float
    score: float
    #: True when this was the only candidate that survived filtering; the score
    #: of 0 is not a comparative rank and should not be displayed as one.
    single_feasible_option: bool = False

    @classmethod
    def from_option(cls, option: RankedOption) -> "RankedOptionRead":
        return cls(
            rank=option.rank,
            action=option.action,
            reference_id=option.reference_id,
            label=option.label,
            quantity=option.quantity,
            route_id=option.route_id,
            total_cost=option.total_cost,
            total_delivery_hours=option.total_delivery_hours,
            total_carbon=option.total_carbon,
            normalized_cost=option.normalized_cost,
            normalized_delivery_hours=option.normalized_delivery_hours,
            normalized_carbon=option.normalized_carbon,
            cost_contribution=option.cost_contribution,
            delivery_contribution=option.delivery_contribution,
            carbon_contribution=option.carbon_contribution,
            score=option.score,
            single_feasible_option=option.single_feasible_option,
        )


class ExcludedOptionRead(ORMModel):
    """A candidate that was filtered out, and the numbers that filtered it."""

    action: RecoveryAction
    reference_id: int
    label: str
    quantity: int
    reason: ExclusionReason
    available_quantity: int
    delivery_hours: float | None = None
    hours_available: float | None = None


class RecoveryPlanResponse(ORMModel):
    """Ranked feasible options plus the candidates that did not make it."""

    shortage_quantity: int
    deadline: datetime
    hours_available: float
    weights: WeightsRead
    options: list[RankedOptionRead] = Field(default_factory=list)
    excluded: list[ExcludedOptionRead] = Field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: RecoveryPlan) -> "RecoveryPlanResponse":
        weights: Weights = plan.weights
        return cls(
            shortage_quantity=plan.shortage_quantity,
            deadline=plan.deadline,
            hours_available=plan.hours_available,
            weights=WeightsRead(
                cost=weights.cost,
                delivery_hours=weights.delivery_hours,
                carbon=weights.carbon,
            ),
            options=[RankedOptionRead.from_option(option) for option in plan.options],
            excluded=[
                ExcludedOptionRead(
                    action=item.action,
                    reference_id=item.reference_id,
                    label=item.label,
                    quantity=item.quantity,
                    reason=item.reason,
                    available_quantity=item.available_quantity,
                    delivery_hours=item.delivery_hours,
                    hours_available=item.hours_available,
                )
                for item in plan.excluded
            ],
        )
