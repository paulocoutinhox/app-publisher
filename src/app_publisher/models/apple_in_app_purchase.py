from pydantic import Field

from app_publisher.enums.apple_purchase_type import ApplePurchaseType
from app_publisher.models.apple_review_screenshot import AppleReviewScreenshot
from app_publisher.models.product_localization import ProductLocalization
from app_publisher.models.strict_model import StrictModel


class AppleInAppPurchase(StrictModel):
    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purchase_type: ApplePurchaseType
    review_note: str = ""
    available_in_all_territories: bool = True
    localizations: dict[str, ProductLocalization] = Field(default_factory=dict)
    review_screenshot: AppleReviewScreenshot | None = None
