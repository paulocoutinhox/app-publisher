from pathlib import Path

from pydantic import Field

from app_publisher.models.screenshot_action import ScreenshotAction
from app_publisher.models.strict_model import StrictModel


class ScreenshotScene(StrictModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    output: Path
    delay_seconds: float = Field(default=2, ge=0, le=60)
    actions: list[ScreenshotAction] = Field(default_factory=list)
