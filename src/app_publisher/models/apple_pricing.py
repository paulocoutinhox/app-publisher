from pydantic import Field

from app_publisher.models.apple_app_price import AppleAppPrice
from app_publisher.models.strict_model import StrictModel


class ApplePricing(StrictModel):
    base_territory: str = Field(pattern=r"^[A-Z]{3}$")
    prices: list[AppleAppPrice] = Field(min_length=1)
    confirm_price_changes: bool = False
