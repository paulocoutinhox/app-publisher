from pydantic import Field

from app_publisher.enums.apple_offer_mode import AppleOfferMode
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionPromotion(StrictModel):
    name: str = Field(min_length=1)
    duration: str = Field(min_length=1)
    number_of_periods: int = Field(ge=1)
    offer_mode: AppleOfferMode
    target_subscription_plan_type: str | None = None
    price_point_ids: list[str] = Field(min_length=1)
