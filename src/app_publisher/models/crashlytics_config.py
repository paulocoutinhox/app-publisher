from pydantic import Field, model_validator

from app_publisher.models.android_crashlytics_symbols import AndroidCrashlyticsSymbols
from app_publisher.models.apple_crashlytics_symbols import AppleCrashlyticsSymbols
from app_publisher.models.strict_model import StrictModel


class CrashlyticsConfig(StrictModel):
    apple: list[AppleCrashlyticsSymbols] = Field(default_factory=list)
    android: list[AndroidCrashlyticsSymbols] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_apps(self) -> "CrashlyticsConfig":
        identities = [item.app_id for item in self.apple] + [item.app_id for item in self.android]

        if not identities or len(identities) != len(set(identities)):
            raise ValueError("Crashlytics configuration requires unique application IDs")

        return self
