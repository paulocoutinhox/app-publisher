import json

import httpx
import pytest
from pydantic import ValidationError

from app_publisher.core.api_client import APIClient
from app_publisher.models.google_monetization_product import GoogleMonetizationProduct
from app_publisher.models.google_one_time_offer import GoogleOneTimeOffer
from app_publisher.models.google_subscription_offer import GoogleSubscriptionOffer
from app_publisher.providers.google_monetization import GoogleMonetization


def test_list_masks_are_encoded_only_for_the_api():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"error": {"message": "not found"}})
        assert request.url.params["updateMask"] == "listings,basePlans"
        assert json.loads(request.content)["basePlans"] == []
        return httpx.Response(200, json={})

    api = APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler))
    product = GoogleMonetizationProduct(
        product_id="premium",
        update_mask=["listings", "basePlans"],
        regions_version="version",
        data={"listings": [], "basePlans": []},
    )
    GoogleMonetization(api, "com.example").synchronize([product], [], apply=True)
    assert product.model_dump()["update_mask"] == ["listings", "basePlans"]
    assert any(request.method == "PATCH" for request in requests)


@pytest.mark.parametrize("mask", ["listings,basePlans", "listings", []])
def test_scalar_or_empty_masks_are_rejected(mask):
    for model, fields in (
        (GoogleMonetizationProduct, {}),
        (GoogleSubscriptionOffer, {"base_plan_id": "monthly", "offer_id": "offer"}),
        (GoogleOneTimeOffer, {"purchase_option_id": "buy", "offer_id": "offer"}),
    ):
        with pytest.raises(ValidationError):
            model(
                product_id="premium",
                update_mask=mask,
                regions_version="version",
                data={"listings": []},
                **fields,
            )
