import json

import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion
from app_publisher.providers.apple_publisher import ApplePublisher


def apple_resource(type, id, attrs):
    return {"type": type, "id": id, "attributes": attrs}


def test_apple_localizations_diff_and_update(project, tmp_path):
    def handler(req):
        path = req.url.path
        if path == "/apps/123":
            return httpx.Response(200, json={"data": apple_resource("apps", "123", {"bundleId": "com.demo"})})
        if path == "/apps/123/appInfos":
            return httpx.Response(200, json={"data": [apple_resource("appInfos", "info", {})]})
        if path == "/appInfos/info/appInfoLocalizations":
            return httpx.Response(
                200,
                json={
                    "data": [
                        apple_resource(
                            "appInfoLocalizations",
                            "locinfo",
                            {"locale": "en-US", "name": "Old", "subtitle": "Other"},
                        )
                    ]
                },
            )
        if path == "/apps/123/appStoreVersions":
            return httpx.Response(
                200,
                json={
                    "data": [
                        apple_resource(
                            "appStoreVersions",
                            "version",
                            {
                                "platform": "IOS",
                                "versionString": "2.0",
                                "appVersionState": "PREPARE_FOR_SUBMISSION",
                                "releaseType": "MANUAL",
                            },
                        )
                    ]
                },
            )
        if path == "/appStoreVersions/version/appStoreVersionLocalizations":
            return httpx.Response(
                200,
                json={
                    "data": [
                        apple_resource(
                            "appStoreVersionLocalizations",
                            "locversion",
                            {"locale": "en-US", "description": "Old"},
                        )
                    ]
                },
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    publisher = ApplePublisher(
        APIClient("https://api.test", lambda: "a", httpx.MockTransport(rec)), project.apple
    )
    changes = publisher.synchronize(project, tmp_path, apply=False)
    assert len(changes) == 3
    assert not [call for call in rec.calls if call.method in {"POST", "PATCH"}]
    assert publisher.synchronize(project, tmp_path, apply=True) == changes
    assert len([call for call in rec.calls if call.method == "PATCH"]) == 2


def test_apple_new_version_and_localizations(project, tmp_path):
    def handler(req):
        path = req.url.path
        if path == "/apps/123":
            return httpx.Response(200, json={"data": apple_resource("apps", "123", {"bundleId": "com.demo"})})
        if path == "/apps/123/appInfos":
            return httpx.Response(200, json={"data": [apple_resource("appInfos", "info", {})]})
        if path == "/appInfos/info/appInfoLocalizations":
            return httpx.Response(200, json={"data": []})
        if path == "/apps/123/appStoreVersions":
            return httpx.Response(200, json={"data": []})
        if path == "/appStoreVersions/new/appStoreVersionLocalizations":
            return httpx.Response(200, json={"data": []})
        if req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "new"}})
        return httpx.Response(204)

    rec = Recorder(handler)
    publisher = ApplePublisher(
        APIClient("https://api.test", lambda: "a", httpx.MockTransport(rec)), project.apple
    )
    assert publisher.ensure_version(project.apple.versions[0], [], apply=False) is None
    assert publisher.synchronize(project, tmp_path, apply=True)
    assert len([call for call in rec.calls if call.method == "POST"]) == 3


def test_apple_refuses_wrong_identity_and_immutable_version(project):
    client = APIClient(
        "https://api.test",
        lambda: "a",
        httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": apple_resource("apps", "123", {"bundleId": "WRONG"})})
        ),
    )
    with pytest.raises(UnsafeOperationError, match="bundle"):
        ApplePublisher(client, project.apple).identify()
    handler = ApplePublisher(client, project.apple)
    for state in ["READY_FOR_DISTRIBUTION", "IN_REVIEW", "WAITING_FOR_REVIEW"]:
        with pytest.raises(UnsafeOperationError):
            handler.ensure_version(
                project.apple.versions[0],
                [
                    apple_resource(
                        "appStoreVersions",
                        "v",
                        {"platform": "IOS", "versionString": "2.0", "appVersionState": state},
                    )
                ],
                apply=True,
            )
    assert (
        handler.version_fields("Description", "Notes", project.locales["en-US"].apple)["whatsNew"] == "Notes"
    )


def test_apple_build_upload(project, tmp_path):
    artifact = tmp_path / "demo.ipa"
    artifact.write_bytes(b"binary")
    v = AppleVersion(platform="IOS", version="2.0", artifact="demo.ipa", build_number="42")

    def handler(req):
        if req.url.path == "/buildUploads":
            return httpx.Response(201, json={"data": {"id": "build"}})
        if req.url.path == "/buildUploadFiles":
            attributes = json.loads(req.content)["data"]["attributes"]
            assert attributes == {
                "assetType": "ASSET",
                "fileName": "demo.ipa",
                "fileSize": 6,
                "uti": "com.apple.ipa",
            }
            return httpx.Response(
                201,
                json={
                    "data": apple_resource(
                        "buildUploadFiles",
                        "file",
                        {
                            "uploadOperations": [
                                {"offset": 0, "length": 6, "method": "PUT", "url": "https://upload.test/file"}
                            ]
                        },
                    )
                },
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = ApplePublisher(APIClient("https://api.test", lambda: "a", httpx.MockTransport(rec)), project.apple)
    assert pub.upload_build(v, tmp_path) == "build"
    assert any(req.url.host == "upload.test" for req in rec.calls)
    with pytest.raises(ConfigurationError, match="artifact"):
        pub.upload_build(project.apple.versions[0], tmp_path)
