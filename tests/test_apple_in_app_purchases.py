import httpx
import pytest

from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
from app_publisher.providers.apple_in_app_purchase_manager import AppleInAppPurchaseManager


def purchase(name="Premium", purchase_type="NON_CONSUMABLE"):
    return AppleInAppPurchase(
        product_id="premium",
        name=name,
        purchase_type=purchase_type,
        review_note="For reviewers",
        available_in_all_territories=True,
    )


def test_in_app_purchase_creation_and_dry_run():
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(201, json={"data": {"id": "purchase-1"}})

    api = APIClient("https://api.test/v1", lambda: "token", httpx.MockTransport(handler))
    manager = AppleInAppPurchaseManager(api, "123")
    expected = ["Apple in-app purchase: create premium"]
    assert manager.synchronize([], apply=True) == []
    assert manager.synchronize([purchase()], apply=False) == expected
    assert len(calls) == 1
    assert manager.synchronize([purchase()], apply=True) == expected
    sent = calls[-1]
    assert sent.url.path == "/v2/inAppPurchases"
    assert b'"NON_CONSUMABLE"' in sent.content
    assert b'"app"' in sent.content


def test_in_app_purchase_updates_and_unchanged():
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "product-123",
                            "attributes": {
                                "productId": "premium",
                                "inAppPurchaseType": "NON_CONSUMABLE",
                                "name": "Basic",
                                "reviewNote": "For reviewers",
                                "availableInAllTerritories": True,
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": {"id": "product-123"}})

    api = APIClient("https://api.test/v1", lambda: "token", httpx.MockTransport(handler))
    manager = AppleInAppPurchaseManager(api, "123")
    assert manager.synchronize([purchase("Basic")], apply=True) == []
    assert manager.synchronize([purchase()], apply=False) == ["Apple in-app purchase: update premium: name"]
    assert manager.synchronize([purchase()], apply=True) == ["Apple in-app purchase: update premium: name"]
    assert calls[-1].url.path == "/v2/inAppPurchases/product-123"
    assert b'"name":"Premium"' in calls[-1].content
    assert len([item for item in calls if item.method == "PATCH"]) == 1


def test_in_app_purchase_immutable_type():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "p", "attributes": {"productId": "premium", "inAppPurchaseType": "CONSUMABLE"}}
                ]
            },
        )

    manager = AppleInAppPurchaseManager(
        APIClient("https://api.test/v1", lambda: "t", httpx.MockTransport(handler)), "123"
    )
    with pytest.raises(UnsafeOperationError, match="immutable"):
        manager.synchronize([purchase()], apply=False)


def test_versioned_http_requires_v1():
    api = APIClient(
        "https://api.test", lambda: "t", httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    with pytest.raises(RemoteAPIError, match="v1 base"):
        api.request("GET", "foo", version="v2")


def test_engine_synchronizes_apple_in_app_purchases(project, tmp_path, monkeypatch):
    project.apple.in_app_purchases = [purchase()]
    calls = []

    class FakeManager:
        def __init__(self, api, app_id):
            calls.append(app_id)

        def synchronize(self, purchases, *, apply, directory):
            assert directory == tmp_path
            calls.append((purchases[0].product_id, apply))
            return ["purchase synchronized"]

    class FakeHandler:
        config = project.apple
        api = type("Api", (), {"close": lambda self: None})()

        def synchronize(self, project, directory, *, apply):
            return []

    monkeypatch.setattr(PublicationEngine, "apple", lambda self: FakeHandler())
    monkeypatch.setattr("app_publisher.core.publication_engine.AppleInAppPurchaseManager", FakeManager)
    assert PublicationEngine(project, tmp_path / "config.yaml").synchronize(
        apply=False, provider="apple"
    ) == ["purchase synchronized"]
    assert calls == ["123", ("premium", False)]
