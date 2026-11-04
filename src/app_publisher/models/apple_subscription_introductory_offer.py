from pydantic import Field

from app_publisher.enums.apple_offer_mode import AppleOfferMode
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionIntroductoryOffer(StrictModel):
    territory: str = Field(pattern=r"^[A-Z]{3}$")
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    duration: str = Field(min_length=1)
    number_of_periods: int = Field(ge=1)
    offer_mode: AppleOfferMode
    price_point_id: str = Field(min_length=1)
    target_subscription_plan_type: str | None = None
