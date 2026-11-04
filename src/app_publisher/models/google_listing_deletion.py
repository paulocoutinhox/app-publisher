from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class GoogleListingDeletion(StrictModel):
    locale: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    confirm_deletion: bool = False
