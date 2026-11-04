import sys
import types
from types import SimpleNamespace

import httpx
import pytest
import yaml
from conftest import Recorder
from typer.testing import CliRunner

from app_publisher import cli
from app_publisher.core import auth
from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_metadata import AppleMetadata
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.google_release import GoogleRelease
from app_publisher.providers.apple_publisher import ApplePublisher
from app_publisher.providers.firebase_publisher import FirebasePublisher
from app_publisher.providers.google_publisher import GooglePublisher


def test_cli_devices_and_capture(project, tmp_path, monkeypatch):
    config = tmp_path / "app.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    api = APIClient(
        "https://api.test",
        lambda: "t",
        httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {
                                "placementProfileGroups": [
                                    {
                                        "placementProfileGroupId": "D",
                                        "displayClassId": "IPHONE_DUO",
                                        "platform": "IOS",
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        ),
    )
    fake = SimpleNamespace(api=api, config=project.apple)
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: fake)
    result = CliRunner().invoke(cli.app, ["devices", str(config)])
    assert result.exit_code == 0
    assert "IPHONE_DUO" in result.stdout
    project.apple = None
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    result = CliRunner().invoke(cli.app, ["devices", str(config)])
    assert result.exit_code != 0
    monkeypatch.setattr(cli.ScreenshotCapture, "capture", lambda self, platform, target, output: output)
    result = CliRunner().invoke(
        cli.app, ["screenshots", "capture", "ios", "booted", str(tmp_path / "out.png")]
    )
    assert result.exit_code == 0
    assert "Saved screenshot" in result.stdout


def test_cli_main_success_and_error(monkeypatch):
    monkeypatch.setattr(cli, "app", lambda: None)
    cli.main()

    def raise_error():
        raise ConfigurationError("simulated")

    monkeypatch.setattr(cli, "app", raise_error)
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 1


def test_google_auth_token(monkeypatch):
    import google

    module = types.ModuleType("google.auth")
    transport = types.ModuleType("google.auth.transport")
    requests = types.ModuleType("google.auth.transport.requests")
    requests.Request = lambda: "request"
    transport.requests = requests
    module.transport = transport
    monkeypatch.setitem(sys.modules, "google.auth", module)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests)
    monkeypatch.setattr(google, "auth", module, raising=False)
    credential = SimpleNamespace(token="access-token", refresh=lambda request: None)
    module.default = lambda scopes: (credential, None)
    assert auth.google_token(["scope"]) == "access-token"
    credential.token = ""
    with pytest.raises(ConfigurationError, match="empty"):
        auth.google_token(["scope"])


def test_engine_build_clients(project, tmp_path, monkeypatch):
    import app_publisher.core.publication_engine as engine_module

    bases = []

    def fake_client(base, token):
        bases.append(base)
        return APIClient(base, lambda: "test")

    monkeypatch.setattr(engine_module, "APIClient", fake_client)
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    assert engine.apple().config == project.apple
    assert engine.google().config == project.google
    assert engine.firebase().config == project.firebase
    assert any("appstoreconnect" in base for base in bases)
    assert any("cloudresourcemanager" in base for base in bases)


def test_validation_more_branches(project, tmp_path):
    locale = project.locales["en-US"]
    locale.apple = None
    locale.google = None
    assert validate_project(project, tmp_path / "app.yaml") == []
    locale.apple = AppleMetadata(
        description="x" * 4001,
        promotional_text="x" * 171,
        whats_new="x" * 4001,
        screenshots={"APP_DUO": ["missing.png"]},
    )
    locale.google = GoogleMetadata(title="X", images={"phoneScreenshots": ["missing.png"]})
    project.apple.versions[0] = AppleVersion(
        platform="IOS", version="2.0", artifact="no.ipa", build_number="20"
    )
    errors = validate_project(project, tmp_path / "app.yaml")
    assert any("description" in item for item in errors)
    assert any("promotional_text" in item for item in errors)
    assert any("whats_new" in item for item in errors)
    assert any("no.ipa" in item for item in errors)


def test_apple_no_change_and_errors(project, tmp_path):
    def handler(req):
        if req.url.path == "/apps/123":
            return httpx.Response(200, json={"data": {"attributes": {"bundleId": "com.demo"}}})
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.url.path.endswith("/appInfoLocalizations"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "local",
                            "attributes": {"locale": "en-US", "name": "Demo", "subtitle": "All apps"},
                        }
                    ]
                },
            )
        if req.url.path.endswith("/appStoreVersions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "ver",
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
        if req.url.path.endswith("/appStoreVersionLocalizations"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "loc",
                            "attributes": {
                                "locale": "en-US",
                                "description": "A demo app",
                                "whatsNew": "Changes",
                                "keywords": "demo,app",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = ApplePublisher(APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.apple)
    assert pub.synchronize(project, tmp_path, apply=True) == ["Apple IOS 2.0: ready"]
    project.locales["en-US"].apple = AppleMetadata()
    assert pub.synchronize(project, tmp_path, apply=False) == ["Apple IOS 2.0: ready"]
    assert pub.version_fields(None, None, AppleMetadata()) == {}
    missing = ApplePublisher(
        APIClient(
            "https://api.test",
            lambda: "t",
            httpx.MockTransport(lambda req: httpx.Response(200, json={"data": []})),
        ),
        project.apple,
    )
    with pytest.raises(RemoteAPIError, match="no appInfos"):
        missing.sync_app_information(project, apply=False)


def test_google_listing_image_and_release_edges(project, tmp_path, png):
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET" and req.url.path.endswith("/listings"):
            return httpx.Response(
                200,
                json={
                    "listings": [
                        {
                            "language": "en-US",
                            "title": "Demo",
                            "shortDescription": "Short demo",
                            "fullDescription": "A demo app",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    assert pub.listing("edit", "en-US")["language"] == "en-US"
    assert pub.listing("edit", "pt-BR") is None
    assert pub.synchronize(project, tmp_path, apply=True) == []
    assert any(req.method == "DELETE" for req in rec.calls)
    assert pub.publish_release(tmp_path, {}, apply=True) == ["Google: update track internal (draft)"]
    project.google.release = None
    with pytest.raises(UnsafeOperationError, match="bundle upload"):
        pub.upload_bundle("edit", tmp_path)
    project.google.release = GoogleRelease(artifact="missing.aab")
    with pytest.raises(FileNotFoundError):
        pub.upload_bundle("edit", tmp_path)


def test_firebase_more_error_branches(project, tmp_path):
    project.firebase.create_if_missing = True

    def handler(req):
        if req.url.path == "/projects/demo-123456" and req.url.host == "firebase.test":
            return httpx.Response(404, json={})
        if req.url.host == "cloud.test" and req.url.path == "/projects/demo-123456":
            return httpx.Response(403, json={})
        return httpx.Response(200, json={})

    client = APIClient("https://firebase.test", lambda: "t", httpx.MockTransport(handler))
    cloud = APIClient("https://cloud.test", lambda: "t", httpx.MockTransport(handler))
    pub = FirebasePublisher(client, cloud, project.firebase)
    with pytest.raises(RemoteAPIError, match="403"):
        pub.ensure_project()
    errors = APIClient(
        "https://firebase.test", lambda: "t", httpx.MockTransport(lambda req: httpx.Response(403, json={}))
    )
    with pytest.raises(RemoteAPIError, match="403"):
        FirebasePublisher(errors, cloud, project.firebase).ensure_project()
