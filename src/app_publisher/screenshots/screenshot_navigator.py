import subprocess
import time
from collections.abc import Callable

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.screenshot_action import ScreenshotAction


class ScreenshotNavigator:
    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.runner = runner
        self.sleeper = sleeper

    def execute(
        self, platform: str, device: str, action: ScreenshotAction, *, driver: str = "native"
    ) -> None:
        if action.kind == "wait":
            self.sleeper(action.seconds)
            return
        if driver == "idb":
            command = self.idb(device, action)
        elif platform == "android":
            command = self.android(device, action)
        elif platform == "macos":
            command = self.macos(action)
        else:
            command = self.apple(device, action)
        try:
            self.runner(command, check=True, capture_output=True)
        except FileNotFoundError as error:
            raise ConfigurationError(f"Screenshot navigation tool is missing: {command[0]}") from error
        except subprocess.CalledProcessError as error:
            raise UnsafeOperationError(f"Screenshot navigation command failed: {action.kind}") from error

    @staticmethod
    def idb(device: str, action: ScreenshotAction) -> list[str]:
        prefix = ["idb"]
        target = ["--udid", device]
        if action.kind == "tap":
            return [*prefix, "ui", "tap", str(action.x), str(action.y), *target]
        if action.kind == "swipe":
            return [
                *prefix,
                "ui",
                "swipe",
                str(action.x),
                str(action.y),
                str(action.end_x),
                str(action.end_y),
                "--duration",
                str(action.duration_ms / 1000),
                *target,
            ]
        if action.kind == "text":
            return [*prefix, "ui", "text", action.value, *target]
        if action.kind == "tap_element":
            return [*prefix, "ui", "tap", action.value, "--match-key", "AXUniqueId", *target]
        if action.kind == "wait_element":
            return [
                *prefix,
                "ui",
                "wait",
                action.value,
                "--match-key",
                "AXUniqueId",
                "--timeout",
                "30",
                *target,
            ]
        if action.kind == "hinge":
            return [*prefix, "hinge", str(action.angle), *target]
        if action.kind == "launch":
            return [*prefix, "launch", action.value, *target]
        if action.kind == "terminate":
            return [*prefix, "terminate", action.value, *target]
        if action.kind == "open_url":
            return [*prefix, "open", action.value, *target]
        if action.kind == "remote":
            return [*prefix, "ui", "remote", action.value, *target]
        if action.kind == "rotate":
            return [*prefix, "rotation", action.value, *target]
        if action.kind == "shake":
            return [*prefix, "ui", "shake", *target]
        if action.kind == "pinch":
            return [*prefix, "ui", "pinch", str(action.x), str(action.y), str(action.scale), *target]
        raise ConfigurationError(f"Unsupported idb screenshot action: {action.kind}")

    @staticmethod
    def android(device: str, action: ScreenshotAction) -> list[str]:
        prefix = ["adb", "-s", device, "shell"]
        if action.kind == "tap":
            return [*prefix, "input", "tap", str(action.x), str(action.y)]
        if action.kind == "swipe":
            return [
                *prefix,
                "input",
                "swipe",
                str(action.x),
                str(action.y),
                str(action.end_x),
                str(action.end_y),
                str(action.duration_ms),
            ]
        if action.kind == "text":
            if not all(
                character.isascii() and (character.isalnum() or character in " ._@-")
                for character in action.value
            ):
                raise ConfigurationError(
                    "Android adb text input accepts only ASCII letters, digits, spaces, dots, underscores, hyphens and @"
                )
            return [*prefix, "input", "text", action.value.replace(" ", "%s")]
        if action.kind == "launch":
            return [*prefix, "monkey", "-p", action.value, "1"]
        if action.kind == "terminate":
            return [*prefix, "am", "force-stop", action.value]
        if action.kind == "open_url":
            return [*prefix, "am", "start", "-a", "android.intent.action.VIEW", "-d", action.value]
        raise ConfigurationError(f"Unsupported Android screenshot action: {action.kind}")

    @staticmethod
    def apple(device: str, action: ScreenshotAction) -> list[str]:
        prefix = ["xcrun", "simctl"]
        if action.kind == "launch":
            return [*prefix, "launch", device, action.value]
        if action.kind == "terminate":
            return [*prefix, "terminate", device, action.value]
        if action.kind == "open_url":
            return [*prefix, "openurl", device, action.value]
        raise ConfigurationError(f"Unsupported Apple screenshot action: {action.kind}")

    @staticmethod
    def macos(action: ScreenshotAction) -> list[str]:
        if action.kind == "launch":
            return ["open", "-a", action.value]
        if action.kind == "open_url":
            return ["open", action.value]
        raise ConfigurationError(f"Unsupported macOS screenshot action: {action.kind}")
