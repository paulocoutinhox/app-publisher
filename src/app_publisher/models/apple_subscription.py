from pydantic import Field, model_validator

from app_publisher.enums.apple_subscription_period import AppleSubscriptionPeriod
from app_publisher.models.apple_review_screenshot import AppleReviewScreenshot
from app_publisher.models.apple_subscription_availability import AppleSubscriptionAvailability
from app_publisher.models.apple_subscription_introductory_offer import AppleSubscriptionIntroductoryOffer
from app_publisher.models.apple_subscription_offer_code import AppleSubscriptionOfferCode
from app_publisher.models.apple_subscription_price import AppleSubscriptionPrice
from app_publisher.models.apple_subscription_promotion import AppleSubscriptionPromotion
from app_publisher.models.apple_subscription_win_back import AppleSubscriptionWinBack
from app_publisher.models.product_localization import ProductLocalization
from app_publisher.models.strict_model import StrictModel


class AppleSubscription(StrictModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    period: AppleSubscriptionPeriod
    group_level: int = Field(default=1, ge=1)
    family_sharable: bool = False
    review_note: str | None = None
    localizations: dict[str, ProductLocalization] = Field(default_factory=dict)
    review_screenshot: AppleReviewScreenshot | None = None
    prices: list[AppleSubscriptionPrice] = Field(default_factory=list)
    availability: list[AppleSubscriptionAvailability] = Field(default_factory=list)
    promotional_offers: list[AppleSubscriptionPromotion] = Field(default_factory=list)
    win_back_offers: list[AppleSubscriptionWinBack] = Field(default_factory=list)
    introductory_offers: list[AppleSubscriptionIntroductoryOffer] = Field(default_factory=list)
    offer_codes: list[AppleSubscriptionOfferCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_plan_availability(self) -> "AppleSubscription":
        plans = [item.plan_type for item in self.availability]

        if len(plans) != len(set(plans)):
            raise ValueError("Subscription plan availability must have unique plan types")

        return self
