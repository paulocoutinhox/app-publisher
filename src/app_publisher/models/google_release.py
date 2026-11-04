from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.enums.google_release_status import GoogleReleaseStatus
from app_publisher.models.android_build import AndroidBuild
from app_publisher.models.google_country_targeting import GoogleCountryTargeting
from app_publisher.models.google_deobfuscation_file import GoogleDeobfuscationFile
from app_publisher.models.strict_model import StrictModel


class GoogleRelease(StrictModel):
    track: str = "internal"
    status: GoogleReleaseStatus = "draft"
    version_codes: list[str] = Field(default_factory=list)
    rollout_fraction: float | None = Field(default=None, gt=0, lt=1)
    artifact: Path | None = None
    confirm_track_replacement: bool = False
    build: AndroidBuild | None = None
    deobfuscation_files: list[GoogleDeobfuscationFile] = Field(default_factory=list)
    testers: list[str] = Field(default_factory=list)
    name: str | None = None
    in_app_update_priority: int | None = Field(default=None, ge=0, le=5)
    country_targeting: GoogleCountryTargeting | None = None

    @model_validator(mode="after")
    def valid_rollout(self) -> "GoogleRelease":
        if self.status == "inProgress" and self.rollout_fraction is None:
            raise ValueError("inProgress releases require rollout_fraction")
        if self.country_targeting is not None and (self.track != "production" or self.status != "inProgress"):
            raise ValueError("Country targeting requires an inProgress production release")
        if self.status != "inProgress" and self.rollout_fraction is not None:
            raise ValueError("rollout_fraction is only valid with inProgress")
        return self
