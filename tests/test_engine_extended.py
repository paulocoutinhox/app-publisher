from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.apple_build import AppleBuild
from app_publisher.models.screenshot_design import ScreenshotDesign
from app_publisher.models.screenshot_plan import ScreenshotPlan


class Store:
    def __init__(self, versions=None):
        self.calls = []
        self.api = SimpleNamespace(close=lambda: self.calls.append("close"))
        self.existing = (
            versions
            if versions is not None
            else [
                {
                    "id": "version-id",
                    "attributes": {
                        "platform": "IOS",
                        "versionString": "2.0",
                        "appVersionState": "PREPARE_FOR_SUBMISSION",
                    },
                }
            ]
        )

    def identify(self):
        self.calls.append("identify")

    def versions(self):
        return self.existing


def test_extra_apple_and_google_sync_routes(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    project.apple.categories = {"primaryCategory": "FOOD_AND_DRINK"}
    project.apple.age_rating = {"advertising": False}
    project.apple.verify_base_territory = "USA"
    project.apple.review = {"notes": "Reviewer instructions"}
    project.google.subscriptions = [
        {
            "product_id": "premium",
            "update_mask": ["listings"],
            "regions_version": "1",
            "data": {"listings": []},
        }
    ]
    store = Store()
    store.synchronize = lambda *args, **kwargs: ["apple metadata"]
    google = SimpleNamespace(
        api=SimpleNamespace(close=lambda: None), synchronize=lambda *args, **kwargs: ["google metadata"]
    )
    monkeypatch.setattr(engine, "apple", lambda: store)
    monkeypatch.setattr(engine, "google", lambda: google)
    calls = []
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleInformation.synchronize",
        lambda *args, **kwargs: calls.append("categories") or ["categories"],
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleCommercial.verify_base_territory",
        lambda *args, **kwargs: calls.append("territory") or ["territory"],
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleReviewManager.synchronize_details",
        lambda *args, **kwargs: calls.append("review") or ["review"],
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.GoogleMonetization.synchronize",
        lambda *args, **kwargs: calls.append("products") or ["products"],
    )
    changes = engine.synchronize(apply=True, provider="apple")
    assert changes == ["apple metadata", "categories", "territory", "review"]
    assert engine.synchronize(apply=False, provider="google") == ["google metadata", "products"]
    assert calls == ["categories", "territory", "review", "products"]


def test_build_plan_and_render_engine(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    (tmp_path / "export.plist").write_text("<plist/>")
    (tmp_path / "gradlew").write_text("#!/bin/sh")
    project.apple.versions[0].build = AppleBuild(
        project="Demo.xcodeproj",
        scheme="Demo",
        archive_path="build/Demo.xcarchive",
        export_path="out",
        export_options="export.plist",
    )
    project.google.release.build = {"gradle_wrapper": "gradlew", "artifact": "out/app.aab"}
    calls = []
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.BuildRunner.apple",
        lambda *args, **kwargs: calls.append("apple"),
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.BuildRunner.android",
        lambda *args, **kwargs: calls.append("android"),
    )
    assert len(engine.build(apply=False, provider="all")) == 2
    assert calls == []
    assert len(engine.build(apply=True, provider="all")) == 2
    assert calls == ["apple", "android"]
    assert len(engine.build(apply=True, provider="apple")) == 1
    assert len(engine.build(apply=True, provider="google")) == 1
    project.publication.screenshot_plans = [
        ScreenshotPlan(
            platform="android",
            device="serial",
            scenes=[{"name": "Home", "url": "app://home", "output": "shots/home.png"}],
        )
    ]
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.ScreenshotPlanner.run",
        lambda *args, **kwargs: calls.append("capture"),
    )
    assert len(engine.screenshots(apply=False)) == 1
    assert len(engine.screenshots(apply=True)) == 1
    assert calls[-1] == "capture"
    (tmp_path / "raw.png").write_bytes(b"image")
    (tmp_path / "font.ttf").write_bytes(b"font")
    project.publication.screenshot_designs = [
        ScreenshotDesign(
            source="raw.png", output="out/shot.png", font="font.ttf", title="Title", width=800, height=1200
        )
    ]
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.ScreenshotRenderer.render",
        lambda *args, **kwargs: calls.append("render"),
    )
    assert len(engine.render_screenshots(apply=False)) == 1
    assert len(engine.render_screenshots(apply=True)) == 1
    assert calls[-1] == "render"


def test_review_engine_modes(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    store = Store()
    monkeypatch.setattr(engine, "apple", lambda: store)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleReviewManager.submit",
        lambda *args, **kwargs: ["submitted"],
    )
    assert engine.review(apply=False) == ["submitted"]
    assert engine.review(apply=True) == ["submitted"]
    store.existing = []
    with pytest.raises(ConfigurationError, match="does not exist"):
        engine.review(apply=False)
    store.existing = [
        {
            "id": "version-id",
            "attributes": {"platform": "IOS", "versionString": "2.0", "appVersionState": "IN_REVIEW"},
        }
    ]
    with pytest.raises(ConfigurationError, match="PREPARE_FOR_SUBMISSION"):
        engine.review(apply=True)
    project.apple = None
    with pytest.raises(ConfigurationError, match="requires an Apple"):
        engine.review(apply=False)


def test_beta_engine_modes(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    store = Store()
    monkeypatch.setattr(engine, "apple", lambda: store)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleBetaManager.distribute",
        lambda *args, **kwargs: ["attached"],
    )
    assert engine.beta(apply=False) == ["attached"]
    assert engine.beta(apply=True) == ["attached"]
    project.apple = None
    with pytest.raises(ConfigurationError, match="TestFlight requires"):
        engine.beta(apply=False)


def test_validation_paths(project, tmp_path):
    config = tmp_path / "app.yaml"
    project.publication.screenshot_plans = [
        ScreenshotPlan(
            platform="ios",
            device="uuid",
            scenes=[{"name": "invalid", "url": "invalid", "output": "image.jpg"}],
        )
    ]
    project.publication.screenshot_designs = [
        ScreenshotDesign(
            source="missing.png",
            output="image.jpg",
            font="missing.ttf",
            title="X",
            width=400,
            height=400,
            padding=200,
        )
    ]
    project.apple.versions[0].build = AppleBuild(
        project="App.xcodeproj",
        scheme="App",
        archive_path="a.xcarchive",
        export_path="out",
        export_options="missing.plist",
    )
    project.google.release.build = {"gradle_wrapper": "missing-wrapper", "artifact": "app.aab"}
    issues = validate_project(project, config)
    assert any("screenshot artwork output" in issue for issue in issues)
    assert any("artwork input" in issue for issue in issues)
    assert any("no drawable area" in issue for issue in issues)
    assert any("Screenshot scene URL" in issue for issue in issues)
    assert any("Invalid screenshot output" in issue for issue in issues)
    assert any("Gradle wrapper" in issue for issue in issues)
    assert any("Apple export options" in issue for issue in issues)


def test_apple_build_schema():
    with pytest.raises(ValidationError, match="Exactly one"):
        AppleBuild(scheme="Demo", archive_path="a", export_path="b", export_options="c")
    with pytest.raises(ValidationError, match="Exactly one"):
        AppleBuild(
            workspace="a", project="b", scheme="Demo", archive_path="a", export_path="b", export_options="c"
        )


def test_engine_branch_only_age_or_apple_version_not_found(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    project.apple.review = {"notes": "check"}
    store = Store([])
    store.synchronize = lambda *args, **kwargs: ["apple"]
    monkeypatch.setattr(engine, "apple", lambda: store)
    assert engine.synchronize(apply=False, provider="apple") == ["apple"]
    assert engine.build(apply=False, provider="apple") == []
