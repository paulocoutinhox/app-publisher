import base64

import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.providers.firebase_publisher import FirebasePublisher


def test_firebase_sync_existing_apps(project, tmp_path):
    def handler(req):
        if req.url.path == "/projects/demo-123456":
            return httpx.Response(200, json={"projectId": "demo-123456"})
        if req.url.path.endswith("/iosApps"):
            return httpx.Response(
                200, json={"apps": [{"bundleId": "com.demo", "name": "projects/demo-123456/iosApps/ios"}]}
            )
        if req.url.path.endswith("/androidApps"):
            return httpx.Response(
                200,
                json={
                    "apps": [{"packageName": "com.demo", "name": "projects/demo-123456/androidApps/android"}]
                },
            )
        if req.url.path.endswith("/config"):
            return httpx.Response(
                200, json={"configFileContents": base64.b64encode(b"configuration").decode()}
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    client = APIClient("https://firebase.test", lambda: "token", httpx.MockTransport(rec))
    cloud = APIClient("https://cloud.test", lambda: "token", httpx.MockTransport(rec))
    pub = FirebasePublisher(client, cloud, project.firebase)
    assert len(pub.synchronize(tmp_path, apply=False)) == 2
    assert len(pub.synchronize(tmp_path, apply=True)) == 2
    assert (tmp_path / "out" / "plist").read_bytes() == b"configuration"
    assert (tmp_path / "out" / "json").read_bytes() == b"configuration"
    assert not any(req.method == "POST" for req in rec.calls)


def test_firebase_creates_apps_with_operations(project, tmp_path):
    def handler(req):
        if req.url.path == "/projects/demo-123456":
            return httpx.Response(200, json={"projectId": "demo-123456"})
        if req.method == "GET" and req.url.path.endswith("Apps"):
            return httpx.Response(200, json={"apps": []})
        if req.method == "POST" and req.url.path.endswith("Apps"):
            platform = "iosApps" if req.url.path.endswith("iosApps") else "androidApps"
            return httpx.Response(
                200,
                json={
                    "name": "operations/created",
                    "done": True,
                    "response": {"name": f"projects/demo-123456/{platform}/new"},
                },
            )
        if req.url.path.endswith("/config"):
            return httpx.Response(200, json={"configFileContents": base64.b64encode(b"ok").decode()})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    client = APIClient("https://firebase.test", lambda: "token", httpx.MockTransport(rec))
    pub = FirebasePublisher(client, client, project.firebase)
    assert len(pub.synchronize(tmp_path, apply=True)) == 2
    assert len([req for req in rec.calls if req.method == "POST"]) == 2


def test_firebase_create_project_and_failures(project):
    project.firebase.create_if_missing = True

    def handler(req):
        if req.method == "GET" and req.url.path == "/projects/demo-123456":
            return httpx.Response(404, json={"error": "Not Found"})
        if req.method == "POST":
            return httpx.Response(
                200,
                json={"name": "operations/ok", "done": True, "response": {"name": "projects/demo-123456"}},
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    client = APIClient("https://firebase.test", lambda: "t", httpx.MockTransport(rec))
    cloud = APIClient("https://cloud.test", lambda: "t", httpx.MockTransport(rec))
    pub = FirebasePublisher(client, cloud, project.firebase)
    pub.ensure_project()
    assert len([req for req in rec.calls if req.method == "POST"]) == 2
    project.firebase.create_if_missing = False
    with pytest.raises(ConfigurationError, match="does not exist"):
        pub.ensure_project()


def test_firebase_operation_errors(project, monkeypatch):
    client = APIClient(
        "https://firebase.test",
        lambda: "t",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"done": False})),
    )
    pub = FirebasePublisher(client, client, project.firebase)
    with pytest.raises(RemoteAPIError, match="no operation name"):
        pub.wait_operation({})
    with pytest.raises(RemoteAPIError, match="operation failed"):
        pub.wait_operation({"name": "operations/x", "done": True, "error": {"code": 1}})
    with pytest.raises(RemoteAPIError, match="no resource"):
        pub.wait_operation({"name": "operations/x", "done": True})
    monkeypatch.setattr("app_publisher.providers.firebase_publisher.time.sleep", lambda _: None)
    with pytest.raises(RemoteAPIError, match="polling window"):
        pub.wait_operation({"name": "operations/x"})
