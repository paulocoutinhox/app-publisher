import re

from pydantic import Field, model_validator

from app_publisher.models.strict_model import StrictModel


class GoogleTesterGroup(StrictModel):
    track: str = Field(min_length=1)
    google_groups: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_groups(self) -> "GoogleTesterGroup":
        if len(set(self.google_groups)) != len(self.google_groups) or any(
            re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", group) is None for group in self.google_groups
        ):
            raise ValueError("Google tester groups must contain unique valid email addresses")
        return self
