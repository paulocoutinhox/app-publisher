import httpx
import pytest
from pydantic import ValidationError

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_availability import AppleSubscriptionAvailability
from app_publisher.models.apple_subscription_price import AppleSubscriptionPrice
from app_publisher.providers.apple_subscription_availability_publisher import (
    AppleSubscriptionAvailabilityPublisher,
)
from app_publisher.providers.apple_subscriptions import AppleSubscriptions


def client_for(*, existing=False, duplicate=False, countries=None, future=False):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/territories":
            return httpx.Response(200, json={"data": [{"id": "USA"}, {"id": "BRA"}]})
        if request.url.path.endswith("/planAvailabilities"):
            data = (
                [
                    {
                        "id": "availability",
                        "attributes": {"planType": "UPFRONT", "availableInNewTerritories": future},
                    }
                ]
                if existing
                else []
            )
            return httpx.Response(200, json={"data": data * 2 if duplicate else data})
        if request.url.path.endswith("/availableTerritories") and request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": code} for code in (countries or ["USA"])]})
        return httpx.Response(200, json={"data": {"id": "availability"}})

    return APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler)), calls


def test_new_availability_and_read_only_preview():
    api, calls = client_for()
    publisher = AppleSubscriptionAvailabilityPublisher(api)
    item = AppleSubscriptionAvailability(plan_type="upfront", territories=["BRA"])
    assert publisher.synchronize("subscription", [], apply=True) == []
    assert publisher.synchronize("subscription", [item], apply=False)
    assert all(request.method == "GET" for request in calls)
    assert publisher.synchronize("subscription", [item], apply=True)
    import json

    body = json.loads(calls[-1].content)["data"]
    assert body["type"] == "subscriptionPlanAvailabilities"
    assert body["attributes"]["planType"] == "UPFRONT"
    assert body["relationships"]["availableTerritories"]["data"] == [{"type": "territories", "id": "BRA"}]


@pytest.mark.parametrize("countries,future", [(["USA"], False), (["BRA"], True), (["USA"], True)])
def test_existing_availability_updates_require_confirmation(countries, future):
    api, calls = client_for(existing=True, countries=countries, future=future)
    publisher = AppleSubscriptionAvailabilityPublisher(api)
    item = AppleSubscriptionAvailability(plan_type="UPFRONT", territories=["BRA"])
    assert publisher.synchronize("s", [item], apply=False)
    with pytest.raises(UnsafeOperationError, match="confirm_territory_changes"):
        publisher.synchronize("s", [item], apply=True)
    assert all(request.method == "GET" for request in calls)
    item.confirm_territory_changes = True
    assert publisher.synchronize("s", [item], apply=True)
    assert any(request.method == "PATCH" for request in calls)
    api, _ = client_for(existing=True, countries=["BRA"])
    assert AppleSubscriptionAvailabilityPublisher(api).synchronize("s", [item], apply=True) == []


def test_unknown_ambiguous_and_duplicate_plan_declarations():
    item = AppleSubscriptionAvailability(plan_type="upfront", territories=["UNKNOWN"])
    api, _ = client_for()
    with pytest.raises(ConfigurationError, match="unknown"):
        AppleSubscriptionAvailabilityPublisher(api).synchronize("s", [item], apply=True)
    api, _ = client_for(existing=True, duplicate=True)
    item.territories = ["BRA"]
    with pytest.raises(UnsafeOperationError, match="Multiple"):
        AppleSubscriptionAvailabilityPublisher(api).synchronize("s", [item], apply=False)
    with pytest.raises(ValidationError, match="unique"):
        AppleSubscriptionAvailability(plan_type="UPFRONT", territories=["BRA", "BRA"])
    with pytest.raises(ValidationError, match="unique plan"):
        AppleSubscription(product_id="premium", name="Premium", period="one_month", availability=[item, item])


def test_price_identity_requires_plan_and_point():
    class API:
        def paginated(self, *args, **kwargs):
            return [{"attributes": {"startDate": None}}]

    with pytest.raises(RemoteAPIError, match="identity or plan"):
        AppleSubscriptions(API(), "123")._prices(
            "s", "p", [AppleSubscriptionPrice(price_point_id="point")], apply=True, allow_price_changes=True
        )


def test_optional_review_note_is_written_only_when_declared():
    from unittest.mock import Mock

    api = Mock()
    manager = AppleSubscriptions(api, "123")
    current = {
        "id": "subscription",
        "attributes": {
            "name": "Premium",
            "subscriptionPeriod": "ONE_MONTH",
            "familySharable": False,
            "groupLevel": 1,
            "reviewNote": None,
        },
    }
    subscription = AppleSubscription(product_id="premium", name="Premium", period="ONE_MONTH")
    assert manager._subscription("group", subscription, current, apply=True, allow_price_changes=False) == []
    api.request.assert_not_called()
    subscription.review_note = "Reviewer instructions."
    assert manager._subscription("group", subscription, current, apply=True, allow_price_changes=False)
    assert (
        api.request.call_args.kwargs["payload"]["data"]["attributes"]["reviewNote"]
        == "Reviewer instructions."
    )
