from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.models.strict_model import StrictModel


class AndroidCrashlyticsSymbols(StrictModel):
    app_id: str = Field(pattern=r"^1:[0-9]+:android:[A-Za-z0-9]+$")
    package_name: str = Field(min_length=3)
    version_code: int = Field(ge=1, le=2_100_000_000)
    configuration: Path
    artifact: Path
    gradle_wrapper: Path
    variant: str = Field(pattern=r"^[a-z][a-zA-Z0-9]*$")
    bundletool_env: str = "BUNDLETOOL_PATH"
    upload_mapping: bool = True
    upload_native: bool = False
    timeout_seconds: int = Field(default=900, ge=1, le=7200)

    @model_validator(mode="after")
    def require_upload(self) -> "AndroidCrashlyticsSymbols":
        if not self.upload_mapping and not self.upload_native:
            raise ValueError("Select at least one Android Crashlytics symbol upload")

        return self
