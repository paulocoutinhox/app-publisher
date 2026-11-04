import hashlib
import os
from pathlib import Path

import httpx
import pytest

from app_publisher.core.api_client import APIClient
from app_publisher.core.sync_plan import apply_plan, asset_manifest, generate_plan
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_metadata import AppleMetadata
from app_publisher.models.google_deobfuscation_file import GoogleDeobfuscationFile
from app_publisher.providers.apple_app_previews import AppleAppPreviews
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.providers.apple_publisher import ApplePublisher


class SyntheticEngine:
    def __init__(self, project, directory):
        self.project = project
        self.directory = directory
        self.file = directory / "app.yaml"
        self.file.write_text("app: fixture\n")

    def validate(self, *, local_files="all"):
        return None

    def synchronize(self, *, apply, provider):
        return ["Apple: no metadata changes"]


def test_plan_detects_changed_builds_and_symbols(project, tmp_path):
    binary = tmp_path / "app.aab"
    binary.write_bytes(b"one")
    symbols = tmp_path / "mapping.txt"
    symbols.write_bytes(b"first symbols")
    project.google.release.artifact = Path("app.aab")
    project.google.release.deobfuscation_files = [
        GoogleDeobfuscationFile(version_code=8, file_type="proguard", path=Path("mapping.txt"))
    ]
    engine = SyntheticEngine(project, tmp_path)
    manifest = asset_manifest(engine)
    assert manifest["app.aab"] == hashlib.sha256(b"one").hexdigest()
    assert manifest["mapping.txt"] == hashlib.sha256(b"first symbols").hexdigest()
    saved = generate_plan(engine)
    binary.write_bytes(b"two")
    with pytest.raises(UnsafeOperationError, match="Local assets changed"):
        apply_plan(engine, saved)


def test_plan_detects_apple_binary_export_options_and_sources(project, tmp_path):
    project.apple.versions[0].build_number = "1"
    project.apple.versions[0].artifact = Path("dist/app.ipa")
    engine = SyntheticEngine(project, tmp_path)
    assert asset_manifest(engine)["dist/app.ipa"] == "MISSING"
    target = tmp_path / "dist"
    target.mkdir()
    (target / "app.ipa").write_bytes(b"build")
    assert asset_manifest(engine)["dist/app.ipa"] == hashlib.sha256(b"build").hexdigest()


def test_apple_manual_release_replaces_previous_scheduled_type(project):
    handler = ApplePublisher(
        APIClient(
            "https://api.test", lambda: "token", httpx.MockTransport(lambda _: httpx.Response(200, json={}))
        ),
        project.apple,
    )
    version = project.apple.versions[0]
    remote = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "2.0",
            "appVersionState": "PREPARE_FOR_SUBMISSION",
            "releaseType": "SCHEDULED",
        },
    }
    assert handler.synchronize_version_settings(version, remote, apply=False) == [
        "Apple IOS 2.0: update releaseType"
    ]


def test_apple_screenshots_replace_requires_explicit_consent(project, tmp_path, png, monkeypatch):
    def response(request):
        path = request.url.path
        if path.endswith("/appAssetLibraryRefData"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {
                                "placementProfileGroups": [
                                    {"placementProfileGroupId": "IPHONE", "displayClassId": "IPHONE"}
                                ],
                                "placementTypes": [
                                    {
                                        "placementTypeId": "APP_SCREENSHOT",
                                        "specMappings": [{"placementGroupId": "IPHONE", "specs": ["p"]}],
                                    }
                                ],
                                "imageSpecs": [
                                    {
                                        "specId": "p",
                                        "dimensions": {
                                            "minWidth": 1,
                                            "minHeight": 1,
                                            "maxWidth": 5000,
                                            "maxHeight": 5000,
                                        },
                                        "fileExtensions": [".png"],
                                        "maxFileSize": 5000000,
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        if path.endswith("/assetLibrary"):
            return httpx.Response(200, json={"data": {"id": "l"}})
        if path.endswith("/placements"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "old",
                            "attributes": {"placementGroup": "IPHONE"},
                            "relationships": {"image": {"data": {"id": "oldimage"}}},
                        }
                    ]
                },
            )
        if path.endswith("/appAssetLibraryImages/oldimage"):
            return httpx.Response(200, json={"data": {"attributes": {"referenceName": "old"}}})
        raise AssertionError("No upload or delete is allowed without consent")

    calls = []

    def recorded(request):
        calls.append(request)
        return response(request)

    client = APIClient("https://api.test", lambda: "token", httpx.MockTransport(recorded))
    with pytest.raises(UnsafeOperationError, match="confirm_asset_replacement"):
        AppleAssetLibrary(client, "123").synchronize("loc", {"IPHONE": [png.name]}, tmp_path)
    assert all(request.method != "DELETE" for request in calls)


def test_apple_asset_only_locale_is_not_skipped(project, tmp_path, monkeypatch):
    from app_publisher.providers.apple_asset_library import AppleAssetLibrary

    config = project.locales["en-US"]
    config.common.description = None
    config.common.release_notes = None
    config.apple = AppleMetadata(screenshots={"IPHONE": ["photo.png"]})
    seen = []
    monkeypatch.setattr(
        AppleAssetLibrary,
        "synchronize",
        lambda self, loc, groups, directory, confirm_replacement=False: seen.append(loc),
    )

    def response(request):
        path = request.url.path
        if path == "/apps/123":
            return httpx.Response(200, json={"data": {"id": "123", "attributes": {"bundleId": "com.demo"}}})
        if path.endswith("/appStoreVersions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "v",
                            "attributes": {
                                "platform": "IOS",
                                "versionString": "2.0",
                                "appVersionState": "PREPARE_FOR_SUBMISSION",
                                "releaseType": "MANUAL",
                            },
                        }
                    ]
                },
            )
        if path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if request.method == "GET" and (
            path.endswith("/appInfoLocalizations") or path.endswith("/appStoreVersionLocalizations")
        ):
            return httpx.Response(200, json={"data": []})
        if request.method == "POST":
            return httpx.Response(201, json={"data": {"id": "locale"}})
        return httpx.Response(200, json={})

    publisher = ApplePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(response)), project.apple
    )
    result = publisher.synchronize(project, tmp_path, apply=True)
    assert seen == ["locale"]
    assert any("screenshot groups" in item for item in result)


def test_plan_tracks_design_build_inputs_and_absent_release(project, tmp_path):
    from app_publisher.models.android_build import AndroidBuild
    from app_publisher.models.apple_build import AppleBuild
    from app_publisher.models.screenshot_design import ScreenshotDesign

    (tmp_path / "screen.png").write_bytes(b"image-source")
    (tmp_path / "font.ttf").write_bytes(b"font-source")
    (tmp_path / "export.plist").write_bytes(b"export-options")
    (tmp_path / "gradlew").write_bytes(b"gradle")
    design = ScreenshotDesign(
        source=Path("screen.png"),
        output=Path("output.png"),
        font=Path("font.ttf"),
        title="App",
        width=1200,
        height=1600,
    )
    project.publication.screenshot_designs = [design]
    apple_build = AppleBuild(
        workspace=Path("App.xcworkspace"),
        scheme="App",
        archive_path=Path("build.xcarchive"),
        export_path=Path("dist"),
        export_options=Path("export.plist"),
    )
    project.apple.versions[0].build = apple_build
    project.google.release.build = AndroidBuild(gradle_wrapper=Path("gradlew"), artifact=Path("dist/app.aab"))
    engine = SyntheticEngine(project, tmp_path)
    manifest = asset_manifest(engine)
    assert set(manifest) == {"screen.png", "font.ttf", "export.plist", "gradlew"}
    assert manifest["font.ttf"] == hashlib.sha256(b"font-source").hexdigest()
    project.google.release = None
    assert "gradlew" not in asset_manifest(engine)
    project.apple = None
    assert "export.plist" not in asset_manifest(engine)


def test_apple_preview_replacement_blocks_deletion(tmp_path, monkeypatch):
    path = tmp_path / "preview.mp4"
    path.write_bytes(b"video")
    calls = []

    def response(request):
        calls.append(request)
        if request.url.path.endswith("/placements"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "old",
                            "attributes": {"placementGroup": "IPHONE"},
                            "relationships": {"video": {"data": {"id": "oldvideo"}}},
                        }
                    ]
                },
            )
        if request.url.path.endswith("/appAssetLibraryVideos/oldvideo"):
            return httpx.Response(200, json={"data": {"attributes": {"referenceName": "old"}}})
        raise AssertionError("Video replacement must stop before any write")

    manager = AppleAppPreviews(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(response)), "123"
    )
    monkeypatch.setattr(manager.assets, "reference_data", lambda: {"fake": True})
    monkeypatch.setattr(manager.assets, "library_id", lambda: "library")
    monkeypatch.setattr(manager.assets, "resolve_group", lambda key, ref: key)
    monkeypatch.setattr(manager, "inspect_video", lambda media: {})
    monkeypatch.setattr(manager, "validate_video", lambda media, group, reference, inspection: None)
    with pytest.raises(UnsafeOperationError, match="confirm_asset_replacement"):
        manager.synchronize("loc", {"IPHONE": ["preview.mp4"]}, tmp_path)
    assert all(request.method == "GET" for request in calls)


def test_google_release_notes_limit_includes_common_fallback(project, tmp_path):
    from app_publisher.core.validation import validate_project

    project.locales["en-US"].common.release_notes = "x" * 501
    problems = validate_project(project, tmp_path / "app.yaml", local_files="none")
    assert "google.en-US.release_notes exceeds 500 characters" in problems
    project.locales["en-US"].google.release_notes = "y" * 500
    assert not any(
        "google.en-US.release_notes" in issue
        for issue in validate_project(project, tmp_path / "app.yaml", local_files="none")
    )


def test_firebase_rejects_repeated_page_tokens(project, tmp_path):
    from app_publisher.errors.remote_api_error import RemoteAPIError
    from app_publisher.providers.firebase_publisher import FirebasePublisher

    def response(request):
        if request.url.path == "/projects/demo-123456":
            return httpx.Response(200, json={"projectId": "demo-123456"})
        return httpx.Response(200, json={"apps": [], "nextPageToken": "again"})

    api = APIClient("https://firebase.test", lambda: "token", httpx.MockTransport(response))
    with pytest.raises(RemoteAPIError, match="pagination cycle"):
        FirebasePublisher(api, api, project.firebase).synchronize(tmp_path, apply=True)


def test_firebase_config_atomic_write_and_symlink_guard(tmp_path):
    from app_publisher.providers.firebase_publisher import FirebasePublisher

    destination = tmp_path / "nested" / "google-services.json"
    FirebasePublisher.write_config(destination, b"one")
    assert destination.read_bytes() == b"one"
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600
    FirebasePublisher.write_config(destination, b"two")
    assert destination.read_bytes() == b"two"
    assert not list(destination.parent.glob(".app-publisher-*"))
    redirect = tmp_path / "linked"
    redirect.symlink_to(destination)
    with pytest.raises(UnsafeOperationError, match="regular file"):
        FirebasePublisher.write_config(redirect, b"wrong")
    with pytest.raises(UnsafeOperationError, match="regular file"):
        FirebasePublisher.write_config(destination.parent, b"wrong")
