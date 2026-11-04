from pydantic import Field

from app_publisher.enums.google_offer_state import GoogleOfferState
from app_publisher.models.strict_model import StrictModel


class GoogleSubscriptionOffer(StrictModel):
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.]{0,39}$")
    base_plan_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    regions_version: str = Field(min_length=1)
    update_mask: list[str] = Field(min_length=1)
    data: dict[str, object] = Field(min_length=1)
    state: GoogleOfferState = "DRAFT"
