"""Demand read model.

``shortage``, ``on_hand_shortfall``, ``constraint_violations`` and
``constraint_violated`` are computed from the other fields, so the payload can
never disagree with itself.

Coverage definition (matches the agent's own ``verify_state`` tool):
    covered = on_hand + sum(inbound shipments arriving at or before the deadline)
    constraint_violated = (covered < required) OR any active shipment is late

``shortage`` / ``on_hand_shortfall`` report the raw on-hand gap
(required - on_hand, floored at 0) as a secondary informational stat. They do
*not* drive ``constraint_violated`` — a dealer whose inbound shipments already
cover the requirement is healthy even while on-hand stock is below the target.
"""

from datetime import datetime

from pydantic import Field, computed_field

from app.models import Dealer, Shipment
from app.schemas.common import ORMModel
from app.schemas.shipment import ShipmentRead


class DemandResponse(ORMModel):
    """What one dealer needs, what it has, and whether it is on track."""

    dealer_id: int
    dealer_name: str
    location: str
    required_quantity: int
    #: Stock on hand right now. In-flight shipments are *not* counted here; see
    #: ``active_shipment_quantity``.
    available_quantity: int
    deadline: datetime
    #: Shipments inbound to this dealer that have not landed: neither ARRIVED
    #: nor CANCELLED.
    active_shipments: list[ShipmentRead] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def shortage(self) -> int:
        """On-hand shortfall: ``required_quantity - available_quantity``, floored at zero.

        This is a secondary informational stat. It does *not* drive
        ``constraint_violated``; use ``on_hand_shortfall`` for the same value
        with a self-documenting name.
        """
        return max(self.required_quantity - self.available_quantity, 0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def on_hand_shortfall(self) -> int:
        """Alias for ``shortage``: how many units are missing from on-hand stock.

        Kept separate from ``constraint_violated`` so callers can display the
        raw on-hand gap without conflating it with the coverage verdict.
        """
        return self.shortage

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_shipment_quantity(self) -> int:
        """Total quantity of the in-flight shipments."""
        return sum(shipment.quantity for shipment in self.active_shipments)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def _inbound_on_time(self) -> int:
        """Units from active shipments whose ETA is at or before the deadline."""
        total = 0
        for shipment in self.active_shipments:
            arrived = shipment.expected_arrival
            if arrived is not None and arrived <= self.deadline:
                total += shipment.quantity
        return total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def covered_quantity(self) -> int:
        """On-hand stock plus inbound units arriving by the deadline.

        This is the same coverage rule the agent's ``verify_state`` tool uses,
        so the status badge and the agent's own verdict always agree.
        """
        return self.available_quantity + self._inbound_on_time

    @computed_field  # type: ignore[prop-decorator]
    @property
    def constraint_violations(self) -> list[str]:
        """Human-readable reasons the demand cannot be met as things stand.

        A coverage shortfall is reported when on_hand + inbound_by_deadline
        falls below the requirement. Late shipments are reported individually.
        On-hand-only shortfalls are *not* violations when inbound supply already
        covers the gap.
        """
        violations: list[str] = []
        if self.covered_quantity < self.required_quantity:
            coverage_gap = self.required_quantity - self.covered_quantity
            violations.append(
                f"coverage shortfall of {coverage_gap} units "
                f"({self.covered_quantity} of {self.required_quantity} covered "
                f"by on-hand + inbound-by-deadline)"
            )
        for shipment in self.active_shipments:
            arrived = shipment.expected_arrival
            if arrived is not None and arrived > self.deadline:
                late_hours = (arrived - self.deadline).total_seconds() / 3600
                violations.append(
                    f"shipment {shipment.id} is expected {late_hours:.1f} h "
                    f"after the deadline"
                )
        return violations

    @computed_field  # type: ignore[prop-decorator]
    @property
    def constraint_violated(self) -> bool:
        """True when coverage (on_hand + inbound_by_deadline) is short, or a shipment is late."""
        return bool(self.constraint_violations)

    @classmethod
    def from_dealer(cls, dealer: Dealer, shipments: list[Shipment]) -> "DemandResponse":
        return cls(
            dealer_id=dealer.id,
            dealer_name=dealer.name,
            location=dealer.location,
            required_quantity=dealer.required_quantity,
            available_quantity=dealer.current_inventory,
            deadline=dealer.deadline,
            active_shipments=[ShipmentRead.model_validate(s) for s in shipments],
        )
