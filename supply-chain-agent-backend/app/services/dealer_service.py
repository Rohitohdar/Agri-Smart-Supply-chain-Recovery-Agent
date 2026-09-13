"""Dealer service."""

from app.models import Dealer
from app.schemas.dealer import DealerCreate, DealerUpdate
from app.services.base import CRUDService


class DealerService(CRUDService[Dealer, DealerCreate, DealerUpdate]):
    model = Dealer
    label = "Dealer"

    def shortfall(self, dealer_id: int) -> int:
        """Units the dealer still needs to hit ``required_quantity``."""
        return self.get_or_404(dealer_id).shortfall

    def update_inventory(self, dealer_id: int, current_inventory: int) -> Dealer:
        """Set the dealer's on-hand stock."""
        dealer = self.get_or_404(dealer_id)
        dealer.current_inventory = max(int(current_inventory), 0)
        self.db.commit()
        self.db.refresh(dealer)
        return dealer
