from pathlib import Path

from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class ScreenshotDesign(StrictModel):
    source: Path
    output: Path
    font: Path
    title: str = Field(min_length=1)
    width: int = Field(ge=400, le=10000)
    height: int = Field(ge=400, le=10000)
    font_size: int = Field(default=72, ge=12, le=300)
    padding: int = Field(default=96, ge=16, le=800)
    foreground: str = "#FFFFFF"
    background: str = "#101820"
