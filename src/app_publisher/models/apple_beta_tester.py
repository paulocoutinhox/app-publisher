from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleBetaTester(StrictModel):
    email: str = Field(min_length=3)
    first_name: str | None = None
    last_name: str | None = None
    invite: bool = False
