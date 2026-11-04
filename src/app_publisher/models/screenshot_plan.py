from pydantic import Field, model_validator

from app_publisher.enums.screenshot_driver import ScreenshotDriver
from app_publisher.enums.screenshot_platform import ScreenshotPlatform
from app_publisher.models.screenshot_scene import ScreenshotScene
from app_publisher.models.strict_model import StrictModel


class ScreenshotPlan(StrictModel):
    driver: ScreenshotDriver = "native"
    platform: ScreenshotPlatform
    device: str = Field(min_length=1)
    scenes: list[ScreenshotScene] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_actions(self) -> "ScreenshotPlan":
        supported = {
            "android": {"tap", "swipe", "text", "launch", "terminate", "open_url", "wait"},
            "ios": {"launch", "terminate", "open_url", "wait"},
            "tvos": {"launch", "terminate", "open_url", "wait"},
            "watchos": {"launch", "terminate", "open_url", "wait"},
            "visionos": {"launch", "terminate", "open_url", "wait"},
            "macos": {"launch", "open_url", "wait"},
        }
        if self.driver == "idb" and self.platform not in {"ios", "tvos"}:
            raise ValueError("The idb screenshot driver currently supports iOS and tvOS targets only")
        if self.driver == "idb":
            supported["ios"] = {
                "tap",
                "swipe",
                "text",
                "launch",
                "terminate",
                "open_url",
                "wait",
                "tap_element",
                "wait_element",
                "hinge",
                "rotate",
                "shake",
                "pinch",
            }
            supported["tvos"] = {"launch", "terminate", "open_url", "wait", "remote"}
        for scene in self.scenes:
            for action in scene.actions:
                if action.kind not in supported[self.platform]:
                    raise ValueError(
                        f"Screenshot action {action.kind} is not supported on {self.platform} by the public device CLI"
                    )
        return self
