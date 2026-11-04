import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.providers.apple_information import AppleInformation


def test_information_categories_age_rating_and_updates():
    def handler(req):
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.url.path == "/appInfos/info" and req.method == "GET":
            return httpx.Response(
                200, json={"data": {"relationships": {"primaryCategory": {"data": {"id": "old"}}}}}
            )
        if req.url.path.endswith("/ageRatingDeclaration"):
            return httpx.Response(200, json={"data": {"id": "rating", "attributes": {"advertising": False}}})
        return httpx.Response(200, json={})

    recorder = Recorder(handler)
    client = APIClient("https://test.example", lambda: "token", httpx.MockTransport(recorder))
    manager = AppleInformation(client, "123")
    assert manager.synchronize({}, {}, apply=True) == []
    expected = manager.synchronize({"primaryCategory": "new"}, {"advertising": True}, apply=False)
    assert len(expected) == 2
    assert not [r for r in recorder.calls if r.method == "PATCH"]
    assert manager.synchronize({"primaryCategory": "new"}, {"advertising": True}, apply=True) == expected
    assert len([r for r in recorder.calls if r.method == "PATCH"]) == 2
    with pytest.raises(ConfigurationError, match="category fields"):
        manager.synchronize({"invented": "new"}, {}, apply=False)
    with pytest.raises(ConfigurationError, match="age rating fields"):
        manager.synchronize({}, {"invented": True}, apply=False)
    bad = APIClient(
        "https://test.example",
        lambda: "token",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})),
    )
    with pytest.raises(ConfigurationError, match="exactly one"):
        AppleInformation(bad, "123").synchronize({"primaryCategory": "FOOD"}, {}, apply=True)


def test_information_is_idempotent():
    def handler(req):
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.url.path == "/appInfos/info":
            return httpx.Response(
                200, json={"data": {"relationships": {"primaryCategory": {"data": {"id": "SAME"}}}}}
            )
        return httpx.Response(200, json={"data": {"id": "rating", "attributes": {"advertising": True}}})

    recorder = Recorder(handler)
    api = APIClient("https://test.example", lambda: "token", httpx.MockTransport(recorder))
    assert (
        AppleInformation(api, "123").synchronize(
            {"primaryCategory": "SAME"}, {"advertising": True}, apply=True
        )
        == []
    )
    assert not [r for r in recorder.calls if r.method == "PATCH"]


def test_information_individual_sections():
    def handler(req):
        if req.url.path.endswith("/appInfos"):
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if req.url.path.endswith("/ageRatingDeclaration"):
            return httpx.Response(200, json={"data": {"id": "rating", "attributes": {"advertising": False}}})
        return httpx.Response(200, json={"data": {"relationships": {}}})

    api = APIClient("https://test.example", lambda: "token", httpx.MockTransport(handler))
    manager = AppleInformation(api, "123")
    assert len(manager.synchronize({}, {"advertising": True}, apply=False)) == 1
    assert len(manager.synchronize({"primaryCategory": "NEW"}, {}, apply=False)) == 1
