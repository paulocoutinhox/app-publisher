from pydantic import Field, field_validator

from app_publisher.enums.apple_subscription_plan_type import AppleSubscriptionPlanType
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionAvailability(StrictModel):
    plan_type: AppleSubscriptionPlanType
    territories: list[str] = Field(min_length=1)
    available_in_new_territories: bool = False
    confirm_territory_changes: bool = False

    @field_validator("territories")
    @classmethod
    def unique_territories(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Subscription availability territories must be unique")

        return value
