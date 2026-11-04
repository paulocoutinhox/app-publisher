from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.google_subscription_offer import GoogleSubscriptionOffer
from app_publisher.models.google_subscription_offer_deletion import GoogleSubscriptionOfferDeletion
from app_publisher.providers.google_subscription_offers import GoogleSubscriptionOffers


class SubscriptionOfferAPI:
    def __init__(self):
        self.calls = []
        self.result = {
            "packageName": "com.demo",
            "productId": "premium",
            "basePlanId": "monthly",
            "offerId": "trial",
            "state": "DRAFT",
        }
        self.error = None

    def request(self, method, path):
        self.calls.append((method, path))
        if method == "GET":
            if self.error:
                raise RemoteAPIError(self.error)
            return self.result
        return {}

    def close(self):
        return None


def test_delete_subscription_draft_with_explicit_confirmation():
    api = SubscriptionOfferAPI()
    provider = GoogleSubscriptionOffers(api, "com.demo")
    unsafe = GoogleSubscriptionOfferDeletion(product_id="premium", base_plan_id="monthly", offer_id="trial")
    with pytest.raises(UnsafeOperationError, match="confirm_deletion"):
        provider.delete([unsafe], apply=False)
    assert api.calls == []
    entry = GoogleSubscriptionOfferDeletion(
        product_id="premium", base_plan_id="monthly", offer_id="trial", confirm_deletion=True
    )
    assert provider.delete([entry], apply=False) == [
        "Google subscription offer: delete premium/monthly/trial"
    ]
    assert api.calls == [
        ("GET", "applications/com.demo/subscriptions/premium/basePlans/monthly/offers/trial")
    ]
    assert provider.delete([entry], apply=True) == ["Google subscription offer: delete premium/monthly/trial"]
    assert api.calls[-1] == (
        "DELETE",
        "applications/com.demo/subscriptions/premium/basePlans/monthly/offers/trial",
    )
    api.error = "GET offers/trial returned HTTP 404"
    assert provider.delete([entry], apply=True) == []
    api.error = "GET offers/trial returned HTTP 500"
    with pytest.raises(RemoteAPIError, match="500"):
        provider.delete([entry], apply=True)


def test_subscription_offer_deletion_rejects_identity_and_published():
    api = SubscriptionOfferAPI()
    provider = GoogleSubscriptionOffers(api, "com.demo")
    entry = GoogleSubscriptionOfferDeletion(
        product_id="premium", base_plan_id="monthly", offer_id="trial", confirm_deletion=True
    )
    api.result = {**api.result, "packageName": "com.other"}
    with pytest.raises(UnsafeOperationError, match="identity mismatch"):
        provider.delete([entry], apply=True)
    api.result = {**api.result, "packageName": "com.demo", "state": "ACTIVE"}
    with pytest.raises(UnsafeOperationError, match="Only draft"):
        provider.delete([entry], apply=True)


def test_subscription_deletion_schema_conflicts(project):
    deletion = GoogleSubscriptionOfferDeletion(
        product_id="premium", base_plan_id="monthly", offer_id="trial", confirm_deletion=True
    )
    with pytest.raises(ValidationError, match="deletions must be unique"):
        GoogleConfig(package_name="com.demo", subscription_offer_deletions=[deletion, deletion])
    offer = GoogleSubscriptionOffer(
        product_id="premium",
        base_plan_id="monthly",
        offer_id="trial",
        regions_version="2026/10",
        update_mask=["phases"],
        data={"phases": []},
    )
    with pytest.raises(ValidationError, match="cannot be changed and deleted"):
        GoogleConfig(
            package_name="com.demo", subscription_offer_deletions=[deletion], subscription_offers=[offer]
        )


def test_engine_routes_both_offer_deletion_types(project, tmp_path, monkeypatch):
    project.google.subscription_offer_deletions = [
        GoogleSubscriptionOfferDeletion(
            product_id="premium", base_plan_id="monthly", offer_id="trial", confirm_deletion=True
        )
    ]
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    api = SubscriptionOfferAPI()
    monkeypatch.setattr(engine, "google", lambda: SimpleNamespace(api=api, config=project.google))
    assert engine.delete_offers(apply=False) == ["Google subscription offer: delete premium/monthly/trial"]
