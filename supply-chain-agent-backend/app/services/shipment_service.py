"""Shipment service."""

from collections.abc import Sequence

from sqlalchemy import select

from app.models import TERMINAL_STATUSES, Shipment, ShipmentStatus
from app.schemas.shipment import ShipmentCreate, ShipmentStatusUpdate, ShipmentUpdate
from app.services.base import CRUDService
from app.services.errors import NotFoundError
from app.utils import utcnow


class ShipmentService(CRUDService[Shipment, ShipmentCreate, ShipmentUpdate]):
    model = Shipment
    label = "Shipment"

    def list_by_status(self, status: ShipmentStatus) -> Sequence[Shipment]:
        stmt = select(Shipment).where(Shipment.status == status).order_by(Shipment.id)
        return list(self.db.scalars(stmt).all())

    def inbound_to(self, location_id: int) -> Sequence[Shipment]:
        """Active (not yet landed) shipments headed to ``location_id``.

        Arrived *and* cancelled shipments are excluded, so a cancellation
        immediately stops counting towards the destination's inbound supply.
        """
        stmt = (
            select(Shipment)
            .where(
                Shipment.to_id == location_id,
                Shipment.status.notin_(TERMINAL_STATUSES),
            )
            .order_by(Shipment.expected_arrival)
        )
        return list(self.db.scalars(stmt).all())

    def set_status(
        self, shipment_id: int, payload: ShipmentStatusUpdate
    ) -> Shipment:
        """Move a shipment to a new status.

        Arriving stamps ``actual_arrival`` (when not supplied) and computes
        ``delay_hours`` against ``expected_arrival``. Marking it delayed keeps
        whatever explicit ``delay_hours`` the caller provided.
        """
        shipment = self.db.get(Shipment, shipment_id)
        if shipment is None:
            raise NotFoundError(self.label, shipment_id)

        shipment.status = payload.status
        now = utcnow()

        if payload.status is ShipmentStatus.ARRIVED:
            shipment.actual_arrival = payload.actual_arrival or now
            if payload.delay_hours is not None:
                shipment.delay_hours = payload.delay_hours
            elif shipment.expected_arrival is not None:
                overdue = shipment.actual_arrival - shipment.expected_arrival
                shipment.delay_hours = round(max(overdue.total_seconds() / 3600, 0.0), 2)
            else:
                shipment.delay_hours = 0.0
        elif payload.delay_hours is not None:
            shipment.delay_hours = payload.delay_hours

        self.db.commit()
        self.db.refresh(shipment)
        return shipment
