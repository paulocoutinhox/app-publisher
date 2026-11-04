from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_offer_code_custom_batch import AppleOfferCodeCustomBatch
from app_publisher.models.apple_offer_code_one_time_batch import AppleOfferCodeOneTimeBatch
from app_publisher.models.apple_subscription_offer_code import AppleSubscriptionOfferCode
from app_publisher.providers.apple_offer_code_batches import AppleOfferCodeBatches
from app_publisher.providers.apple_subscription_intro_offers import AppleSubscriptionIntroOffers


class OfferAPI:
    def __init__(self, custom=None, one_time=None):
        self.custom = custom if custom is not None else []
        self.one_time = one_time if one_time is not None else []
        self.calls = []

    def paginated(self, path, *, params):
        self.calls.append(("GET", path, params))
        if path.endswith("/customCodes"):
            return self.custom
        if path.endswith("/oneTimeUseCodes"):
            return self.one_time
        return []

    def request(self, method, path, *, payload):
        self.calls.append((method, path, payload))
        return {"data": {"id": "offer-id"}}


def test_offer_code_batches_create_and_skip_existing():
    api = OfferAPI()
    provider = AppleOfferCodeBatches(api)
    custom = [AppleOfferCodeCustomBatch(custom_code="PROMO2026", number_of_codes=50, confirm_creation=True)]
    one_time = [
        AppleOfferCodeOneTimeBatch(
            number_of_codes=500, expiration_date="2026-12-20", environment="SANDBOX", confirm_creation=True
        )
    ]
    assert len(provider.synchronize("code-id", custom, one_time, apply=False)) == 2
    assert not any(item[0] == "POST" for item in api.calls)
    assert len(provider.synchronize("code-id", custom, one_time, apply=True)) == 2
    posts = [call for call in api.calls if call[0] == "POST"]
    assert len(posts) == 2
    assert posts[0][2] == {
        "data": {
            "type": "subscriptionOfferCodeCustomCodes",
            "attributes": {"customCode": "PROMO2026", "numberOfCodes": 50},
            "relationships": {"offerCode": {"data": {"type": "subscriptionOfferCodes", "id": "code-id"}}},
        }
    }
    assert posts[1][2]["data"]["attributes"] == {
        "numberOfCodes": 500,
        "expirationDate": "2026-12-20",
        "environment": "SANDBOX",
    }
    api.custom = [{"attributes": {"customCode": "PROMO2026", "numberOfCodes": 50}}]
    api.one_time = [
        {"attributes": {"numberOfCodes": 500, "expirationDate": "2026-12-20", "environment": "SANDBOX"}}
    ]
    api.calls.clear()
    assert provider.synchronize("code-id", custom, one_time, apply=True) == []
    assert not any(call[0] == "POST" for call in api.calls)
    assert provider.synchronize("code-id", [], [], apply=True) == []


def test_offer_code_batch_confirmations_and_expiration():
    api = OfferAPI()
    provider = AppleOfferCodeBatches(api)
    with pytest.raises(UnsafeOperationError, match="custom offer code"):
        provider.synchronize(
            "id", [AppleOfferCodeCustomBatch(custom_code="PROMO", number_of_codes=2)], [], apply=True
        )
    with pytest.raises(UnsafeOperationError, match="one-time offer code"):
        provider.synchronize(
            "id",
            [],
            [AppleOfferCodeOneTimeBatch(number_of_codes=500, expiration_date="2026-12-20")],
            apply=True,
        )
    batch = AppleOfferCodeCustomBatch(
        custom_code="TEST", number_of_codes=5, expiration_date="2026-12-20", confirm_creation=True
    )
    assert len(provider.synchronize("id", [batch], [], apply=True)) == 1
    assert api.calls[-1][2]["data"]["attributes"]["expirationDate"] == "2026-12-20"
    no_env = AppleOfferCodeOneTimeBatch(
        number_of_codes=500, expiration_date="2026-12-20", confirm_creation=True
    )
    assert len(provider.synchronize("id", [], [no_env], apply=True)) == 1
    assert "environment" not in api.calls[-1][2]["data"]["attributes"]
    for value in [
        {"custom_code": "PROMO-WRONG", "number_of_codes": 1},
        {"custom_code": "A", "number_of_codes": 25001},
    ]:
        with pytest.raises(ValidationError):
            AppleOfferCodeCustomBatch(**value)
    with pytest.raises(ValidationError):
        AppleOfferCodeOneTimeBatch(number_of_codes=10, expiration_date="2026-12-20")


def offer(**kwargs):
    return AppleSubscriptionOfferCode(
        name="Holiday",
        duration="ONE_MONTH",
        number_of_periods=1,
        offer_mode="FREE_TRIAL",
        customer_eligibilities=["NEW"],
        offer_eligibility="STACK_WITH_INTRO_OFFERS",
        price_point_ids=["price1"],
        **kwargs,
    )


def test_existing_offer_code_batches_integrate():
    api = OfferAPI()
    api.paginated = Mock(
        side_effect=[
            [
                {
                    "id": "offer-id",
                    "attributes": {
                        "name": "Holiday",
                        "duration": "ONE_MONTH",
                        "numberOfPeriods": 1,
                        "offerMode": "FREE_TRIAL",
                        "customerEligibilities": ["NEW"],
                        "offerEligibility": "STACK_WITH_INTRO_OFFERS",
                    },
                }
            ],
            [],
            [],
        ]
    )
    config = offer(
        custom_code_batches=[
            AppleOfferCodeCustomBatch(custom_code="BONUS", number_of_codes=10, confirm_creation=True)
        ],
        one_time_code_batches=[
            AppleOfferCodeOneTimeBatch(
                number_of_codes=500, expiration_date="2026-12-20", confirm_creation=True
            )
        ],
    )
    assert len(AppleSubscriptionIntroOffers(api).synchronize("subscription", [], [config], apply=True)) == 2
    assert [call[1] for call in api.calls] == [
        "subscriptionOfferCodeCustomCodes",
        "subscriptionOfferCodeOneTimeUseCodes",
    ]


def test_new_offer_code_batches_dry_run_and_apply():
    config = offer(
        custom_code_batches=[
            AppleOfferCodeCustomBatch(custom_code="BONUS", number_of_codes=10, confirm_creation=True)
        ],
        one_time_code_batches=[
            AppleOfferCodeOneTimeBatch(
                number_of_codes=500, expiration_date="2026-12-20", confirm_creation=True
            )
        ],
    )
    api = OfferAPI()
    assert len(AppleSubscriptionIntroOffers(api).synchronize("subscription", [], [config], apply=False)) == 3
    assert api.calls == [("GET", "subscriptions/subscription/offerCodes", {"limit": 200})]
    api.calls.clear()
    assert len(AppleSubscriptionIntroOffers(api).synchronize("subscription", [], [config], apply=True)) == 3
    assert [item[1] for item in api.calls if item[0] == "POST"] == [
        "subscriptionOfferCodes",
        "subscriptionOfferCodeCustomCodes",
        "subscriptionOfferCodeOneTimeUseCodes",
    ]
