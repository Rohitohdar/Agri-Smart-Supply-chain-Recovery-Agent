"""Demand read model.

``shortage``, ``constraint_violations`` and ``constraint_violated`` are computed
from the other fields, so the payload can never disagree with itself.
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
        """``required_quantity - available_quantity``, floored at zero."""
        return max(self.required_quantity - self.available_quantity, 0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_shipment_quantity(self) -> int:
        """Total quantity of the in-flight shipments."""
        return sum(shipment.quantity for shipment in self.active_shipments)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def constraint_violations(self) -> list[str]:
        """Human-readable reasons the demand cannot be met as things stand."""
        violations: list[str] = []
        if self.shortage > 0:
            violations.append(
                f"shortage of {self.shortage} units "
                f"({self.available_quantity} of {self.required_quantity} on hand)"
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
        """True when there is a shortage or an in-flight shipment lands late."""
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
