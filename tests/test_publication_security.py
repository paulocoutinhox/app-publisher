import subprocess
from pathlib import Path

import pytest

from app_publisher.config import load_project
from app_publisher.core.credential_helper import CredentialHelper
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.android_build import AndroidBuild
from app_publisher.models.apple_build import AppleBuild
from app_publisher.toolchain.build_runner import BuildRunner


def test_credentials_are_hidden_in_diagnostics(monkeypatch):
    monkeypatch.setenv("CUSTOM_UPLOAD_PASSWORD", "unlabelled-private-test-value")
    message = '"private_key": "-----BEGIN PRIVATE KEY-----\nprivate-value\n-----END PRIVATE KEY-----", "password": "quoted-private-value", Bearer bearer-private-value https://example.com/upload?signature=signed-private-value unlabelled-private-test-value'
    cleaned = CredentialHelper.redact(message)
    for private_value in [
        "private-value",
        "quoted-private-value",
        "bearer-private-value",
        "signed-private-value",
        "unlabelled-private-test-value",
    ]:
        assert private_value not in cleaned


def test_config_errors_do_not_echo_private_yaml(tmp_path):
    path = tmp_path / "app.yaml"
    for content in ["secret: invalid-private-value\n", "secret: [invalid-private-value"]:
        path.write_text(content)
        with pytest.raises(ConfigurationError) as failure:
            load_project(path)
        assert "invalid-private-value" not in str(failure.value)
        assert failure.value.__suppress_context__


def test_build_errors_do_not_echo_command_output(tmp_path):
    def fail(command, **options):
        raise subprocess.CalledProcessError(65, command, stderr="unlabelled-private-value")

    with pytest.raises(UnsafeOperationError) as failure:
        BuildRunner(fail).execute(["xcodebuild"], tmp_path)

    assert "unlabelled-private-value" not in str(failure.value)
    assert "65" in str(failure.value)
    assert failure.value.__suppress_context__


def test_build_preparation_and_android_project_directory(tmp_path):
    wrapper = tmp_path / "platform/android/gradlew"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("test")
    wrapper.chmod(0o755)
    (tmp_path / "app.aab").write_bytes(b"test")
    calls = []
    runner = BuildRunner(lambda command, **options: calls.append(command))
    build = AndroidBuild(
        gradle_wrapper=Path("platform/android/gradlew"),
        artifact=Path("app.aab"),
        prepare_commands=[{"executable": "haylen", "arguments": ["prepare"]}],
        finish_commands=[{"executable": "python", "arguments": ["stage.py"]}],
    )

    runner.android(build, tmp_path)

    assert calls[0] == ["haylen", "prepare"]
    assert calls[1][1:3] == ["--project-dir", str(wrapper.parent)]
    assert calls[2] == ["python", "stage.py"]


def test_apple_explicit_distribution_settings(tmp_path):
    (tmp_path / "export.plist").write_text("test")
    calls = []
    runner = BuildRunner(lambda command, **options: calls.append(command))
    build = AppleBuild(
        project="App.xcodeproj",
        scheme="iOS",
        archive_path="app.xcarchive",
        export_path="export",
        export_options="export.plist",
        prepare_commands=[{"executable": "haylen", "arguments": ["prepare"]}],
        allow_provisioning_updates=True,
        build_settings={"DEVELOPMENT_TEAM": "TESTTEAM"},
    )

    runner.apple(build, tmp_path)

    assert calls[0] == ["haylen", "prepare"]
    assert "DEVELOPMENT_TEAM=TESTTEAM" in calls[1]
    assert all("-allowProvisioningUpdates" in command for command in calls[1:])


def test_uploaded_google_version_mismatch_blocks_track_changes(project, tmp_path):
    import httpx

    from app_publisher.core.api_client import APIClient
    from app_publisher.providers.google_publisher import GooglePublisher

    artifact = tmp_path / "app.aab"
    artifact.write_bytes(b"binary")
    project.google.release.artifact = Path("app.aab")
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if request.url.path.endswith("/bundles"):
            return httpx.Response(200, json={"versionCode": 99})
        return httpx.Response(200, json={})

    api = APIClient("https://api.test", lambda: "test", httpx.MockTransport(respond))
    publisher = GooglePublisher(api, project.google)

    with pytest.raises(UnsafeOperationError, match="version_codes"):
        publisher.publish_release(tmp_path, {}, apply=True)

    assert not any(method == "PUT" for method, _ in calls)
    assert calls[-1] == ("DELETE", "/applications/com.demo/edits/edit")
    api.close()


def test_cli_reports_installed_version():
    from typer.testing import CliRunner

    from app_publisher.cli import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.0.1"


@pytest.mark.parametrize(
    "track,submit_for_review,deferred",
    [
        ("internal", False, False),
        ("internal", True, False),
        ("production", False, True),
        ("production", True, False),
    ],
)
def test_google_commit_respects_automatic_internal_processing(
    project, tmp_path, track, submit_for_review, deferred
):
    import httpx

    from app_publisher.core.api_client import APIClient
    from app_publisher.providers.google_publisher import GooglePublisher

    project.google.release.track = track
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        return httpx.Response(200, json={})

    api = APIClient("https://api.test", lambda: "test", httpx.MockTransport(respond))
    publisher = GooglePublisher(api, project.google)
    publisher.publish_release(tmp_path, {}, apply=True, submit_for_review=submit_for_review)
    commit = next(request for request in requests if request.url.path.endswith(":commit"))

    assert commit.url.params.get("changesNotSentForReview") == ("true" if deferred else None)
    assert commit.url.params["changesInReviewBehavior"] == "ERROR_IF_IN_REVIEW"
    assert requests[-2].url.path.endswith(":validate")
    api.close()


def test_missing_expected_build_number_blocks_all_store_calls(project, tmp_path):
    import httpx

    from app_publisher.core.api_client import APIClient
    from app_publisher.providers.google_publisher import GooglePublisher

    project.google.release.artifact = Path("app.aab")
    project.google.release.version_codes = []
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={})

    api = APIClient("https://api.test", lambda: "test", httpx.MockTransport(respond))
    publisher = GooglePublisher(api, project.google)

    with pytest.raises(UnsafeOperationError, match="explicit expected version code"):
        publisher.publish_release(tmp_path, {}, apply=True)

    assert requests == []
    api.close()
