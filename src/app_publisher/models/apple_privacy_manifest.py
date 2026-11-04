import re
from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.models.privacy_accessed_api import PrivacyAccessedAPI
from app_publisher.models.privacy_collected_data import PrivacyCollectedData
from app_publisher.models.strict_model import StrictModel


class ApplePrivacyManifest(StrictModel):
    output: Path
    tracking: bool = False
    tracking_domains: list[str] = Field(default_factory=list)
    collected_data: list[PrivacyCollectedData] = Field(default_factory=list)
    accessed_apis: list[PrivacyAccessedAPI] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_privacy(self) -> "ApplePrivacyManifest":
        if self.tracking and not self.tracking_domains:
            raise ValueError("Tracking requires declared tracking domains")
        if not self.tracking and self.tracking_domains:
            raise ValueError("Tracking domains must not be declared when tracking is false")
        if not self.tracking and any(item.tracking for item in self.collected_data):
            raise ValueError("Tracking data types require tracking to be enabled")
        if any(
            re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+", domain) is None
            for domain in self.tracking_domains
        ):
            raise ValueError("Tracking domains must be domain names without URL schemes or paths")
        categories = [item.category for item in self.accessed_apis]
        if len(categories) != len(set(categories)):
            raise ValueError("Privacy required-reason API categories must be unique")
        data_types = [item.data_type for item in self.collected_data]
        if len(data_types) != len(set(data_types)):
            raise ValueError("Privacy collected data types must be unique")
        return self
