from pathlib import Path

from pydantic import Field

from app_publisher.enums.apple_crashlytics_platform import AppleCrashlyticsPlatform
from app_publisher.models.strict_model import StrictModel


class AppleCrashlyticsSymbols(StrictModel):
    app_id: str = Field(pattern=r"^1:[0-9]+:ios:[A-Za-z0-9]+$")
    bundle_id: str = Field(min_length=3)
    version: str = Field(min_length=1)
    build_number: str = Field(min_length=1)
    configuration: Path
    archive: Path
    platform: AppleCrashlyticsPlatform = "ios"
    upload_tool_env: str = "FIREBASE_UPLOAD_SYMBOLS_PATH"
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
