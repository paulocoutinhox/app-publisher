from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class GoogleSubscriptionOfferDeletion(StrictModel):
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.]{0,39}$")
    base_plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    offer_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    confirm_deletion: bool = False
