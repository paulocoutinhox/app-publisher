from pydantic import Field

from app_publisher.enums.google_one_time_offer_state import GoogleOneTimeOfferState
from app_publisher.models.strict_model import StrictModel


class GoogleOneTimeOffer(StrictModel):
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.]{0,39}$")
    purchase_option_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    offer_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    regions_version: str = Field(min_length=1)
    update_mask: list[str] = Field(min_length=1)
    data: dict[str, object] = Field(min_length=1)
    state: GoogleOneTimeOfferState = "DRAFT"
