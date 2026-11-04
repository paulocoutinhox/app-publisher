import hashlib
import json
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.sync_plan import asset_manifest
from app_publisher.core.validation import validate_project
from app_publisher.core.workflow_runner import WorkflowRunner
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
from app_publisher.models.apple_review_screenshot import AppleReviewScreenshot
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.providers.apple_in_app_purchase_manager import AppleInAppPurchaseManager
from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper
from app_publisher.providers.apple_review_screenshot_publisher import AppleReviewScreenshotPublisher
from app_publisher.providers.apple_subscriptions import AppleSubscriptions


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "review.png"
    Image.new("RGB", (200, 300), "coral").save(path)
    return path


def record(image, state="COMPLETE", **attributes):
    return {
        "type": "subscriptionAppStoreReviewScreenshots",
        "id": "screenshot-1",
        "attributes": {
            "sourceFileChecksum": AppleReviewAssetHelper.checksum(image),
            "assetDeliveryState": {"state": state},
            "fileName": f"review-{AppleReviewAssetHelper.checksum(image)}.png",
            **attributes,
        },
    }


@pytest.mark.parametrize(
    "kind,version,relation", [("subscription", "v1", "subscription"), ("iap", "v2", "inAppPurchaseV2")]
)
def test_reservation_upload_commit_and_processing(image, kind, version, relation):
    calls = []
    resource = AppleReviewScreenshotPublisher.definition(kind, "owner")[0]
    states = iter(["UPLOAD_COMPLETE", "COMPLETE"])

    def handler(request):
        calls.append(request)
        if request.url.host == "upload.example.invalid":
            assert request.headers["x-example"] == "upload"
            assert "Authorization" not in request.headers
            assert request.content == image.read_bytes()
            return httpx.Response(200)
        if request.url.path.endswith("/appStoreReviewScreenshot"):
            assert request.url.path.startswith(f"/{version}/")
            return httpx.Response(404, json={})
        if request.method == "POST":
            body = json.loads(request.content)["data"]
            assert body["relationships"][relation]["data"]["id"] == "owner"
            assert body["attributes"]["fileSize"] == image.stat().st_size
            return httpx.Response(
                201,
                json={
                    "data": record(
                        image,
                        "AWAITING_UPLOAD",
                        uploadOperations=[
                            {
                                "method": "PUT",
                                "url": "https://upload.example.invalid/asset",
                                "offset": 0,
                                "length": image.stat().st_size,
                                "requestHeaders": [{"name": "x-example", "value": "upload"}],
                            }
                        ],
                    )
                },
            )
        if request.method == "PATCH":
            assert json.loads(request.content)["data"]["attributes"] == {
                "uploaded": True,
                "sourceFileChecksum": hashlib.md5(image.read_bytes(), usedforsecurity=False).hexdigest(),
            }
            return httpx.Response(200, json={})
        assert request.url.path == f"/v1/{resource}/screenshot-1"
        return httpx.Response(200, json={"data": record(image, next(states))})

    api = APIClient("https://api.test/v1", lambda: "synthetic-token", httpx.MockTransport(handler))
    sleeps = []
    publisher = AppleReviewScreenshotPublisher(api, sleep=sleeps.append)
    item = AppleReviewScreenshot(path=image.name)
    assert publisher.synchronize(kind, "owner", item, image.parent, apply=True)
    assert sleeps == [2]
    assert [request.method for request in calls] == ["GET", "POST", "PUT", "PATCH", "GET", "GET"]


def test_unchanged_preview_and_replacement_guard(image):
    api = Mock()
    api.request.return_value = {"data": record(image)}
    publisher = AppleReviewScreenshotPublisher(api)
    item = AppleReviewScreenshot(path=image.name)
    assert publisher.synchronize("subscription", "owner", item, image.parent, apply=True) == []
    api.request.return_value = {"data": record(image, sourceFileChecksum="other")}
    assert publisher.synchronize("subscription", "owner", item, image.parent, apply=False)
    with pytest.raises(UnsafeOperationError, match="confirm_replacement"):
        publisher.synchronize("subscription", "owner", item, image.parent, apply=True)
    assert all(call.args[0] == "GET" for call in api.request.call_args_list)


def test_confirmed_replacement_and_resume(image, monkeypatch):
    api = Mock()
    item = AppleReviewScreenshot(path=image.name, confirm_replacement=True)
    publisher = AppleReviewScreenshotPublisher(api)
    monkeypatch.setattr(publisher.assets, "wait", Mock())
    monkeypatch.setattr(
        "app_publisher.providers.apple_review_asset_helper.AppleAssetUploadHelper.upload_parts",
        Mock(),
    )
    api.request.side_effect = [
        {"data": record(image, "FAILED")},
        {},
        {"data": record(image, "AWAITING_UPLOAD", uploadOperations=[{"method": "PUT"}])},
        {},
    ]
    assert publisher.synchronize("subscription", "owner", item, image.parent, apply=True)
    assert [call.args[0] for call in api.request.call_args_list] == ["GET", "DELETE", "POST", "PATCH"]
    for state in ("AWAITING_UPLOAD", "UPLOAD_COMPLETE"):
        api.reset_mock(side_effect=True)
        api.request.return_value = {
            "data": record(image, state, sourceFileChecksum=None, uploadOperations=[{}])
        }
        assert publisher.synchronize("subscription", "owner", item, image.parent, apply=True)
        expected = ["GET", "PATCH"] if state == "AWAITING_UPLOAD" else ["GET"]
        assert [call.args[0] for call in api.request.call_args_list] == expected


def test_validation_lookup_and_upload_operation_errors(image):
    item = AppleReviewScreenshot(path=image.name)
    with pytest.raises(ConfigurationError, match="directory"):
        AppleReviewScreenshotPublisher.validate(item, None)
    with pytest.raises(ConfigurationError, match="owner"):
        AppleReviewScreenshotPublisher.definition("unknown", "owner")
    api = Mock()
    api.request.side_effect = RemoteAPIError("denied", status_code=403)
    publisher = AppleReviewScreenshotPublisher(api)
    with pytest.raises(RemoteAPIError, match="denied"):
        publisher.find("screenshot", "v1")
    for operations in (None, [], "invalid"):
        api.request.side_effect = [
            {"data": None},
            {"data": record(image, "AWAITING_UPLOAD", uploadOperations=operations)},
        ]
        with pytest.raises(RemoteAPIError, match="upload operations"):
            publisher.synchronize("subscription", "owner", item, image.parent, apply=True)


@pytest.mark.parametrize(
    "state,checksum,message",
    [
        ("FAILED", None, "could not process"),
        ("UNKNOWN", None, "unknown"),
        ("COMPLETE", None, "checksum"),
        ("COMPLETE", "other", "checksum"),
        ("UPLOAD_COMPLETE", None, "timeout"),
    ],
)
def test_processing_rejects_failures(image, state, checksum, message):
    api = Mock()
    api.request.return_value = {"data": record(image, state, sourceFileChecksum=checksum)}
    publisher = AppleReviewScreenshotPublisher(api, clock=Mock(side_effect=[0, 2]), sleep=Mock())
    with pytest.raises(RemoteAPIError, match=message):
        publisher.assets.wait("screenshots", "image", AppleReviewAssetHelper.checksum(image), 1)


def test_project_validation_and_product_integration(image, project, monkeypatch):
    screenshot = AppleReviewScreenshot(path=image.name)
    subscription = AppleSubscription(
        product_id="premium", name="Premium", period="one_month", review_screenshot=screenshot
    )
    group = AppleSubscriptionGroup(reference_name="Premium", subscriptions=[subscription])
    purchase = AppleInAppPurchase(
        product_id="upgrade", name="Upgrade", purchase_type="non_consumable", review_screenshot=screenshot
    )
    project.apple.subscription_groups = [group]
    project.apple.in_app_purchases = [purchase]
    config_path = image.parent / "publish.yaml"
    engine = PublicationEngine(project, config_path)
    assert image.name in asset_manifest(engine)
    assert image.name in WorkflowRunner(engine).artifacts()
    assert not validate_project(project, config_path, local_files="store")
    screenshot.path = "missing.png"
    assert len(validate_project(project, config_path, local_files="store")) == 2
    assert not validate_project(project, config_path, local_files="none")
    screenshot.path = image.name
    service = Mock(return_value=["review screenshot"])
    monkeypatch.setattr(AppleReviewScreenshotPublisher, "synchronize", service)
    api = Mock()
    api.paginated.return_value = []
    api.request.return_value = {"data": {"id": "created"}}
    manager = AppleInAppPurchaseManager(api, "app")
    assert any(
        "review screenshot" in item
        for item in manager.synchronize([purchase], apply=False, directory=image.parent)
    )
    assert "review screenshot" in manager.synchronize([purchase], apply=True, directory=image.parent)
    api.paginated.return_value = [
        {"id": "purchase", "attributes": {"productId": "upgrade", "inAppPurchaseType": "NON_CONSUMABLE"}}
    ]
    assert "review screenshot" in manager.synchronize([purchase], apply=True, directory=image.parent)
    api.paginated.return_value = []
    assert "review screenshot" in AppleSubscriptions(api, "app").synchronize(
        [group], apply=True, directory=image.parent
    )
    assert any("review screenshot" in item for item in AppleSubscriptions.preview_subscription(subscription))


def test_missing_asset_state_is_rejected():
    with pytest.raises(RemoteAPIError, match="unknown"):
        AppleReviewAssetHelper.state({"attributes": {"assetDeliveryState": None}})
