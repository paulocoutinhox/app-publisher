import runpy
import warnings
from types import SimpleNamespace

import httpx
import pytest
import typer
import yaml
from conftest import Recorder
from typer.testing import CliRunner

from app_publisher import cli
from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.models.apple_metadata import AppleMetadata
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.firebase_application import FirebaseApplication
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.locale_config import LocaleConfig
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper
from app_publisher.providers.apple_publisher import ApplePublisher
from app_publisher.providers.firebase_publisher import FirebasePublisher
from app_publisher.providers.google_publisher import GooglePublisher


def test_apple_create_localization_and_screenshot_paths(project, tmp_path, monkeypatch, png):
    project.locales["en-US"].apple.screenshots = {"IPHONE_DUO": ["shot.png"]}
    seen = []
    monkeypatch.setattr(
        AppleAssetLibrary,
        "synchronize",
        lambda self, ident, groups, directory, confirm_replacement=False: seen.append((ident, groups)),
    )

    def handler(req):
        if req.url.path == "/apps/123":
            return httpx.Response(200, json={"data": {"attributes": {"bundleId": "com.demo"}}})
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.method == "GET" and (
            req.url.path.endswith("/appInfoLocalizations")
            or req.url.path.endswith("/appStoreVersionLocalizations")
        ):
            return httpx.Response(200, json={"data": []})
        if req.url.path.endswith("/appStoreVersions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "version",
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
        if req.url.path == "/appInfoLocalizations":
            return httpx.Response(201, json={"data": {"id": "info-local"}})
        if req.url.path == "/appStoreVersionLocalizations":
            return httpx.Response(201, json={"data": {"id": "ver-local"}})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = ApplePublisher(APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.apple)
    planned = pub.synchronize(project, tmp_path, apply=False)
    assert any("create localization" in item for item in planned)
    assert any("screenshot" in item for item in planned)
    assert not seen
    assert pub.synchronize(project, tmp_path, apply=True) == planned
    assert seen == [("ver-local", {"IPHONE_DUO": ["shot.png"]})]
    project.apple.versions[0].version = "3.0"
    assert any("create version" in item for item in pub.synchronize(project, tmp_path, apply=False))
    project.locales["en-US"].apple = None
    assert pub.synchronize(project, tmp_path, apply=False) == ["Apple IOS 3.0: create version"]
    project.locales["en-US"].apple = AppleMetadata()
    project.locales["en-US"].common.description = None
    project.locales["en-US"].common.release_notes = None
    assert pub.synchronize(project, tmp_path, apply=False) == [
        "Apple en-US: create app info localization",
        "Apple IOS 3.0: create version",
    ]


def test_apple_skip_null_fields_and_locale(project):
    project.locales["en-US"].apple = None
    pub = ApplePublisher(
        APIClient(
            "https://api.test",
            lambda: "t",
            httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    json={"data": [{"id": "info"}]} if req.url.path.endswith("/appInfos") else {"data": []},
                )
            ),
        ),
        project.apple,
    )
    assert pub.sync_app_information(project, apply=True) == []
    project.locales["en-US"].apple = AppleMetadata()
    project.locales["en-US"].common.name = None
    assert pub.sync_app_information(project, apply=True) == []


def test_apple_no_version_fields_and_locales(project, tmp_path):
    project.locales["en-US"].common.description = None
    project.locales["en-US"].common.release_notes = None
    project.locales["en-US"].apple = AppleMetadata()

    def handler(req):
        if req.url.path == "/apps/123":
            return httpx.Response(200, json={"data": {"attributes": {"bundleId": "com.demo"}}})
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.url.path.endswith("/appInfoLocalizations"):
            return httpx.Response(
                200, json={"data": [{"id": "loc", "attributes": {"locale": "en-US", "name": "Demo"}}]}
            )
        if req.url.path.endswith("/appStoreVersions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "version",
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
        return httpx.Response(200, json={"data": []})

    pub = ApplePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler)), project.apple
    )
    assert pub.synchronize(project, tmp_path, apply=True) == ["Apple IOS 2.0: ready"]
    project.locales["pt-BR"] = LocaleConfig()
    assert pub.synchronize(project, tmp_path, apply=True) == ["Apple IOS 2.0: ready"]


def test_apple_assets_find_later_image_and_short_upload(png):
    name = AppleAssetLibrary.reference_name(png)

    def handler(req):
        if req.url.path.endswith("/images"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "wrong", "attributes": {"referenceName": "else"}},
                        {"id": "right", "attributes": {"referenceName": name}},
                    ]
                },
            )
        return httpx.Response(200, json={"data": {"attributes": {"state": "APPROVED"}}})

    pub = AppleAssetLibrary(APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler)), "123")
    assert pub.ensure_image("lib", png) == "right"
    with pytest.raises(RemoteAPIError, match="exceeds"):
        AppleAssetUploadHelper.upload_parts(
            pub.api,
            [{"offset": 0, "length": 99999999, "method": "PUT", "url": "https://upload.test"}],
            b"abc",
        )


def test_google_null_metadata_empty_images_and_data_safety_dry_run(project, tmp_path, png):
    project.locales["en-US"].google = None
    project.google.data_safety_csv = "declaration.csv"

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        return httpx.Response(200, json={"listings": []})

    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler)), project.google
    )
    assert pub.synchronize(project, tmp_path, apply=False) == ["Google: update Data Safety declaration"]
    project.google.data_safety_csv = None
    project.locales["en-US"].google = GoogleMetadata(images={"phoneScreenshots": ["shot.png"]})
    assert pub.synchronize(project, tmp_path, apply=False) == [
        "Google en-US: update title, fullDescription",
        "Google en-US phoneScreenshots: replace 1 images",
    ]


def test_google_upload_bundle_network_error(project, tmp_path):
    (tmp_path / "package.aab").write_bytes(b"fake")
    project.google.release.artifact = "package.aab"
    pub = GooglePublisher(
        APIClient(
            "https://api.test",
            lambda: "t",
            httpx.MockTransport(lambda _: httpx.Response(403, json={"error": "blocked"})),
        ),
        project.google,
    )
    with pytest.raises(RemoteAPIError, match="bundle upload"):
        pub.upload_bundle("edit", tmp_path)


def test_firebase_pagination_and_display_name(project, tmp_path):
    project.firebase.apple_apps = []
    project.firebase.android_apps = [
        FirebaseApplication(identifier="com.demo", output="out/config.json", display_name="Demo Android")
    ]
    history = []

    def handler(req):
        history.append(req)
        if req.url.path == "/projects/demo-123456":
            return httpx.Response(200, json={})
        if req.url.path.endswith("/androidApps") and req.method == "GET":
            if "pageToken" not in req.url.params:
                return httpx.Response(
                    200,
                    json={
                        "apps": [{"packageName": "other", "name": "projects/demo-123456/androidApps/other"}],
                        "nextPageToken": "next",
                    },
                )
            return httpx.Response(200, json={"apps": []})
        if req.url.path.endswith("/androidApps") and req.method == "POST":
            return httpx.Response(
                200,
                json={
                    "name": "operations/add",
                    "done": True,
                    "response": {"name": "projects/demo-123456/androidApps/new"},
                },
            )
        if req.url.path.endswith("/config"):
            return httpx.Response(200, json={"configFileContents": "e30="})
        return httpx.Response(200, json={})

    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler))
    pub = FirebasePublisher(api, api, project.firebase)
    assert pub.synchronize(tmp_path, apply=True) == ["Firebase: configured com.demo -> out/config.json"]
    assert (tmp_path / "out/config.json").read_bytes() == b"{}"
    assert any(req.url.params.get("pageToken") == "next" for req in history)
    assert any(b'"displayName"' in req.content for req in history)


def test_engine_release_multiple_versions(project, tmp_path, monkeypatch):
    project.apple.versions.append(
        AppleVersion(platform="TV_OS", version="2.0", artifact="tv.ipa", build_number="10")
    )
    (tmp_path / "tv.ipa").write_bytes(b"fake")
    events = []
    fake = SimpleNamespace(
        identify=lambda: events.append("identify"),
        upload_build=lambda version, path: events.append(version.platform),
        api=SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: fake)
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    assert engine.release(apply=True, provider="apple") == ["Apple TV_OS: upload tv.ipa"]
    assert events == ["identify", "TV_OS"]


def test_remaining_validation_and_release_dry_run(project, tmp_path, monkeypatch):
    from app_publisher.core.validation import validate_project

    project.google = None
    assert validate_project(project, tmp_path / "app.yaml") == []
    project.apple.versions[0] = AppleVersion(
        platform="IOS", version="2.0", artifact="ios.ipa", build_number="42"
    )
    (tmp_path / "ios.ipa").write_bytes(b"archive")
    events = []
    publisher = SimpleNamespace(
        identify=lambda: events.append("identify"),
        upload_build=lambda version, path: events.append("uploaded"),
        api=SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: publisher)
    assert PublicationEngine(project, tmp_path / "app.yaml").release(apply=False, provider="apple") == [
        "Apple IOS: upload ios.ipa"
    ]
    assert events == ["identify"]


def test_doctor_success_and_cli_module(monkeypatch, project, tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    monkeypatch.setattr(cli, "inspect_tools", lambda apple, google, capture: {"python": True})
    result = CliRunner().invoke(cli.app, ["doctor", str(path)])
    assert result.exit_code == 0
    monkeypatch.setattr(typer.Typer, "__call__", lambda self: None)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*found in sys.modules.*", category=RuntimeWarning)
        runpy.run_module("app_publisher.cli", run_name="__main__")
