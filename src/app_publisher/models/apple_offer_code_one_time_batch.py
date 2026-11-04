from pydantic import Field

from app_publisher.enums.apple_environment import AppleEnvironment
from app_publisher.models.strict_model import StrictModel


class AppleOfferCodeOneTimeBatch(StrictModel):
    number_of_codes: int = Field(ge=500, le=25000)
    expiration_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    environment: AppleEnvironment | None = None
    confirm_creation: bool = False
