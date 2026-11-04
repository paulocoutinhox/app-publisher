from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppDetails(StrictModel):
    id: str = Field(min_length=2)
    default_locale: str = "en-US"
    paid: bool
