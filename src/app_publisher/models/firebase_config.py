from pydantic import Field

from app_publisher.models.crashlytics_config import CrashlyticsConfig
from app_publisher.models.firebase_application import FirebaseApplication
from app_publisher.models.strict_model import StrictModel


class FirebaseConfig(StrictModel):
    project_id: str = Field(min_length=6)
    create_if_missing: bool = False
    crashlytics: CrashlyticsConfig | None = None
    apple_apps: list[FirebaseApplication] = Field(default_factory=list)
    android_apps: list[FirebaseApplication] = Field(default_factory=list)
