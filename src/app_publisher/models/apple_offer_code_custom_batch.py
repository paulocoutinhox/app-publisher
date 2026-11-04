from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleOfferCodeCustomBatch(StrictModel):
    custom_code: str = Field(pattern=r"^[A-Za-z0-9]{1,64}$")
    number_of_codes: int = Field(ge=1, le=25000)
    expiration_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    confirm_creation: bool = False
