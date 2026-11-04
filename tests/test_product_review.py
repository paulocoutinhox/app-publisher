from pathlib import Path
from types import SimpleNamespace

import pytest
from test_new_capabilities import MemoryAPI

from app_publisher import cli
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.models.product_localization import ProductLocalization
from app_publisher.providers.apple_product_review import AppleProductReview


def _product_configuration(project):
    project.apple.in_app_purchases = [
        AppleInAppPurchase(
            product_id="lifetime",
            name="Lifetime",
            purchase_type="NON_CONSUMABLE",
            localizations={"en-US": ProductLocalization(name="Lifetime", description="Lifetime access")},
        )
    ]
    project.apple.subscription_groups = [
        AppleSubscriptionGroup(
            reference_name="Premium",
            localizations={"en-US": "Premium"},
            subscriptions=[
                AppleSubscription(
                    product_id="monthly",
                    name="Monthly",
                    period="ONE_MONTH",
                    localizations={
                        "en-US": ProductLocalization(name="Monthly", description="Monthly access")
                    },
                )
            ],
        )
    ]
    return project.apple


def _product_api():
    return MemoryAPI(
        lists={
            "apps/123/inAppPurchasesV2": [{"id": "iap", "attributes": {"productId": "lifetime"}}],
            "inAppPurchases/iap/versions": [
                {"id": "iap-v", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}}
            ],
            "apps/123/subscriptionGroups": [{"id": "group", "attributes": {"referenceName": "Premium"}}],
            "subscriptionGroups/group/versions": [
                {"id": "group-v", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}}
            ],
            "subscriptionGroups/group/subscriptions": [{"id": "sub", "attributes": {"productId": "monthly"}}],
            "subscriptions/sub/versions": [
                {"id": "sub-v", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}}
            ],
            "apps/123/reviewSubmissions": [],
        }
    )


def test_apple_product_review_full_dry_run_and_apply(project):
    manager = AppleProductReview(_product_api(), _product_configuration(project))
    with pytest.raises(UnsafeOperationError, match="first in-app purchase"):
        manager.submit("IOS", apply=False, first_purchase_review_completed=False)
    changes = manager.submit("IOS", apply=False, first_purchase_review_completed=True)
    assert len(changes) == 3
    assert not any(call[0] == "POST" for call in manager.api.calls)
    assert len(manager.submit("MAC_OS", apply=True, first_purchase_review_completed=True)) == 3
    created = [
        (method, path, payload["payload"])
        for method, path, payload in manager.api.calls
        if method in ("POST", "PATCH")
    ]
    assert created[0][2]["data"]["attributes"]["platform"] == "MAC_OS"
    assert [item[2]["data"]["relationships"].keys() for item in created[1:4]] == [
        dict.fromkeys(["reviewSubmission", name]).keys()
        for name in ("inAppPurchaseVersion", "subscriptionGroupVersion", "subscriptionVersion")
    ]
    assert created[-1][:2] == ("PATCH", "reviewSubmissions/created")


def test_apple_product_review_no_candidates_or_unlocalized(project):
    subject = AppleProductReview(MemoryAPI(), project.apple)
    assert subject.submit("IOS", apply=True, first_purchase_review_completed=True) == []
    project.apple.in_app_purchases = [
        AppleInAppPurchase(product_id="life", name="Life", purchase_type="NON_CONSUMABLE")
    ]
    subject.api.lists["apps/123/inAppPurchasesV2"] = []
    assert subject.candidates() == []


def test_apple_product_review_missing_resources(project):
    config = _product_configuration(project)
    api = _product_api()
    manager = AppleProductReview(api, config)
    api.lists["apps/123/inAppPurchasesV2"] = []
    with pytest.raises(UnsafeOperationError, match="not registered: lifetime"):
        manager.candidates()
    api.lists["apps/123/inAppPurchasesV2"] = [{"id": "iap", "attributes": {"productId": "lifetime"}}]
    api.lists["apps/123/subscriptionGroups"] = []
    with pytest.raises(UnsafeOperationError, match="group is not registered"):
        manager.candidates()
    api.lists["apps/123/subscriptionGroups"] = [{"id": "group", "attributes": {"referenceName": "Premium"}}]
    api.lists["subscriptionGroups/group/subscriptions"] = []
    with pytest.raises(UnsafeOperationError, match="subscription is not registered"):
        manager.candidates()


def test_apple_product_review_requires_exactly_one_draft(project):
    config = _product_configuration(project)
    api = _product_api()
    manager = AppleProductReview(api, config)
    api.lists["inAppPurchases/iap/versions"] = [{"id": "approved", "attributes": {"state": "APPROVED"}}]
    with pytest.raises(UnsafeOperationError, match="exactly one"):
        manager.candidates()
    api.lists["inAppPurchases/iap/versions"] = [
        {"id": "a", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}},
        {"id": "b", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}},
    ]
    with pytest.raises(UnsafeOperationError, match="exactly one"):
        manager.candidates()


def test_apple_product_review_existing_active_and_different_platform(project):
    api = _product_api()
    manager = AppleProductReview(api, _product_configuration(project))
    api.lists["apps/123/reviewSubmissions"] = [
        {"id": "other", "attributes": {"platform": "MAC_OS", "state": "WAITING_FOR_REVIEW"}}
    ]
    assert len(manager.submit("IOS", apply=False, first_purchase_review_completed=True)) == 3
    with pytest.raises(UnsafeOperationError, match="already active"):
        manager.submit("MAC_OS", apply=False, first_purchase_review_completed=True)
    api.lists["apps/123/reviewSubmissions"][0]["attributes"]["state"] = "COMPLETE"
    assert len(manager.submit("MAC_OS", apply=False, first_purchase_review_completed=True)) == 3


def test_apple_product_review_unlocalized_group_and_subscription(project):
    config = _product_configuration(project)
    config.in_app_purchases = []
    config.subscription_groups[0].localizations = {}
    config.subscription_groups[0].subscriptions = []
    api = MemoryAPI(
        lists={
            "apps/123/subscriptionGroups": [{"id": "g", "attributes": {"referenceName": "Premium"}}],
            "subscriptionGroups/g/subscriptions": [],
        }
    )
    manager = AppleProductReview(api, config)
    assert manager.candidates() == []
    config.subscription_groups[0].subscriptions = [
        AppleSubscription(product_id="no-metadata", name="No metadata", period="ONE_MONTH")
    ]
    assert manager.candidates() == []


def test_review_products_engine_and_cli(monkeypatch, project, tmp_path):
    runner = SimpleNamespace(identify=lambda: None, api=SimpleNamespace(close=lambda: None))
    calls = []
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: runner)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleProductReview",
        lambda api, config: SimpleNamespace(
            submit=lambda *args, **kwargs: calls.append(kwargs) or ["reviewed"]
        ),
    )
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    assert engine.review_products(apply=False, platform="IOS", first_purchase_review_completed=True) == [
        "reviewed"
    ]
    assert calls == [{"apply": False, "first_purchase_review_completed": True}]
    project.apple = None
    with pytest.raises(ConfigurationError, match="requires an Apple app"):
        engine.review_products(apply=False, platform="IOS", first_purchase_review_completed=True)
    result = []
    monkeypatch.setattr(
        cli,
        "open_engine",
        lambda config: SimpleNamespace(
            review_products=lambda **kwargs: result.append(kwargs) or ["reviewed"]
        ),
    )
    monkeypatch.setattr(cli, "show_changes", lambda changes: result.extend(changes))
    cli.review_products(
        Path("project.yaml"), platform="TV_OS", first_purchase_review_completed=True, apply=False
    )
    assert result == [
        {"apply": False, "platform": "TV_OS", "first_purchase_review_completed": True},
        "reviewed",
    ]
