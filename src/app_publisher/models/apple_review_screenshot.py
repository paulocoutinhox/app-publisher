from pathlib import Path

from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleReviewScreenshot(StrictModel):
    path: Path
    confirm_replacement: bool = False
    timeout_seconds: int = Field(default=300, ge=1, le=1800)
