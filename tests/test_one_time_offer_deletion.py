from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher import cli
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.google_one_time_offer import GoogleOneTimeOffer
from app_publisher.models.google_one_time_offer_deletion import GoogleOneTimeOfferDeletion
from app_publisher.providers.google_one_time_offers import GoogleOneTimeOffers


class OfferDeletionAPI:
    def __init__(self, ids=None):
        self.ids = ["welcome"] if ids is None else ids
        self.calls = []

    def request(self, method, endpoint, *, params=None, payload=None):
        self.calls.append((method, endpoint, params, payload))
        if method == "GET":
            return {"oneTimeProductOffers": [{"offerId": item} for item in self.ids]}
        return {}

    def close(self):
        return None


def test_offer_deletion_only_explicit_and_idempotent():
    api = OfferDeletionAPI()
    service = GoogleOneTimeOffers(api, "com.example.app")
    unconfirmed = [
        GoogleOneTimeOfferDeletion(product_id="unlock", purchase_option_id="buy", offer_id="welcome")
    ]
    with pytest.raises(UnsafeOperationError, match="confirm_deletion"):
        service.delete(unconfirmed, apply=False)
    assert api.calls == []
    offers = [
        GoogleOneTimeOfferDeletion(
            product_id="unlock", purchase_option_id="buy", offer_id="welcome", confirm_deletion=True
        )
    ]
    changes = ["Google one-time offer: delete unlock/buy/welcome"]
    assert service.delete(offers, apply=False) == changes
    assert len(api.calls) == 1
    assert service.delete(offers, apply=True) == changes
    method, path, _, payload = api.calls[-1]
    assert method == "POST"
    assert (
        path == "applications/com.example.app/oneTimeProducts/unlock/purchaseOptions/buy/offers:batchDelete"
    )
    assert payload == {
        "requests": [
            {
                "packageName": "com.example.app",
                "productId": "unlock",
                "purchaseOptionId": "buy",
                "offerId": "welcome",
            }
        ]
    }
    api.ids = []
    assert service.delete(offers, apply=True) == []
    assert api.calls[-1][0] == "GET"


def test_offer_deletion_rejects_ambiguous_remote_and_batches():
    api = OfferDeletionAPI(ids=["same", "same"])
    service = GoogleOneTimeOffers(api, "com.example.app")
    entry = GoogleOneTimeOfferDeletion(
        product_id="unlock", purchase_option_id="buy", offer_id="same", confirm_deletion=True
    )
    with pytest.raises(UnsafeOperationError, match="duplicate"):
        service.delete([entry], apply=True)
    api = OfferDeletionAPI(ids=[f"deal-{number}" for number in range(102)])
    service = GoogleOneTimeOffers(api, "com.example.app")
    entries = [
        GoogleOneTimeOfferDeletion(
            product_id="unlock", purchase_option_id="buy", offer_id=f"deal-{number}", confirm_deletion=True
        )
        for number in range(102)
    ]
    assert len(service.delete(entries, apply=True)) == 102
    assert [len(call[3]["requests"]) for call in api.calls if call[0] == "POST"] == [100, 2]
    assert service.delete(entries[:1], apply=False) == ["Google one-time offer: delete unlock/buy/deal-0"]


def test_offer_deletion_model_conflicts(project):
    deletion = GoogleOneTimeOfferDeletion(
        product_id="unlock", purchase_option_id="buy", offer_id="deal", confirm_deletion=True
    )
    project.google.one_time_offer_deletions = [deletion]
    with pytest.raises(ValidationError, match="unique"):
        project.google.one_time_offer_deletions = [deletion, deletion]
    example = GoogleOneTimeOffer(
        product_id="unlock",
        purchase_option_id="buy",
        offer_id="deal",
        regions_version="2026/10",
        update_mask=["offerTags"],
        data={"offerTags": []},
    )
    with pytest.raises(ValidationError, match="cannot be changed and deleted"):
        GoogleConfig(
            package_name="com.example.app", one_time_offers=[example], one_time_offer_deletions=[deletion]
        )


def test_offer_deletion_cli_and_engine(project, tmp_path, monkeypatch):
    target = GoogleOneTimeOfferDeletion(
        product_id="unlock", purchase_option_id="buy", offer_id="welcome", confirm_deletion=True
    )
    project.google.one_time_offer_deletions = [target]
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    api = OfferDeletionAPI()
    google = SimpleNamespace(api=api, config=project.google)
    monkeypatch.setattr(engine, "google", lambda: google)
    assert engine.delete_offers(apply=False) == ["Google one-time offer: delete unlock/buy/welcome"]
    assert engine.delete_offers(apply=True) == ["Google one-time offer: delete unlock/buy/welcome"]
    result = []
    monkeypatch.setattr(
        cli,
        "open_engine",
        lambda path: SimpleNamespace(delete_offers=lambda **kwargs: [str(kwargs["apply"])]),
    )
    monkeypatch.setattr(cli, "show_changes", result.extend)
    cli.delete_offers(Path("example.yaml"), apply=True)
    assert result == ["True"]
    project.google = None
    with pytest.raises(ConfigurationError, match="Google Play is not configured"):
        engine.delete_offers(apply=False)
