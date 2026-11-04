from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class ProductLocalization(StrictModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=55)
