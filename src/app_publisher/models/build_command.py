from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class BuildCommand(StrictModel):
    executable: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)
