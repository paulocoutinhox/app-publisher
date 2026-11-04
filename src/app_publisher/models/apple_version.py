from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.enums.apple_platform import ApplePlatform
from app_publisher.enums.apple_release_type import AppleReleaseType
from app_publisher.models.apple_beta_distribution import AppleBetaDistribution
from app_publisher.models.apple_build import AppleBuild
from app_publisher.models.strict_model import StrictModel


class AppleVersion(StrictModel):
    platform: ApplePlatform
    version: str = Field(min_length=1)
    release_type: AppleReleaseType = "MANUAL"
    artifact: Path | None = None
    build_number: str | None = None
    build: AppleBuild | None = None
    beta: AppleBetaDistribution | None = None
    phased_release: bool = False
    manual_release: bool = False
    earliest_release_date: str | None = None

    @model_validator(mode="after")
    def validate_artifact(self) -> "AppleVersion":
        if self.artifact is not None and self.build_number is None:
            raise ValueError("Apple build uploads require an explicit build_number")
        if self.earliest_release_date is not None:
            from datetime import datetime

            if self.release_type != "SCHEDULED":
                raise ValueError("Apple earliest_release_date requires release_type SCHEDULED")
            try:
                scheduled = datetime.fromisoformat(self.earliest_release_date.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("Apple earliest_release_date must be a valid RFC 3339 timestamp") from error
            if scheduled.tzinfo is None or scheduled.utcoffset() is None:
                raise ValueError("Apple earliest_release_date requires an explicit timezone")
        return self
