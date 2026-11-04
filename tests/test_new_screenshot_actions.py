import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.screenshot_action import ScreenshotAction
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.screenshots.screenshot_navigator import ScreenshotNavigator
from app_publisher.screenshots.screenshot_planner import ScreenshotPlanner


def test_actions_require_exclusive_parameters():
    required = {
        "tap": {"x": 10, "y": 20},
        "swipe": {"x": 1, "y": 2, "end_x": 50, "end_y": 40, "duration_ms": 300},
        "text": {"value": "Hello"},
        "launch": {"value": "com.example.app"},
        "terminate": {"value": "com.example.app"},
        "open_url": {"value": "sample://screen"},
        "wait": {"seconds": 0.1},
    }
    for kind, arguments in required.items():
        assert ScreenshotAction(kind=kind, **arguments).kind == kind
        with pytest.raises(ValidationError, match="requires exactly"):
            ScreenshotAction(kind=kind)
        with pytest.raises(ValidationError, match="requires exactly"):
            ScreenshotAction(kind=kind, x=1, y=2, value="unexpected")
    with pytest.raises(ValidationError, match="not supported"):
        ScreenshotPlan(
            platform="ios",
            device="sim",
            scenes=[
                {
                    "name": "home",
                    "url": "sample://home",
                    "output": "home.png",
                    "actions": [{"kind": "tap", "x": 2, "y": 3}],
                }
            ],
        )
    with pytest.raises(ValidationError, match="not supported"):
        ScreenshotPlan(
            platform="macos",
            device="desktop",
            scenes=[
                {
                    "name": "home",
                    "url": "sample://home",
                    "output": "home.png",
                    "actions": [{"kind": "terminate", "value": "App"}],
                }
            ],
        )


def test_android_action_commands_and_rejected_input():
    calls = []
    waits = []
    navigator = ScreenshotNavigator(lambda command, **options: calls.append((command, options)), waits.append)
    actions = [
        {"kind": "tap", "x": 12, "y": 13},
        {"kind": "swipe", "x": 1, "y": 2, "end_x": 3, "end_y": 4, "duration_ms": 500},
        {"kind": "text", "value": "Hello world"},
        {"kind": "launch", "value": "com.example.app"},
        {"kind": "terminate", "value": "com.example.app"},
        {"kind": "open_url", "value": "myapp://home"},
        {"kind": "wait", "seconds": 0.25},
    ]
    for action in actions:
        navigator.execute("android", "device", ScreenshotAction(**action))
    assert len(calls) == 6
    assert waits == [0.25]
    assert calls[0][0] == ["adb", "-s", "device", "shell", "input", "tap", "12", "13"]
    assert calls[1][0][-7:] == ["input", "swipe", "1", "2", "3", "4", "500"]
    assert calls[2][0][-2:] == ["text", "Hello%sworld"]
    assert calls[3][0][-4:] == ["monkey", "-p", "com.example.app", "1"]
    assert calls[4][0][-3:] == ["am", "force-stop", "com.example.app"]
    assert calls[5][0][-2:] == ["-d", "myapp://home"]
    with pytest.raises(ConfigurationError, match="only ASCII"):
        navigator.execute("android", "device", ScreenshotAction(kind="text", value="ação"))
    with pytest.raises(ConfigurationError, match="Unsupported Android"):
        navigator.android("device", ScreenshotAction(kind="wait", seconds=1))


def test_apple_and_macos_actions():
    calls = []
    navigator = ScreenshotNavigator(lambda command, **options: calls.append(command))
    for platform in ["ios", "tvos", "watchos", "visionos"]:
        for action in [
            {"kind": "launch", "value": "com.example.app"},
            {"kind": "terminate", "value": "com.example.app"},
            {"kind": "open_url", "value": "sample://test"},
        ]:
            navigator.execute(platform, "uuid", ScreenshotAction(**action))
    assert calls[:3] == [
        ["xcrun", "simctl", "launch", "uuid", "com.example.app"],
        ["xcrun", "simctl", "terminate", "uuid", "com.example.app"],
        ["xcrun", "simctl", "openurl", "uuid", "sample://test"],
    ]
    navigator.execute("macos", "desktop", ScreenshotAction(kind="launch", value="Sample"))
    navigator.execute("macos", "desktop", ScreenshotAction(kind="open_url", value="sample://test"))
    assert calls[-2:] == [["open", "-a", "Sample"], ["open", "sample://test"]]
    with pytest.raises(ConfigurationError, match="Unsupported Apple"):
        navigator.apple("uuid", ScreenshotAction(kind="wait", seconds=1))
    with pytest.raises(ConfigurationError, match="Unsupported macOS"):
        navigator.macos(ScreenshotAction(kind="wait", seconds=1))


def test_action_errors_and_full_scene(tmp_path):
    for error, expected in [
        (FileNotFoundError(), ConfigurationError),
        (subprocess.CalledProcessError(1, "adb"), UnsafeOperationError),
    ]:
        navigator = ScreenshotNavigator(lambda command, **options: (_ for _ in ()).throw(error))
        with pytest.raises(expected):
            navigator.execute("android", "device", ScreenshotAction(kind="tap", x=1, y=2))
    calls = []

    def runner(command, **options):
        calls.append(command)
        if command[0] == "adb" and "screencap" in command:
            return SimpleNamespace(stdout=b"mocked-png")
        if command[0] == "xcrun" and "screenshot" in command:
            Path(command[-1]).write_bytes(b"mocked-png")
        return SimpleNamespace(stdout=b"")

    planner = ScreenshotPlanner(runner, lambda seconds: None)
    android = ScreenshotPlan(
        platform="android",
        device="device",
        scenes=[
            {
                "name": "screen",
                "url": "sample://app",
                "output": "android.png",
                "actions": [{"kind": "tap", "x": 20, "y": 30}],
            }
        ],
    )
    apple = ScreenshotPlan(
        platform="ios",
        device="uuid",
        scenes=[
            {
                "name": "screen",
                "url": "sample://app",
                "output": "ios.png",
                "actions": [{"kind": "launch", "value": "com.example.app"}],
            }
        ],
    )
    mac = ScreenshotPlan(
        platform="macos",
        device="desktop",
        scenes=[
            {
                "name": "screen",
                "url": "sample://app",
                "output": "mac.png",
                "actions": [{"kind": "open_url", "value": "sample://one"}],
            }
        ],
    )
    assert planner.run(android, tmp_path) == [tmp_path / "android.png"]
    assert planner.run(apple, tmp_path) == [tmp_path / "ios.png"]
    assert calls[1][-3:] == ["tap", "20", "30"]
    assert calls[4] == ["xcrun", "simctl", "launch", "uuid", "com.example.app"]

    def mac_runner(command, **options):
        if command[0] == "screencapture":
            Path(command[-1]).write_bytes(b"mocked-png")
        return SimpleNamespace(stdout=b"")

    assert ScreenshotPlanner(mac_runner, lambda _: None).run(mac, tmp_path) == [tmp_path / "mac.png"]
