import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_release import GoogleRelease
from app_publisher.providers.google_publisher import GooglePublisher


def test_google_listing_diff_and_commit(project, tmp_path):
    def handler(req):
        if req.method == "POST" and req.url.path == "/applications/com.demo/edits":
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET" and req.url.path.endswith("/listings"):
            return httpx.Response(200, json={"listings": [{"language": "en-US", "title": "Old"}]})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(rec)), project.google
    )
    changes = pub.synchronize(project, tmp_path, apply=False)
    assert changes == ["Google en-US: update title, shortDescription, fullDescription"]
    assert not any(req.method == "PATCH" for req in rec.calls)
    assert pub.synchronize(project, tmp_path, apply=True) == changes
    assert any(req.method == "PATCH" for req in rec.calls)
    assert any(":commit" in req.url.path for req in rec.calls)


def test_google_image_upload_and_datasafety(project, tmp_path, png):
    project.locales["en-US"].google.images = {"phoneScreenshots": ["shot.png"]}
    project.google.data_safety_csv = "safety.csv"
    (tmp_path / "safety.csv").write_text("field,answer", encoding="utf-8")

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET":
            return httpx.Response(200, json={"listings": []})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    changes = pub.synchronize(project, tmp_path, apply=True)
    assert any("phoneScreenshots" in item for item in changes)
    assert any("Data Safety" in item for item in changes)
    assert any(
        req.url.host == "androidpublisher.googleapis.com" and req.method == "POST" for req in rec.calls
    )
    assert any(req.url.path.endswith("/dataSafety") and req.method == "POST" for req in rec.calls)


def test_google_releases_rollouts_testers_and_bundle(project, tmp_path):
    artifact = tmp_path / "app.aab"
    artifact.write_bytes(b"bundle")
    project.google.release = GoogleRelease(
        track="internal",
        status="inProgress",
        rollout_fraction=0.1,
        artifact="app.aab",
        version_codes=["32"],
        testers=["testers@example.com"],
    )

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.url.path.endswith("/bundles"):
            return httpx.Response(200, json={"versionCode": 32})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    assert pub.publish_release(tmp_path, {"en-US": "Changes"}, apply=False)
    assert pub.publish_release(tmp_path, {"en-US": "Changes"}, apply=True)
    requests = [req for req in rec.calls if req.method == "PUT"]
    assert any(
        req.url.path.endswith("/tracks/internal") and b'"userFraction":0.1' in req.content for req in requests
    )
    assert any(req.url.path.endswith("/testers/internal") for req in requests)
    assert any(req.url.host == "androidpublisher.googleapis.com" for req in rec.calls)


def test_google_release_needs_version_and_cleanup(project, tmp_path):
    project.google.release.version_codes = []

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    with pytest.raises(UnsafeOperationError, match="version codes"):
        pub.publish_release(tmp_path, {}, apply=True)
    assert any(req.method == "DELETE" for req in rec.calls)
    project.google.release = None
    with pytest.raises(UnsafeOperationError, match="not configured"):
        pub.publish_release(tmp_path, {}, apply=False)


def test_google_api_rejections(project, tmp_path, png):
    pub = GooglePublisher(
        APIClient(
            "https://api.test",
            lambda: "t",
            httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "blocked"})),
        ),
        project.google,
    )
    with pytest.raises(RemoteAPIError):
        pub.synchronize(project, tmp_path, apply=True)
    with pytest.raises(RemoteAPIError, match="image upload"):
        pub.upload_image("e", "en-US", "phoneScreenshots", png)
