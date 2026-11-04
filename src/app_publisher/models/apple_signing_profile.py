from pathlib import Path

from pydantic import Field

from app_publisher.enums.apple_profile_type import AppleProfileType
from app_publisher.models.strict_model import StrictModel


class AppleSigningProfile(StrictModel):
    name: str = Field(min_length=1)
    profile_type: AppleProfileType
    certificate_ids: list[str] = Field(min_length=1)
    device_ids: list[str] = Field(default_factory=list)
    output: Path
    create_if_missing: bool = False
