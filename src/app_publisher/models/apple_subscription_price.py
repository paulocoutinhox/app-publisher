from pydantic import Field

from app_publisher.enums.apple_subscription_plan_type import AppleSubscriptionPlanType
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionPrice(StrictModel):
    price_point_id: str = Field(min_length=1)
    plan_type: AppleSubscriptionPlanType = AppleSubscriptionPlanType.UPFRONT
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    preserve_current_price: bool = True
