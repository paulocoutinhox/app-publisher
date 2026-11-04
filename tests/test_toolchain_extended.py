import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.android_build import AndroidBuild
from app_publisher.models.apple_build import AppleBuild
from app_publisher.models.screenshot_design import ScreenshotDesign
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.screenshots.screenshot_planner import ScreenshotPlanner
from app_publisher.screenshots.screenshot_renderer import ScreenshotRenderer
from app_publisher.toolchain.build_runner import BuildRunner


def test_build_runner_apple_and_android(tmp_path):
    commands = []
    (tmp_path / "export.plist").write_text("test")
    (tmp_path / "gradlew").write_text("#!/bin/sh\n")
    (tmp_path / "gradlew").chmod(0o755)
    (tmp_path / "app.aab").write_bytes(b"binary")
    runner = BuildRunner(lambda command, **options: commands.append((command, options)))
    assert (
        runner.apple(
            AppleBuild(
                workspace="app.xcworkspace",
                scheme="App",
                archive_path="out.xcarchive",
                export_path="output",
                export_options="export.plist",
            ),
            tmp_path,
        )
        == tmp_path / "output"
    )
    assert (
        runner.apple(
            AppleBuild(
                project="app.xcodeproj",
                scheme="App",
                archive_path="out.xcarchive",
                export_path="output",
                export_options="export.plist",
            ),
            tmp_path,
        )
        == tmp_path / "output"
    )
    assert runner.android(AndroidBuild(artifact="app.aab"), tmp_path) == tmp_path / "app.aab"
    assert len(commands) == 5
    assert commands[0][0][:3] == ["xcodebuild", "-workspace", "app.xcworkspace"]
    assert commands[2][0][:3] == ["xcodebuild", "-project", "app.xcodeproj"]


def test_build_failures(tmp_path, monkeypatch):
    build = AppleBuild(
        project="test.xcodeproj",
        scheme="Test",
        archive_path="a.xcarchive",
        export_path="output",
        export_options="missing.plist",
    )
    with pytest.raises(ConfigurationError, match="export options"):
        BuildRunner().apple(build, tmp_path)
    with pytest.raises(ConfigurationError, match="wrapper is missing"):
        BuildRunner().android(AndroidBuild(artifact="out.aab"), tmp_path)
    wrapper = tmp_path / "gradlew"
    wrapper.write_text("#!/bin/sh\n")
    with monkeypatch.context() as permission:
        permission.setattr("app_publisher.toolchain.build_runner.os.access", lambda *args: False)
        with pytest.raises(ConfigurationError, match="not executable"):
            BuildRunner().android(AndroidBuild(artifact="out.aab"), tmp_path)
    wrapper.chmod(0o755)
    with pytest.raises(ConfigurationError, match="did not produce"):
        BuildRunner(lambda *args, **kwargs: None).android(AndroidBuild(artifact="out.aab"), tmp_path)
    with pytest.raises(ConfigurationError, match="Required build tool"):
        BuildRunner(lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError())).execute(
            ["missing"], tmp_path
        )
    with pytest.raises(UnsafeOperationError, match="Build command failed"):
        BuildRunner(
            lambda *args, **kwargs: (_ for _ in ()).throw(
                subprocess.CalledProcessError(1, "test", stderr="problem")
            )
        ).execute(["test"], tmp_path)


def test_screenshot_plan_android_and_apple(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "screencap" in command:
            return SimpleNamespace(stdout=b"image")
        if "screenshot" in command:
            Path(command[-1]).write_bytes(b"image")
        return SimpleNamespace(stdout=b"")

    sleep = []
    planner = ScreenshotPlanner(runner, sleep.append)
    android = ScreenshotPlan(
        platform="android",
        device="serial",
        scenes=[{"name": "home", "url": "myapp://home", "output": "shots/home.png", "delay_seconds": 0}],
    )
    apple = ScreenshotPlan(
        platform="ios",
        device="uuid",
        scenes=[{"name": "search", "url": "myapp://search", "output": "shots/apple.png", "delay_seconds": 1}],
    )
    assert planner.run(android, tmp_path) == [tmp_path / "shots/home.png"]
    assert planner.run(apple, tmp_path) == [tmp_path / "shots/apple.png"]
    assert calls[0][:4] == ["adb", "-s", "serial", "shell"]
    assert calls[2][:4] == ["xcrun", "simctl", "openurl", "uuid"]
    assert sleep == [0, 1]


def test_screenshot_plan_failures():
    for error, expected in [
        (FileNotFoundError(), ConfigurationError),
        (subprocess.CalledProcessError(1, "tool"), UnsafeOperationError),
    ]:
        planner = ScreenshotPlanner(lambda *args, **kwargs: (_ for _ in ()).throw(error))
        with pytest.raises(expected):
            planner.command(["tool"])


def test_render_screenshot_and_invalid_titles(tmp_path):
    font = Path(__file__).parent / "fixtures" / "poppins-regular.ttf"
    (tmp_path / "font.ttf").write_bytes(font.read_bytes())
    Image.new("RGB", (400, 600), "red").save(tmp_path / "source.png")
    renderer = ScreenshotRenderer()
    design = ScreenshotDesign(
        source="source.png",
        font="font.ttf",
        output="output/store.png",
        title="Demo",
        width=600,
        height=900,
        font_size=24,
        padding=48,
    )
    assert renderer.render(design, tmp_path).exists()
    with Image.open(tmp_path / "output/store.png") as result:
        assert result.size == (600, 900)
    design.title = "A" * 100
    with pytest.raises(ConfigurationError, match="title exceeds"):
        renderer.render(design, tmp_path)
    design.source = Path("missing.png")
    with pytest.raises(ConfigurationError, match="is missing"):
        renderer.render(design, tmp_path)
