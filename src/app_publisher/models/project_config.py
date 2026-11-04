from typing import Literal

from pydantic import Field, model_validator

from app_publisher.models.app_details import AppDetails
from app_publisher.models.apple_config import AppleConfig
from app_publisher.models.firebase_config import FirebaseConfig
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.locale_config import LocaleConfig
from app_publisher.models.publication_config import PublicationConfig
from app_publisher.models.strict_model import StrictModel


class ProjectConfig(StrictModel):
    schema_version: Literal[1]
    app: AppDetails
    publication: PublicationConfig = Field(default_factory=PublicationConfig)
    apple: AppleConfig | None = None
    google: GoogleConfig | None = None
    firebase: FirebaseConfig | None = None
    locales: dict[str, LocaleConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_configuration(self) -> "ProjectConfig":
        if self.apple is None and self.google is None and self.firebase is None:
            raise ValueError("At least one provider must be configured")
        if self.app.default_locale not in self.locales:
            raise ValueError("The default locale is not configured")
        return self
