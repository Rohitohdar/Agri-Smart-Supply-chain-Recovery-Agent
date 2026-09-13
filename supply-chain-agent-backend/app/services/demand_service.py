"""Demand service: the dealer's requirement plus its in-flight shipments."""

from sqlalchemy.orm import Session

from app.models import Dealer, Shipment
from app.services.dealer_service import DealerService
from app.services.errors import NotFoundError
from app.services.shipment_service import ShipmentService


class DemandService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.dealers = DealerService(db)
        self.shipments = ShipmentService(db)

    def dealer_or_default(self, dealer_id: int | None = None) -> Dealer:
        """The requested dealer, or the lowest-id dealer when none is given."""
        if dealer_id is not None:
            return self.dealers.get_or_404(dealer_id)
        dealers = self.dealers.list(limit=1)
        if not dealers:
            raise NotFoundError(
                "Dealer",
                "default",
                detail="No dealers exist; create one or POST /admin/reset",
            )
        return dealers[0]

    def active_shipments(self, dealer_id: int) -> list[Shipment]:
        """Shipments inbound to the dealer that have not arrived yet."""
        return list(self.shipments.inbound_to(dealer_id))
