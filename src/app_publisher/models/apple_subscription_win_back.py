from pydantic import Field

from app_publisher.enums.apple_offer_priority import AppleOfferPriority
from app_publisher.models.strict_model import StrictModel


class AppleSubscriptionWinBack(StrictModel):
    reference_name: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    duration: str = Field(min_length=1)
    offer_mode: str = Field(min_length=1)
    period_count: int = Field(ge=1)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: AppleOfferPriority
    promotion_intent: str = Field(min_length=1)
    price_point_ids: list[str] = Field(min_length=1)
