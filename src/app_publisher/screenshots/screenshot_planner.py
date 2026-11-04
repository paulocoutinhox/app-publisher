import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.screenshots.screenshot_capture import ScreenshotCapture
from app_publisher.screenshots.screenshot_navigator import ScreenshotNavigator


class ScreenshotPlanner:
    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.runner = runner
        self.sleeper = sleeper
        self.navigator = ScreenshotNavigator(runner, sleeper)

    def run(self, plan: ScreenshotPlan, directory: Path) -> list[Path]:
        if plan.platform == "android":
            return self.android(plan, directory)
        if plan.platform == "macos":
            return self.macos(plan, directory)
        return self.apple(plan, directory)

    def command(self, args: list[str]) -> None:
        try:
            self.runner(args, check=True, capture_output=True)
        except FileNotFoundError as error:
            raise ConfigurationError(f"Screenshot tool is missing: {args[0]}") from error
        except subprocess.CalledProcessError as error:
            raise UnsafeOperationError(f"Screenshot navigation failed: {args}") from error

    def android(self, plan: ScreenshotPlan, directory: Path) -> list[Path]:
        results: list[Path] = []
        for scene in plan.scenes:
            self.command(
                [
                    "adb",
                    "-s",
                    plan.device,
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    scene.url,
                ]
            )
            self.sleeper(scene.delay_seconds)
            for action in scene.actions:
                self.navigator.execute(plan.platform, plan.device, action)
            results.append(
                ScreenshotCapture(self.runner).capture("android", plan.device, directory / scene.output)
            )
        return results

    def macos(self, plan: ScreenshotPlan, directory: Path) -> list[Path]:
        results: list[Path] = []
        for scene in plan.scenes:
            self.command(["open", scene.url])
            self.sleeper(scene.delay_seconds)
            for action in scene.actions:
                self.navigator.execute(plan.platform, plan.device, action)
            results.append(
                ScreenshotCapture(self.runner).capture("macos", plan.device, directory / scene.output)
            )
        return results

    def apple(self, plan: ScreenshotPlan, directory: Path) -> list[Path]:
        if plan.driver == "idb":
            return self.idb(plan, directory)
        results: list[Path] = []
        for scene in plan.scenes:
            self.command(["xcrun", "simctl", "openurl", plan.device, scene.url])
            self.sleeper(scene.delay_seconds)
            for action in scene.actions:
                self.navigator.execute(plan.platform, plan.device, action)
            results.append(
                ScreenshotCapture(self.runner).capture(plan.platform, plan.device, directory / scene.output)
            )
        return results

    def idb(self, plan: ScreenshotPlan, directory: Path) -> list[Path]:
        results: list[Path] = []
        for scene in plan.scenes:
            self.command(["idb", "open", scene.url, "--udid", plan.device])
            self.sleeper(scene.delay_seconds)
            for action in scene.actions:
                self.navigator.execute(plan.platform, plan.device, action, driver="idb")
            output = project_path(directory, scene.output)
            if output.suffix.lower() != ".png":
                raise ConfigurationError("Screenshots must use the PNG format")
            output.parent.mkdir(parents=True, exist_ok=True)
            self.command(["idb", "screenshot", str(output), "--udid", plan.device])
            if not output.is_file():
                raise UnsafeOperationError(f"idb did not generate the screenshot: {output}")
            results.append(output)
        return results
