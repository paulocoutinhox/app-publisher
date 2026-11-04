import subprocess
from pathlib import Path
from typing import Literal

from app_publisher.errors.configuration_error import ConfigurationError


class ScreenshotCapture:
    def __init__(self, runner: object | None = None):
        self.runner = runner if runner is not None else subprocess.run

    def capture(
        self,
        platform: Literal["ios", "tvos", "watchos", "visionos", "macos", "android"],
        target: str,
        output: Path,
    ) -> Path:
        if not target:
            raise ConfigurationError("Screenshot capture requires a device identifier")
        if output.suffix.lower() != ".png":
            raise ConfigurationError("Screenshots must use the PNG format")
        output.parent.mkdir(parents=True, exist_ok=True)
        if platform in {"ios", "tvos", "watchos", "visionos"}:
            command = ["xcrun", "simctl", "io", target, "screenshot", str(output)]
            self.runner(command, check=True, capture_output=True)
        elif platform == "macos":
            self.runner(["screencapture", "-x", str(output)], check=True, capture_output=True)
        elif platform == "android":
            command = ["adb", "-s", target, "exec-out", "screencap", "-p"]
            result = self.runner(command, check=True, capture_output=True)
            output.write_bytes(result.stdout)
        else:
            raise ConfigurationError(f"Unsupported capture platform: {platform}")
        if not output.exists():
            raise ConfigurationError(f"Capture did not create an output file: {output}")
        return output
