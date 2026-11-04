from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.screenshots.screenshot_capture import ScreenshotCapture
from app_publisher.toolchain.doctor import inspect_tools, is_macos


def test_cli_validate_doctor_and_screenshots(project, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    result = CliRunner().invoke(app, ["validate", str(config)])
    assert result.exit_code == 0
    assert "valid" in result.stdout
    result = CliRunner().invoke(app, ["screenshots", "validate", str(config)])
    assert result.exit_code == 0
    result = CliRunner().invoke(app, ["doctor", str(config)])
    assert result.exit_code in {0, 1}
    assert "xcodebuild" in result.stdout
    assert inspect_tools(False, False, False) == {}
    assert isinstance(is_macos(), bool)


def test_cli_diff_sync_release_status_dispatch(project, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    monkeypatch.setattr(
        PublicationEngine, "synchronize", lambda self, apply, provider: [f"{provider} {apply}"]
    )
    monkeypatch.setattr(PublicationEngine, "release", lambda self, apply, provider: [f"release {apply}"])
    monkeypatch.setattr(PublicationEngine, "status", lambda self, provider: {"status": "ok"})
    for command in [
        ["diff", str(config)],
        ["sync", str(config), "--apply"],
        ["release", str(config), "--apply"],
        ["status", str(config)],
    ]:
        result = CliRunner().invoke(app, command)
        assert result.exit_code == 0, result.stdout


def test_screenshot_capture_android_and_apple(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[0] in {"xcrun", "screencapture"}:
            Path(command[-1]).write_bytes(b"PNG")
        return SimpleNamespace(stdout=b"PNG")

    capture = ScreenshotCapture(runner)
    assert capture.capture("ios", "booted", tmp_path / "ios.png").read_bytes() == b"PNG"
    assert capture.capture("android", "serial", tmp_path / "android.png").read_bytes() == b"PNG"
    for platform in ("tvos", "watchos", "visionos", "macos"):
        assert capture.capture(platform, "booted", tmp_path / f"{platform}.png").read_bytes() == b"PNG"
    assert calls[0][:3] == ["xcrun", "simctl", "io"]
    assert calls[1][:3] == ["adb", "-s", "serial"]
    with pytest.raises(ConfigurationError, match="device identifier"):
        capture.capture("ios", "", tmp_path / "x.png")
    with pytest.raises(ConfigurationError, match="PNG format"):
        capture.capture("ios", "booted", tmp_path / "x.jpg")
    with pytest.raises(ConfigurationError, match="Unsupported"):
        capture.capture("windows", "target", tmp_path / "x.png")
    with pytest.raises(ConfigurationError, match="did not create"):
        ScreenshotCapture(lambda cmd, **kw: SimpleNamespace(stdout=b"")).capture(
            "ios", "booted", tmp_path / "missing.png"
        )


def test_engine_local_validation(project, tmp_path):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    engine.validate()
    assert engine.project.app.id == "demo"
    project.locales["en-US"].apple.name = "x" * 31
    with pytest.raises(ConfigurationError, match="Validation failed"):
        engine.validate()
