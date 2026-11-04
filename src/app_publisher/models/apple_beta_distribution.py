from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleBetaDistribution(StrictModel):
    group_ids: list[str] = Field(min_length=1)
    notify: bool = False
