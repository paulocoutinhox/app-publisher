from pydantic import Field

from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionGroup(StrictModel):
    reference_name: str = Field(min_length=1)
    localizations: dict[str, str] = Field(default_factory=dict)
    subscriptions: list[AppleSubscription] = Field(default_factory=list)
