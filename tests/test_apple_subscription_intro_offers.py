from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription_introductory_offer import AppleSubscriptionIntroductoryOffer
from app_publisher.models.apple_subscription_offer_code import AppleSubscriptionOfferCode
from app_publisher.providers.apple_subscription_intro_offers import AppleSubscriptionIntroOffers


def intro(**values):
    return AppleSubscriptionIntroductoryOffer(
        **(
            {
                "territory": "USA",
                "start_date": "2026-11-01",
                "end_date": "2027-01-01",
                "duration": "ONE_MONTH",
                "number_of_periods": 1,
                "offer_mode": "FREE_TRIAL",
                "price_point_id": "price-1",
            }
            | values
        )
    )


def code(**values):
    return AppleSubscriptionOfferCode(
        **(
            {
                "name": "Holiday",
                "duration": "ONE_MONTH",
                "number_of_periods": 1,
                "offer_mode": "PAY_UP_FRONT",
                "customer_eligibilities": ["NEW"],
                "offer_eligibility": "STACK_WITH_INTRO_OFFERS",
                "price_point_ids": ["price-1"],
            }
            | values
        )
    )


def test_intro_and_offer_code_create():
    api = Mock()
    api.paginated.side_effect = [[], []]
    result = AppleSubscriptionIntroOffers(api).synchronize(
        "subscription-1",
        [intro(target_subscription_plan_type="STANDARD")],
        [code(target_subscription_plan_type="STANDARD")],
        apply=True,
    )
    assert len(result) == 2
    intro_call = api.request.call_args_list[0]
    assert intro_call.args == ("POST", "subscriptionIntroductoryOffers")
    assert intro_call.kwargs["payload"]["data"]["relationships"]["territory"]["data"]["id"] == "USA"
    assert intro_call.kwargs["payload"]["data"]["attributes"]["targetSubscriptionPlanType"] == "STANDARD"
    code_call = api.request.call_args_list[1]
    assert code_call.args == ("POST", "subscriptionOfferCodes")
    assert (
        code_call.kwargs["payload"]["included"][0]["relationships"]["subscriptionPricePoint"]["data"]["id"]
        == "price-1"
    )


def test_intro_offer_code_dry_run():
    api = Mock()
    api.paginated.side_effect = [[], []]
    result = AppleSubscriptionIntroOffers(api).synchronize("subscription-1", [intro()], [code()], apply=False)
    assert len(result) == 2
    api.request.assert_not_called()


def test_intro_matches_existing_territory_start_date():
    api = Mock()
    api.paginated.return_value = [
        {
            "attributes": {
                "startDate": "2026-11-01",
                "endDate": "2027-01-01",
                "duration": "ONE_MONTH",
                "numberOfPeriods": 1,
                "offerMode": "FREE_TRIAL",
            },
            "relationships": {"territory": {"data": {"id": "USA"}}},
        }
    ]
    assert AppleSubscriptionIntroOffers(api).synchronize("subscription-1", [intro()], [], apply=True) == []
    api.request.assert_not_called()


def test_intro_only_creates_when_unmatched_and_rejects_dates():
    api = Mock()
    api.paginated.return_value = [
        {"attributes": {"startDate": "2026-10-01"}, "relationships": {"territory": {"data": {"id": "USA"}}}}
    ]
    assert (
        len(AppleSubscriptionIntroOffers(api).synchronize("subscription-1", [intro()], [], apply=True)) == 1
    )
    api.paginated.return_value = []
    with pytest.raises(UnsafeOperationError, match="dates"):
        AppleSubscriptionIntroOffers(api).synchronize(
            "subscription-1", [intro(start_date="2027-12-01")], [], apply=True
        )


def test_offer_code_existing_noop_and_immutable_field_conflict():
    api = Mock()
    api.paginated.return_value = [
        {
            "attributes": {
                "name": "Holiday",
                "duration": "ONE_MONTH",
                "numberOfPeriods": 1,
                "offerMode": "PAY_UP_FRONT",
                "customerEligibilities": ["NEW"],
                "offerEligibility": "STACK_WITH_INTRO_OFFERS",
            }
        }
    ]
    assert AppleSubscriptionIntroOffers(api).synchronize("subscription-1", [], [code()], apply=True) == []
    api.request.assert_not_called()
    with pytest.raises(UnsafeOperationError, match="immutable"):
        AppleSubscriptionIntroOffers(api).synchronize(
            "subscription-1", [], [code(number_of_periods=2)], apply=False
        )


def test_offer_code_rejects_duplicate_remote_names():
    api = Mock()
    api.paginated.return_value = [{"attributes": {"name": "Holiday"}}, {"attributes": {"name": "Holiday"}}]
    with pytest.raises(UnsafeOperationError, match="ambiguous"):
        AppleSubscriptionIntroOffers(api).synchronize("subscription-1", [], [code()], apply=False)


def test_offer_code_rejects_duplicate_price_points():
    api = Mock()
    api.paginated.return_value = []
    with pytest.raises(UnsafeOperationError, match="repeats"):
        AppleSubscriptionIntroOffers(api).synchronize(
            "subscription-1", [], [code(price_point_ids=["price-1", "price-1"])], apply=True
        )
    api.request.assert_not_called()


def test_no_offers_short_circuits_and_optional_relationship():
    api = Mock()
    manager = AppleSubscriptionIntroOffers(api)
    assert manager.synchronize("subscription-1", [], [], apply=True) == []
    assert manager._territory({}) is None
    api.paginated.assert_not_called()
    with pytest.raises(ValidationError):
        intro(territory="us")


def test_intro_existing_difference_and_duplicate_remote_records():
    api = Mock()
    entry = {
        "attributes": {
            "startDate": "2026-11-01",
            "endDate": "2026-12-01",
            "duration": "ONE_MONTH",
            "numberOfPeriods": 1,
            "offerMode": "FREE_TRIAL",
        },
        "relationships": {
            "territory": {"data": {"id": "USA"}},
            "subscriptionPricePoint": {"data": {"id": "price-2"}},
        },
    }
    api.paginated.return_value = [entry]
    with pytest.raises(UnsafeOperationError, match="immutable"):
        AppleSubscriptionIntroOffers(api).synchronize("s1", [intro()], [], apply=True)
    api.paginated.return_value = [entry, entry]
    with pytest.raises(UnsafeOperationError, match="ambiguous"):
        AppleSubscriptionIntroOffers(api).synchronize("s1", [intro()], [], apply=True)


def test_intro_existing_price_point_conflict():
    api = Mock()
    api.paginated.return_value = [
        {
            "attributes": {
                "startDate": "2026-11-01",
                "endDate": "2027-01-01",
                "duration": "ONE_MONTH",
                "numberOfPeriods": 1,
                "offerMode": "FREE_TRIAL",
            },
            "relationships": {
                "territory": {"data": {"id": "USA"}},
                "subscriptionPricePoint": {"data": {"id": "price-2"}},
            },
        }
    ]
    with pytest.raises(UnsafeOperationError, match="subscriptionPricePoint"):
        AppleSubscriptionIntroOffers(api).synchronize("s1", [intro()], [], apply=True)


def test_intro_existing_target_plan_type_comparison():
    api = Mock()
    api.paginated.return_value = [
        {
            "attributes": {
                "startDate": "2026-11-01",
                "endDate": "2027-01-01",
                "duration": "ONE_MONTH",
                "numberOfPeriods": 1,
                "offerMode": "FREE_TRIAL",
                "targetSubscriptionPlanType": "STANDARD",
            },
            "relationships": {"territory": {"data": {"id": "USA"}}},
        }
    ]
    assert (
        AppleSubscriptionIntroOffers(api).synchronize(
            "s1", [intro(target_subscription_plan_type="STANDARD")], [], apply=True
        )
        == []
    )
