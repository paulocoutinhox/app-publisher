from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleAppPrice(StrictModel):
    price_point_id: str = Field(min_length=1)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
