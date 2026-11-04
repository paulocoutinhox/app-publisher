from pathlib import Path

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.validation import validate_project
from app_publisher.models.apple_build import AppleBuild
from app_publisher.models.screenshot_plan import ScreenshotPlan


def test_stage_validation_does_not_require_generated_assets(project, tmp_path, monkeypatch):
    project.locales["en-US"].apple.screenshots = {"APP_IPHONE_65": ["not-captured-yet.png"]}
    project.locales["en-US"].google.images = {"phoneScreenshots": ["not-captured-yet.png"]}
    project.apple.versions[0].build_number = "100"
    project.apple.versions[0].artifact = Path("not-built-yet.ipa")
    project.apple.versions[0].build = AppleBuild(
        project="Demo.xcodeproj",
        scheme="Demo",
        archive_path="out.xcarchive",
        export_path="output",
        export_options="not-created.plist",
    )
    project.publication.screenshot_plans = [
        ScreenshotPlan(
            platform="android",
            device="device",
            scenes=[{"name": "home", "url": "sample://home", "output": "not-captured-yet.png"}],
        )
    ]
    assert validate_project(project, tmp_path / "config.yaml", local_files="none") == []
    assert any(
        "no matches" in issue
        for issue in validate_project(project, tmp_path / "config.yaml", local_files="store")
    )
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    recorded = []
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.ScreenshotPlanner.run",
        lambda self, plan, directory: recorded.append(plan),
    )
    assert engine.screenshots(apply=False) == ["android device: capture home -> not-captured-yet.png"]
    assert len(engine.screenshots(apply=True)) == 1
    assert len(recorded) == 1
    assert engine.build(apply=False) == ["Apple IOS: compile and export Demo"]


def test_stage_validation_rejects_path_traversal(project, tmp_path):
    project.publication.screenshot_plans = [
        ScreenshotPlan(
            platform="ios",
            device="device",
            scenes=[{"name": "unsafe", "url": "sample://home", "output": "../outside.png"}],
        )
    ]
    assert any(
        "Invalid screenshot output" in issue
        for issue in validate_project(project, tmp_path / "config.yaml", local_files="none")
    )
    project.publication.screenshot_plans = []
    from app_publisher.models.screenshot_design import ScreenshotDesign

    project.publication.screenshot_designs = [
        ScreenshotDesign(
            source="photo.png", font="font.ttf", output="../unsafe.png", title="Test", width=600, height=800
        )
    ]
    assert any(
        "Invalid screenshot artwork output" in issue
        for issue in validate_project(project, tmp_path / "config.yaml", local_files="none")
    )
