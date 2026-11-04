from pydantic import Field, ValidationInfo, field_validator, model_validator

from app_publisher.enums.screenshot_action_kind import ScreenshotActionKind
from app_publisher.enums.screenshot_orientation import ScreenshotOrientation
from app_publisher.enums.screenshot_remote_button import ScreenshotRemoteButton
from app_publisher.models.strict_model import StrictModel


class ScreenshotAction(StrictModel):
    kind: ScreenshotActionKind
    value: str | None = None
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    end_x: int | None = Field(default=None, ge=0)
    end_y: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=1, le=60000)
    angle: int | None = Field(default=None, ge=0, le=180)
    scale: float | None = Field(default=None, gt=0, le=10)
    seconds: float | None = Field(default=None, ge=0, le=60)

    @field_validator("value")
    @classmethod
    def normalize_option(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None

        if info.data.get("kind") == "remote":
            try:
                return ScreenshotRemoteButton(value).value
            except ValueError:
                raise ValueError("tvOS remote action is invalid") from None

        if info.data.get("kind") == "rotate":
            try:
                return ScreenshotOrientation(value).value
            except ValueError:
                raise ValueError("iOS orientation is invalid") from None

        return value

    @model_validator(mode="after")
    def validate_arguments(self) -> "ScreenshotAction":
        fields = {
            key
            for key in ("value", "x", "y", "end_x", "end_y", "duration_ms", "seconds", "angle", "scale")
            if getattr(self, key) is not None
        }
        required = {
            "tap": {"x", "y"},
            "swipe": {"x", "y", "end_x", "end_y", "duration_ms"},
            "text": {"value"},
            "launch": {"value"},
            "terminate": {"value"},
            "open_url": {"value"},
            "wait": {"seconds"},
            "tap_element": {"value"},
            "wait_element": {"value"},
            "hinge": {"angle"},
            "remote": {"value"},
            "rotate": {"value"},
            "shake": set(),
            "pinch": {"x", "y", "scale"},
        }[self.kind]
        if fields != required:
            raise ValueError(f"Screenshot action {self.kind} requires exactly {', '.join(sorted(required))}")
        return self
