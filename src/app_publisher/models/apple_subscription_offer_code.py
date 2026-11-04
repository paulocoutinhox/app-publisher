from pydantic import Field

from app_publisher.enums.apple_offer_mode import AppleOfferMode
from app_publisher.models.apple_offer_code_custom_batch import AppleOfferCodeCustomBatch
from app_publisher.models.apple_offer_code_one_time_batch import AppleOfferCodeOneTimeBatch
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionOfferCode(StrictModel):
    name: str = Field(min_length=1)
    duration: str = Field(min_length=1)
    number_of_periods: int = Field(ge=1)
    offer_mode: AppleOfferMode
    customer_eligibilities: list[str] = Field(min_length=1)
    custom_code_batches: list[AppleOfferCodeCustomBatch] = Field(default_factory=list)
    one_time_code_batches: list[AppleOfferCodeOneTimeBatch] = Field(default_factory=list)
    offer_eligibility: str = Field(min_length=1)
    price_point_ids: list[str] = Field(min_length=1)
    target_subscription_plan_type: str | None = None
