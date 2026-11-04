import hashlib
import json

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.api_client import APIClient
from app_publisher.core.diagnostics import diagnose, remote_error_message, save_report
from app_publisher.core.sync_plan import (
    apply_plan,
    asset_manifest,
    generate_plan,
    load_plan,
    plan_digest,
    sha256_file,
    store_plan,
)
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_tester_group import GoogleTesterGroup
from app_publisher.providers.google_publisher import GooglePublisher
from app_publisher.providers.google_testers import GoogleTesters


class PlannedEngine:
    def __init__(self, project, file, changes=None):
        self.project = project
        self.file = file
        self.directory = file.parent
        self.changes = changes if changes is not None else ["Google en-US: update description"]
        self.calls = []

    def validate(self, *, local_files="all"):
        self.calls.append(("validate", local_files))

    def synchronize(self, *, apply, provider):
        self.calls.append(("synchronize", apply, provider))
        return self.changes


def test_plan_generation_and_application(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    engine = PlannedEngine(project, file)
    plan = generate_plan(engine, "google")
    assert plan["changes"] == engine.changes
    assert plan["plan_sha256"] == plan_digest(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    assert plan["config_sha256"] == sha256_file(file)
    assert plan["assets"] == {}
    path = store_plan(plan, tmp_path / "plan.json")
    assert load_plan(path) == plan
    assert apply_plan(engine, load_plan(path), apply=True) == engine.changes
    assert engine.calls[-2:] == [("synchronize", False, "google"), ("synchronize", True, "google")]


def test_plan_detects_changed_config_assets_remote_and_identity(project, tmp_path, png):
    file = tmp_path / "app.yaml"
    file.write_text("test: initial\n")
    engine = PlannedEngine(project, file)
    engine.project.locales["en-US"].google.images = {"phoneScreenshots": [png.name]}
    plan = generate_plan(engine)
    assert plan["assets"][png.name] == hashlib.sha256(png.read_bytes()).hexdigest()
    file.write_text("test: modified\n")
    with pytest.raises(UnsafeOperationError, match="YAML changed"):
        apply_plan(engine, plan)
    file.write_text("test: initial\n")
    original = png.read_bytes()
    png.write_bytes(original + b"extra")
    with pytest.raises(UnsafeOperationError, match="Local assets changed"):
        apply_plan(engine, plan)
    png.write_bytes(original)
    engine.changes = ["other operation"]
    with pytest.raises(UnsafeOperationError, match="Remote store state changed"):
        apply_plan(engine, plan)
    engine.project.app.id = "other-app"
    with pytest.raises(UnsafeOperationError, match="identity"):
        apply_plan(engine, plan)


def test_plan_store_protects_existing_and_invalid_json(tmp_path):
    target = tmp_path / "plan.json"
    store_plan({"ok": True}, target)
    assert json.loads(target.read_text()) == {"ok": True}
    with pytest.raises(UnsafeOperationError, match="overwrite"):
        store_plan({}, target)
    with pytest.raises(ConfigurationError, match="format"):
        load_plan(target)
    target.write_text("not json")
    with pytest.raises(ConfigurationError, match="Invalid JSON"):
        load_plan(target)
    symlink = tmp_path / "link.json"
    symlink.symlink_to(target)
    with pytest.raises(UnsafeOperationError, match="symbolic link"):
        store_plan({}, symlink)
    with pytest.raises(ConfigurationError, match="symbolic link"):
        load_plan(symlink)


def test_plan_detects_tampering_and_missing_fields(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("project: test\n")
    plan = generate_plan(PlannedEngine(project, file))
    path = tmp_path / "plan.json"
    forged = {**plan, "changes": ["malicious change"]}
    path.write_text(json.dumps(forged))
    with pytest.raises(UnsafeOperationError, match="modified"):
        load_plan(path)
    path.write_text(json.dumps({**plan, "other": 1}))
    with pytest.raises(UnsafeOperationError, match="modified"):
        load_plan(path)
    path.write_text(json.dumps({**plan, "schema_version": 5}))
    with pytest.raises(ConfigurationError, match="Unsupported"):
        load_plan(path)


def test_google_images_unchanged_are_not_uploaded(project, tmp_path, png):
    project.locales["en-US"].google.images = {"phoneScreenshots": [png.name]}
    checksum = hashlib.sha256(png.read_bytes()).hexdigest()
    calls = []

    def responder(request):
        calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/listings"):
            return httpx.Response(200, json={"listings": [{"language": "en-US", "title": "Name"}]})
        if request.method == "GET" and request.url.path.endswith("/phoneScreenshots"):
            return httpx.Response(200, json={"images": [{"id": "image1", "sha256": checksum}]})
        return httpx.Response(200, json={})

    client = APIClient("https://api.test", lambda: "secret", httpx.MockTransport(responder))
    handler = GooglePublisher(client, project.google)
    changes = handler.synchronize(project, tmp_path, apply=True)
    assert not any("phoneScreenshots" in entry for entry in changes)
    assert not any(req.method == "DELETE" and req.url.path.endswith("/phoneScreenshots") for req in calls)


def test_google_images_replacement_requires_confirmation(project, tmp_path, png):
    project.locales["en-US"].google.images = {"phoneScreenshots": [png.name]}
    calls = []

    def responder(request):
        calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/listings"):
            return httpx.Response(200, json={"listings": [{"language": "en-US"}]})
        if request.method == "GET" and request.url.path.endswith("/phoneScreenshots"):
            return httpx.Response(200, json={"images": [{"id": "old", "sha256": "different"}]})
        return httpx.Response(200, json={})

    client = APIClient("https://api.test", lambda: "secret", httpx.MockTransport(responder))
    handler = GooglePublisher(client, project.google)
    assert any("phoneScreenshots" in entry for entry in handler.synchronize(project, tmp_path, apply=False))
    with pytest.raises(UnsafeOperationError, match="confirm_image_replacement"):
        handler.synchronize(project, tmp_path, apply=True)
    project.google.confirm_image_replacement = True
    handler.synchronize(project, tmp_path, apply=True)
    assert any(req.method == "DELETE" and req.url.path.endswith("/phoneScreenshots") for req in calls)
    assert any(req.url.path.endswith(":validate") for req in calls)
    commits = [request for request in calls if request.url.path.endswith(":commit")]
    assert commits and all("ERROR_IF_IN_REVIEW" in str(request.url) for request in commits)


def test_google_images_invalid_remote_response(project, tmp_path, png):
    project.locales["en-US"].google.images = {"phoneScreenshots": [png.name]}

    def responder(request):
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/listings"):
            return httpx.Response(200, json={"listings": [{"language": "en-US"}]})
        if request.method == "GET" and request.url.path.endswith("/phoneScreenshots"):
            return httpx.Response(200, json={"images": [None]})
        return httpx.Response(200, json={})

    handler = GooglePublisher(
        APIClient("https://api.test", lambda: "secret", httpx.MockTransport(responder)), project.google
    )
    with pytest.raises(RemoteAPIError, match="invalid image listing response"):
        handler.synchronize(project, tmp_path, apply=False)


def test_google_testers_validate_before_safe_commit():
    calls = []

    def responder(request):
        calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        return httpx.Response(200, json={})

    client = APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder))
    manager = GoogleTesters(client, "com.example.app")
    manager.synchronize(
        [GoogleTesterGroup(track="internal", google_groups=["group@example.com"])], apply=True
    )
    endpoints = [req.url.path for req in calls]
    assert endpoints.index("/applications/com.example.app/edits/edit:validate") < endpoints.index(
        "/applications/com.example.app/edits/edit:commit"
    )
    assert "ERROR_IF_IN_REVIEW" in str(calls[-1].url)


def test_structured_api_errors_and_reports(tmp_path):
    def apple_error(request):
        return httpx.Response(
            403,
            json={
                "errors": [
                    {
                        "code": "FORBIDDEN",
                        "detail": "Invalid permissions",
                        "source": {"pointer": "/data/attributes/name"},
                    }
                ]
            },
        )

    client = APIClient("https://api.test", lambda: "token", httpx.MockTransport(apple_error))
    with pytest.raises(RemoteAPIError, match="Invalid permissions") as caught:
        client.request("GET", "apps/id")
    report = diagnose(caught.value, action="sync", provider="apple")
    assert report["http_status"] == 403
    assert "permissions" in report["recommendation"]
    target = tmp_path / "status.json"
    save_report(target, report)
    assert json.loads(target.read_text()) == report
    with pytest.raises(UnsafeOperationError, match="overwrite"):
        save_report(target, report)
    link = tmp_path / "symlink.json"
    link.symlink_to(target)
    with pytest.raises(UnsafeOperationError, match="symbolic link"):
        save_report(link, report)


def test_google_remote_error_and_nonjson_error():
    assert "UNAVAILABLE" in remote_error_message(
        httpx.Response(503, json={"error": {"status": "UNAVAILABLE", "message": "Try later"}})
    )
    assert "non-JSON" in remote_error_message(httpx.Response(400, text="private content"))
    assert "unexpected" in remote_error_message(httpx.Response(400, json=[1, 2]))
    assert "unrecognized" in remote_error_message(
        httpx.Response(400, json={"not_a_standard_error": "private"})
    )
    assert "structured" in remote_error_message(httpx.Response(400, json={"error": {}}))
    assert "FORBIDDEN" in remote_error_message(
        httpx.Response(403, json={"errors": [{"code": "FORBIDDEN"}, None]})
    )
    assert "unrecognized" in remote_error_message(httpx.Response(400, json={"errors": [None]}))
    assert diagnose(UnsafeOperationError("Unsafe"), action="apply-plan", provider="all")[
        "recommendation"
    ].startswith("The operation was blocked")


def test_cli_report_with_mock_engine(tmp_path, monkeypatch, project):
    config = tmp_path / "app.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    from app_publisher.core.publication_engine import PublicationEngine

    monkeypatch.setattr(PublicationEngine, "synchronize", lambda self, apply, provider: ["change"])
    result = CliRunner().invoke(app, ["sync", str(config), "--report", str(tmp_path / "success.json")])
    assert result.exit_code == 0
    assert json.loads((tmp_path / "success.json").read_text())["status"] == "success"

    def fail(self, *, apply, provider):
        raise UnsafeOperationError("configuration blocked")

    monkeypatch.setattr(PublicationEngine, "synchronize", fail)
    result = CliRunner().invoke(
        app, ["sync", str(config), "--apply", "--report", str(tmp_path / "failure.json")]
    )
    assert result.exit_code != 0
    assert json.loads((tmp_path / "failure.json").read_text())["status"] == "failed"


def test_plan_with_apple_previews_and_google_data_safety(project, tmp_path, png):
    file = tmp_path / "app.yaml"
    file.write_text("test: resource-files\n")
    (tmp_path / "video.mov").write_bytes(b"video")
    (tmp_path / "safety.csv").write_text("field,value")
    project.locales["en-US"].apple.screenshots = {"IPHONE_65": [png.name]}
    project.locales["en-US"].apple.app_previews = {"IPHONE_65": ["video.mov"]}
    project.google.data_safety_csv = "safety.csv"
    assets = asset_manifest(PlannedEngine(project, file))
    assert set(assets) == {"shot.png", "video.mov", "safety.csv"}


def test_plan_mismatched_provider_identity(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("test: identity\n")
    engine = PlannedEngine(project, file)
    plan = generate_plan(engine)
    engine.project.apple.app_id = "999999"
    with pytest.raises(UnsafeOperationError, match="store identity"):
        apply_plan(engine, plan)


def test_plan_valid_checksum_but_bad_provider(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("test: provider\n")
    plan = generate_plan(PlannedEngine(project, file))
    for key, value in [("provider", "other"), ("changes", "invalid")]:
        forged = {**plan, key: value}
        body = {item: content for item, content in forged.items() if item != "plan_sha256"}
        forged["plan_sha256"] = plan_digest(body)
        target = tmp_path / f"{key}.json"
        target.write_text(json.dumps(forged))
        with pytest.raises(ConfigurationError, match="invalid provider or change list"):
            load_plan(target)


def test_plan_invalid_root_and_missing_file(tmp_path):
    target = tmp_path / "missing.json"
    with pytest.raises(ConfigurationError, match="regular file"):
        load_plan(target)
    target.write_text("[]")
    with pytest.raises(ConfigurationError, match="Unsupported"):
        load_plan(target)


def test_plan_store_cleanup_on_write_failure(tmp_path, monkeypatch):
    import app_publisher.core.sync_plan as module

    def explode(*args, **kwargs):
        raise RuntimeError("failed to serialize")

    monkeypatch.setattr(module.json, "dumps", explode)
    target = tmp_path / "plan.json"
    with pytest.raises(RuntimeError, match="serialize"):
        store_plan({"abc": 1}, target)
    assert not target.exists()


def test_report_cleanup_on_write_failure(tmp_path, monkeypatch):
    import app_publisher.core.diagnostics as module

    def explode(*args, **kwargs):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(module.json, "dump", explode)
    target = tmp_path / "report.json"
    with pytest.raises(RuntimeError, match="write failed"):
        save_report(target, {"status": "error"})
    assert not target.exists()


def test_plan_and_report_without_nofollow(tmp_path, monkeypatch):
    import app_publisher.core.sync_plan as plan_module

    monkeypatch.setattr(plan_module.os, "O_NOFOLLOW", 0, raising=False)
    assert store_plan({"test": 1}, tmp_path / "flag-plan.json").exists()
    assert save_report(tmp_path / "flag-report.json", {"ok": True}).exists()

    monkeypatch.delattr(plan_module.os, "O_NOFOLLOW", raising=False)
    assert store_plan({"test": 1}, tmp_path / "plan.json").exists()
    assert save_report(tmp_path / "report.json", {"ok": True}).exists()


def test_google_track_requires_explicit_replacement(project, tmp_path):
    project.google.release.artifact = None
    project.google.release.version_codes = ["42"]
    requests = []

    def responder(request):
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/tracks/internal"):
            return httpx.Response(200, json={"releases": [{"versionCodes": ["41"]}]})
        return httpx.Response(200, json={})

    publisher = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), project.google
    )
    with pytest.raises(UnsafeOperationError, match="confirm_track_replacement"):
        publisher.publish_release(tmp_path, {}, apply=True)
    assert not any(req.method == "PUT" for req in requests)
    project.google.release.confirm_track_replacement = True
    assert publisher.publish_release(tmp_path, {}, apply=True)
    assert any(req.method == "PUT" for req in requests)


def test_google_track_not_found_is_a_valid_new_track(project, tmp_path):
    project.google.release.artifact = None
    project.google.release.version_codes = ["42"]

    def responder(request):
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/tracks/internal"):
            return httpx.Response(404, json={"error": {"message": "Not found"}})
        return httpx.Response(200, json={})

    publisher = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), project.google
    )
    assert publisher.publish_release(tmp_path, {}, apply=True)


def test_google_track_get_fails_closed(project, tmp_path):
    project.google.release.artifact = None
    project.google.release.version_codes = ["42"]

    def responder(request):
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET" and request.url.path.endswith("/tracks/internal"):
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})
        return httpx.Response(200, json={})

    publisher = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), project.google
    )
    with pytest.raises(RemoteAPIError, match="HTTP 403"):
        publisher.publish_release(tmp_path, {}, apply=True)


def test_cli_approved_plan_and_failure_reports(tmp_path, monkeypatch, project):
    import app_publisher.cli as module

    config = tmp_path / "app.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    monkeypatch.setattr(
        module, "generate_plan", lambda engine, provider: {"changes": ["operation"], "schema_version": 1}
    )
    monkeypatch.setattr(module, "store_plan", lambda value, target: target)
    monkeypatch.setattr(module, "load_plan", lambda file: {"provider": "google"})
    monkeypatch.setattr(module, "apply_plan", lambda engine, saved, *, apply: ["operation"])
    runner = CliRunner()
    assert runner.invoke(app, ["plan", str(config), "--output", str(tmp_path / "a.json")]).exit_code == 0
    path = tmp_path / "success.json"
    assert runner.invoke(app, ["apply-plan", str(config), "--report", str(path)]).exit_code == 0
    assert json.loads(path.read_text())["status"] == "success"

    def reject(engine, saved, *, apply):
        raise UnsafeOperationError("blocked")

    monkeypatch.setattr(module, "apply_plan", reject)
    path = tmp_path / "error.json"
    assert runner.invoke(app, ["apply-plan", str(config), "--report", str(path)]).exit_code != 0
    assert json.loads(path.read_text())["status"] == "failed"


def test_manifest_optional_providers(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("test: config\n")
    project.apple = None
    assert asset_manifest(PlannedEngine(project, file)) == {}
    project.google = None
    assert asset_manifest(PlannedEngine(project, file)) == {}


def test_cli_safety_without_reports(tmp_path, monkeypatch, project):
    import app_publisher.cli as module
    from app_publisher.core.publication_engine import PublicationEngine

    config = tmp_path / "app.yaml"
    config.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    runner = CliRunner()

    def reject(self, *, apply, provider):
        raise UnsafeOperationError("No unsafe writes")

    monkeypatch.setattr(PublicationEngine, "synchronize", reject)
    assert runner.invoke(app, ["sync", str(config), "--apply"]).exit_code != 0
    monkeypatch.setattr(module, "load_plan", lambda file: {"provider": "google"})
    monkeypatch.setattr(module, "apply_plan", lambda engine, saved, *, apply: ["completed"])
    assert runner.invoke(app, ["apply-plan", str(config)]).exit_code == 0

    def reject_plan(engine, saved, *, apply):
        raise UnsafeOperationError("Stale remote state")

    monkeypatch.setattr(module, "apply_plan", reject_plan)
    assert runner.invoke(app, ["apply-plan", str(config)]).exit_code != 0


def test_manifest_locale_without_store_metadata(project, tmp_path):
    project.locales["en-US"].apple = None
    project.locales["en-US"].google = None
    file = tmp_path / "config.yaml"
    file.write_text("test: no-localized-assets\n")
    assert asset_manifest(PlannedEngine(project, file)) == {}


def test_diagnostics_redacts_credentials_in_vendor_messages():
    from app_publisher.core.credential_helper import CredentialHelper

    text = "Access denied. Bearer abc.def.ghi password:secret123 token=abcdef api_key=qwerty"
    cleaned = CredentialHelper.redact(text)
    assert "secret123" not in cleaned
    assert "abc.def.ghi" not in cleaned
    assert "abcdef" not in cleaned
    assert "qwerty" not in cleaned
    assert "[REDACTED]" in cleaned
    message = remote_error_message(
        httpx.Response(403, json={"error": {"message": "Bearer sensitive.token.value"}})
    )
    assert "sensitive" not in message


def test_pagination_cycle_detection():
    def responder(request):
        return httpx.Response(200, json={"data": [], "links": {"next": "https://api.test/v1/apps"}})

    client = APIClient("https://api.test/v1", lambda: "token", httpx.MockTransport(responder))
    with pytest.raises(RemoteAPIError, match="cycle detected"):
        client.paginated("apps")


def test_pagination_page_limit():
    index = 0

    def responder(request):
        nonlocal index
        index += 1
        return httpx.Response(
            200, json={"data": [], "links": {"next": f"https://api.test/v1/apps?page={index}"}}
        )

    client = APIClient("https://api.test/v1", lambda: "token", httpx.MockTransport(responder))
    with pytest.raises(RemoteAPIError, match="500 pages"):
        client.paginated("apps")


def test_google_edit_cleanup_preserves_original_failure(project, tmp_path):
    def responder(request):
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "DELETE":
            return httpx.Response(403, json={"error": {"message": "Cleanup denied"}})
        if request.method == "GET" and request.url.path.endswith("/listings"):
            return httpx.Response(500, json={"error": {"message": "Read failed"}})
        return httpx.Response(200, json={})

    publisher = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder), retries=0),
        project.google,
    )
    with pytest.raises(RemoteAPIError, match="Read failed") as failure:
        publisher.synchronize(project, tmp_path, apply=True)
    assert "cleanup also failed" in failure.value.__notes__[0]
    assert diagnose(failure.value, action="sync", provider="google")["cleanup_notes"]


def test_google_cleanup_without_original_raises(project):
    def responder(request):
        return httpx.Response(403, json={"error": {"message": "Cleanup denied"}})

    publisher = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), project.google
    )
    with pytest.raises(RemoteAPIError, match="Cleanup denied"):
        publisher.discard_edit("edit")


def test_google_tester_cleanup_preserves_original_failure():
    def responder(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "GET":
            return httpx.Response(400, json={"error": {"message": "Original tester error"}})
        return httpx.Response(403, json={"error": {"message": "Cleanup denied"}})

    tester = GoogleTesters(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), "com.example.app"
    )
    with pytest.raises(RemoteAPIError, match="Original tester error") as failure:
        tester.synchronize(
            [GoogleTesterGroup(track="internal", google_groups=["team@example.com"])], apply=True
        )
    assert "cleanup also failed" in failure.value.__notes__[0]


def test_google_tester_cleanup_raises_when_dry_run_succeeds():
    def responder(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "edit"})
        if request.method == "DELETE":
            return httpx.Response(403, json={"error": {"message": "Cleanup denied"}})
        return httpx.Response(200, json={"googleGroups": []})

    tester = GoogleTesters(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(responder)), "com.example.app"
    )
    with pytest.raises(RemoteAPIError, match="Cleanup denied"):
        tester.synchronize(
            [GoogleTesterGroup(track="internal", google_groups=["team@example.com"])], apply=False
        )
