from datetime import date
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_beta_group import AppleBetaGroup
from app_publisher.models.apple_beta_tester import AppleBetaTester
from app_publisher.models.apple_registered_device import AppleRegisteredDevice
from app_publisher.models.apple_subscription_promotion import AppleSubscriptionPromotion
from app_publisher.models.apple_subscription_win_back import AppleSubscriptionWinBack
from app_publisher.models.google_one_time_offer import GoogleOneTimeOffer
from app_publisher.providers.apple_beta_groups import AppleBetaGroups
from app_publisher.providers.apple_devices import AppleDevices
from app_publisher.providers.apple_price_audit import ApplePriceAudit
from app_publisher.providers.apple_subscription_promotions import AppleSubscriptionPromotions
from app_publisher.providers.google_one_time_offers import GoogleOneTimeOffers
from app_publisher.providers.store_inspection import StoreInspection


def group(**values):
    return AppleBetaGroup(name="Early Access", **values)


def offer(**values):
    return GoogleOneTimeOffer(
        **(
            {
                "product_id": "coins",
                "purchase_option_id": "buy",
                "offer_id": "sale",
                "regions_version": "2026/10",
                "update_mask": ["offerTags"],
                "data": {"offerTags": [{"tag": "summer"}]},
            }
            | values
        )
    )


def test_apple_beta_group_creates_and_invites():
    api = Mock()
    api.paginated.side_effect = [[], [], []]
    api.request.side_effect = [{"data": {"id": "group-1"}}, {"data": {"id": "tester-1"}}, {}]
    result = AppleBetaGroups(api, "apple-app").synchronize(
        [
            group(
                testers=[
                    AppleBetaTester(
                        email="test@example.com", invite=True, first_name="Test", last_name="Person"
                    )
                ]
            )
        ],
        apply=True,
    )
    assert len(result) == 2
    assert api.request.call_args_list[0].args == ("POST", "betaGroups")
    assert api.request.call_args_list[-1].args == ("POST", "betaTesterInvitations")
    assert (
        api.request.call_args_list[-1].kwargs["payload"]["data"]["relationships"]["app"]["data"]["id"]
        == "apple-app"
    )


def test_apple_beta_group_existing_updates_and_existing_tester():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
        [{"id": "t1", "attributes": {"email": "test@example.com"}}],
    ]
    changes = AppleBetaGroups(api, "app").synchronize(
        [
            group(
                public_link_enabled=True,
                public_link_limit=20,
                testers=[AppleBetaTester(email="test@example.com")],
            )
        ],
        apply=True,
    )
    assert len(changes) == 2
    assert api.request.call_args_list[0].args == ("PATCH", "betaGroups/g1")
    assert api.request.call_args_list[1].args == ("POST", "betaGroups/g1/relationships/betaTesters")


def test_apple_beta_group_dry_run_new_does_not_read_testers():
    api = Mock()
    api.paginated.return_value = []
    changes = AppleBetaGroups(api, "app").synchronize(
        [group(testers=[AppleBetaTester(email="a@example.com")])], apply=False
    )
    assert len(changes) == 2
    api.request.assert_not_called()


def test_apple_beta_group_noop_and_invalid_group():
    api = Mock()
    api.paginated.side_effect = [
        [{"id": "g1", "attributes": {"name": "Early Access", "isInternalGroup": True}}],
        [{"id": "t1", "attributes": {"email": "a@example.com"}}],
    ]
    assert (
        AppleBetaGroups(api, "app").synchronize(
            [group(internal=True, testers=[AppleBetaTester(email="a@example.com")])], apply=True
        )
        == []
    )
    with pytest.raises(ValidationError):
        group(internal=True, public_link_enabled=True)
    with pytest.raises(ValidationError):
        group(testers=[AppleBetaTester(email="X@example.com"), AppleBetaTester(email="x@example.com")])


def test_apple_beta_group_mismatch_and_ambiguity():
    api = Mock()
    api.paginated.return_value = [
        {"id": "g1", "attributes": {"name": "Early Access", "isInternalGroup": True}}
    ]
    with pytest.raises(UnsafeOperationError, match="cannot be changed"):
        AppleBetaGroups(api, "app").synchronize([group()], apply=True)
    api.paginated.return_value = [
        {"id": "g1", "attributes": {"name": "Early Access"}},
        {"id": "g2", "attributes": {"name": "Early Access"}},
    ]
    with pytest.raises(UnsafeOperationError, match="ambiguous"):
        AppleBetaGroups(api, "app").synchronize([group()], apply=False)


def test_apple_beta_group_duplicate_remote_testers():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
        [
            {"id": "a", "attributes": {"email": "a@example.com"}},
            {"id": "b", "attributes": {"email": "a@example.com"}},
        ],
    ]
    with pytest.raises(UnsafeOperationError, match="Multiple"):
        AppleBetaGroups(api, "app").synchronize(
            [group(testers=[AppleBetaTester(email="a@example.com")])], apply=True
        )


def test_apple_devices_register_and_verify():
    api = Mock()
    api.paginated.return_value = [{"attributes": {"udid": "12345", "platform": "IOS", "status": "ENABLED"}}]
    devices = [
        AppleRegisteredDevice(name="Phone", udid="12345", platform="IOS"),
        AppleRegisteredDevice(name="Mac", udid="ABCDE", platform="MAC_OS"),
    ]
    assert len(AppleDevices(api).synchronize(devices, apply=True)) == 1
    assert api.request.call_args.kwargs["payload"]["data"]["attributes"]["udid"] == "ABCDE"


def test_apple_devices_dry_run_and_invalid():
    api = Mock()
    api.paginated.return_value = []
    assert (
        len(
            AppleDevices(api).synchronize(
                [AppleRegisteredDevice(name="Phone", udid="ABCDE", platform="IOS")], apply=False
            )
        )
        == 1
    )
    api.request.assert_not_called()
    api.paginated.return_value = [
        {"attributes": {"udid": "ABCDE", "platform": "MAC_OS", "status": "ENABLED"}}
    ]
    with pytest.raises(UnsafeOperationError, match="mismatch"):
        AppleDevices(api).synchronize(
            [AppleRegisteredDevice(name="Phone", udid="ABCDE", platform="IOS")], apply=True
        )
    api.paginated.return_value = [{"attributes": {"udid": "ABCDE", "platform": "IOS", "status": "DISABLED"}}]
    with pytest.raises(UnsafeOperationError, match="disabled"):
        AppleDevices(api).synchronize(
            [AppleRegisteredDevice(name="Phone", udid="ABCDE", platform="IOS")], apply=True
        )
    assert AppleDevices(api).synchronize([], apply=False) == []


def test_apple_promotions_create_and_verify_existing():
    api = Mock()
    api.paginated.side_effect = [[], []]
    promotion = AppleSubscriptionPromotion(
        name="New Deal",
        duration="ONE_MONTH",
        number_of_periods=2,
        offer_mode="PAY_AS_YOU_GO",
        target_subscription_plan_type="STANDARD",
        price_point_ids=["point-1"],
    )
    winback = AppleSubscriptionWinBack(
        reference_name="Return",
        offer_id="return-1",
        duration="ONE_MONTH",
        offer_mode="PAY_UP_FRONT",
        period_count=1,
        start_date="2026-10-01",
        end_date="2026-11-01",
        priority="HIGH",
        promotion_intent="USE_AUTO_GENERATED_ASSETS",
        price_point_ids=["point-1"],
    )
    result = AppleSubscriptionPromotions(api).synchronize("s1", [promotion], [winback], apply=True)
    assert len(result) == 2
    assert [entry.args[1] for entry in api.request.call_args_list] == [
        "subscriptionPromotionalOffers",
        "winBackOffers",
    ]
    api.paginated.side_effect = [
        [
            {
                "attributes": {
                    "name": "New Deal",
                    "duration": "ONE_MONTH",
                    "numberOfPeriods": 2,
                    "offerMode": "PAY_AS_YOU_GO",
                    "targetSubscriptionPlanType": "STANDARD",
                }
            }
        ]
    ]
    assert AppleSubscriptionPromotions(api).synchronize("s1", [promotion], [], apply=False) == []


def test_apple_promotion_mismatch_and_dry_run():
    api = Mock()
    api.paginated.return_value = [{"attributes": {"name": "New Deal", "duration": "ONE_YEAR"}}]
    promotion = AppleSubscriptionPromotion(
        name="New Deal",
        duration="ONE_MONTH",
        number_of_periods=1,
        offer_mode="FREE_TRIAL",
        price_point_ids=["point-1"],
    )
    with pytest.raises(UnsafeOperationError, match="migration"):
        AppleSubscriptionPromotions(api).synchronize("s1", [promotion], [], apply=False)
    api.paginated.return_value = []
    assert len(AppleSubscriptionPromotions(api).synchronize("s1", [promotion], [], apply=False)) == 1
    api.request.assert_not_called()


def test_google_one_time_offer_creates_and_activates():
    api = Mock()
    api.request.side_effect = [{"oneTimeProductOffers": []}, {}, {}]
    result = GoogleOneTimeOffers(api, "com.example").synchronize([offer(state="ACTIVE")], apply=True)
    assert len(result) == 2
    assert api.request.call_args_list[1].args[1].endswith("offers:batchUpdate")
    assert api.request.call_args_list[-1].args[1].endswith("offers/sale:activate")


def test_google_one_time_offer_noop_and_deactivate():
    api = Mock()
    current = {"offerId": "sale", "offerTags": [{"tag": "summer"}], "state": "ACTIVE"}
    api.request.return_value = {"oneTimeProductOffers": [current]}
    assert GoogleOneTimeOffers(api, "com.example").synchronize([offer(state="ACTIVE")], apply=True) == []
    api.request.side_effect = [{"oneTimeProductOffers": [current]}, {}]
    changes = GoogleOneTimeOffers(api, "com.example").synchronize([offer(state="INACTIVE")], apply=True)
    assert changes == ["Google one-time offer: set sale to INACTIVE"]
    assert api.request.call_args_list[-1].args[1].endswith(":deactivate")


def test_google_one_time_offer_update_and_cancel_dry_run():
    api = Mock()
    api.request.return_value = {
        "oneTimeProductOffers": [{"offerId": "sale", "offerTags": [], "state": "ACTIVE"}]
    }
    changes = GoogleOneTimeOffers(api, "com.example").synchronize([offer(state="CANCELLED")], apply=False)
    assert len(changes) == 2
    assert api.request.call_count == 1


def test_google_one_time_offer_page_cycle_and_invalid_input():
    api = Mock()
    api.request.side_effect = [
        {"oneTimeProductOffers": [], "nextPageToken": "abc"},
        {"oneTimeProductOffers": [], "nextPageToken": "abc"},
    ]
    with pytest.raises(UnsafeOperationError, match="repeats"):
        GoogleOneTimeOffers(api, "com.example").synchronize([offer()], apply=True)
    api = Mock()
    with pytest.raises(UnsafeOperationError, match="identity mismatch"):
        GoogleOneTimeOffers(api, "com.example")._validate_offer(
            offer(data={"offerTags": [], "productId": "wrong"})
        )


def test_google_one_time_offer_invalid_update_mask_and_nested_field():
    api = Mock()
    manager = GoogleOneTimeOffers(api, "com.example")
    assert manager._field({"pricing": {"region": "BR"}}, "pricing.region") == "BR"
    assert manager._field({"pricing": "wrong"}, "pricing.region") is None
    for mask in ["", "offerTags,", "offerTags,,items", ".offerTags", "foo..bar", "offerTags,offerTags"]:
        with pytest.raises((ValidationError, UnsafeOperationError)):
            manager._validate_offer(
                GoogleOneTimeOffer(
                    product_id="coins",
                    purchase_option_id="buy",
                    offer_id="sale",
                    regions_version="2026/10",
                    update_mask=mask.split(","),
                    data={"offerTags": []},
                )
            )


def test_apple_price_audit_paid_and_free():
    api = Mock()
    api.request.side_effect = [
        {"data": {"id": "schedule"}},
        {"data": {"id": "USA"}},
        {"data": {"attributes": {"customerPrice": "2.99"}}},
    ]
    api.paginated.return_value = [
        {
            "attributes": {"startDate": "2026-01-01", "endDate": "2026-12-31"},
            "relationships": {"appPricePoint": {"data": {"id": "point"}}},
        }
    ]
    result = ApplePriceAudit(api, "123").verify(True, today=date(2026, 10, 22))
    assert result["paid"] is True
    assert result["base_territory"] == "USA"
    api.request.side_effect = [
        {"data": {"id": "schedule"}},
        {"data": {"id": "USA"}},
        {"data": {"attributes": {"customerPrice": "0.00"}}},
    ]
    assert ApplePriceAudit(api, "123").verify(False, today=date(2026, 10, 22))["paid"] is False


def test_apple_price_audit_invalid_or_missing():
    api = Mock()
    api.request.side_effect = [{"data": {"id": "schedule"}}, {"data": {"id": "USA"}}]
    api.paginated.return_value = []
    with pytest.raises(UnsafeOperationError, match="exactly one"):
        ApplePriceAudit(api, "123").inspect(today=date(2026, 10, 22))
    api.request.side_effect = [
        {"data": {"id": "schedule"}},
        {"data": {"id": "USA"}},
        {"data": {"attributes": {"customerPrice": "-1"}}},
    ]
    api.paginated.return_value = [
        {"attributes": {}, "relationships": {"appPricePoint": {"data": {"id": "point"}}}}
    ]
    with pytest.raises(UnsafeOperationError, match="nonnegative"):
        ApplePriceAudit(api, "123").inspect(today=date(2026, 10, 22))


def test_apple_price_audit_mismatch_and_inactive_entries():
    api = Mock()
    api.request.side_effect = [
        {"data": {"id": "schedule"}},
        {"data": {"id": "USA"}},
        {"data": {"attributes": {"customerPrice": "10.00"}}},
    ]
    api.paginated.return_value = [
        {
            "attributes": {"startDate": "2026-01-01"},
            "relationships": {
                "territory": {"data": {"id": "GBR"}},
                "appPricePoint": {"data": {"id": "other"}},
            },
        },
        {
            "attributes": {"startDate": "2027-01-01"},
            "relationships": {"appPricePoint": {"data": {"id": "future"}}},
        },
        {
            "attributes": {"startDate": "2025-01-01", "endDate": "2025-12-31"},
            "relationships": {"appPricePoint": {"data": {"id": "expired"}}},
        },
        {"attributes": {}, "relationships": {"appPricePoint": {"data": {"id": "point"}}}},
    ]
    with pytest.raises(UnsafeOperationError, match="differs"):
        ApplePriceAudit(api, "123").verify(False, today=date(2026, 10, 22))
    assert api.request.call_args_list[-1].args[1] == "appPricePoints/point"


def test_apple_price_audit_malformed_price():
    api = Mock()
    api.request.side_effect = [
        {"data": {"id": "schedule"}},
        {"data": {"id": "USA"}},
        {"data": {"attributes": {"customerPrice": "broken"}}},
    ]
    api.paginated.return_value = [
        {"attributes": {}, "relationships": {"appPricePoint": {"data": {"id": "point"}}}}
    ]
    with pytest.raises(UnsafeOperationError, match="valid customer price"):
        ApplePriceAudit(api, "123").inspect()


def test_store_inspection_shapes():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "v1",
                "attributes": {
                    "platform": "IOS",
                    "versionString": "1.0",
                    "appVersionState": "READY_FOR_REVIEW",
                },
            }
        ],
        [{"id": "r1", "attributes": {"state": "IN_REVIEW"}}],
        [{"id": "g1", "attributes": {"name": "Team", "isInternalGroup": True}}],
    ]
    inspector = StoreInspection(api, "app")
    result = inspector.apple()
    assert result["versions"][0]["state"] == "READY_FOR_REVIEW"
    assert result["review_submissions"][0]["state"] == "IN_REVIEW"
    assert result["testflight_groups"][0]["name"] == "Team"
    assert inspector.google([{"track": "production"}])["paid_state"] == "NOT_EXPOSED_BY_PUBLIC_API"


def test_new_configuration_is_strict():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AppleBetaTester(email="a@b.com", arbitrary=True)
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        GoogleOneTimeOffer(
            product_id="A",
            purchase_option_id="buy",
            offer_id="sale",
            regions_version="1",
            update_mask=["offerTags"],
            data={"offerTags": []},
        )


def test_beta_group_feedback_and_dry_run_existing_update():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
    ]
    changes = AppleBetaGroups(api, "app").synchronize(
        [group(feedback_enabled=True, public_link_enabled=True)], apply=False
    )
    assert changes == ["Apple TestFlight: update group Early Access"]
    api.request.assert_not_called()
    assert AppleBetaGroups(api, "app").synchronize([], apply=True) == []


def test_beta_group_existing_dry_run_tester_and_without_names():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
        [],
    ]
    changes = AppleBetaGroups(api, "app").synchronize(
        [group(testers=[AppleBetaTester(email="tester@example.com")])], apply=False
    )
    assert len(changes) == 1
    api.request.assert_not_called()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
        [],
    ]
    api.request.return_value = {"data": {"id": "new-tester"}}
    assert (
        len(
            AppleBetaGroups(api, "app").synchronize(
                [group(testers=[AppleBetaTester(email="tester@example.com", last_name="Smith")])], apply=True
            )
        )
        == 1
    )
    assert api.request.call_args.kwargs["payload"]["data"]["attributes"] == {
        "email": "tester@example.com",
        "lastName": "Smith",
    }


def test_models_duplicate_beta_groups_and_offers(project):
    value = project.apple.model_dump()
    value["beta_groups"] = [{"name": "Alpha"}, {"name": "Alpha"}]
    from app_publisher.models.apple_config import AppleConfig
    from app_publisher.models.google_config import GoogleConfig

    with pytest.raises(ValidationError, match="must be unique"):
        AppleConfig.model_validate(value)
    google = {
        "package_name": "com.example",
        "one_time_offers": [
            {
                "product_id": "coins",
                "purchase_option_id": "buy",
                "offer_id": "test",
                "regions_version": "1",
                "update_mask": ["offerTags"],
                "data": {"offerTags": []},
            }
        ]
        * 2,
    }
    with pytest.raises(ValidationError, match="must be unique"):
        GoogleConfig.model_validate(google)


def test_inspect_engine_routes_both(project, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app_publisher.core.publication_engine import PublicationEngine

    engine = PublicationEngine(project, tmp_path / "app.yaml")
    engine.validate = Mock()
    fake_apple = SimpleNamespace(api=Mock(), config=SimpleNamespace(app_id="1"), identify=Mock())
    fake_google = SimpleNamespace(
        api=Mock(),
        config=SimpleNamespace(package_name="com.example"),
        start_edit=Mock(return_value="e1"),
        edit_path=Mock(return_value="applications/com.example/edits/e1"),
    )
    fake_google.api.request.return_value = {"tracks": [{"track": "production"}]}
    engine.apple = Mock(return_value=fake_apple)
    engine.google = Mock(return_value=fake_google)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.StoreInspection",
        lambda api, app_id: SimpleNamespace(
            apple=lambda: {"versions": []}, google=lambda tracks: {"tracks": tracks}
        ),
    )
    project.apple.verify_paid = True
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.ApplePriceAudit",
        lambda api, app_id: SimpleNamespace(verify=lambda paid: {"paid": paid}),
    )
    result = engine.inspect()
    assert result["apple"]["pricing"] == {"paid": True}
    assert result["google"]["tracks"][0]["track"] == "production"
    assert fake_google.api.request.call_args_list[-1].args[0] == "DELETE"
    assert fake_apple.api.close.called
    assert fake_google.api.close.called
    project.apple.verify_paid = None
    assert engine.inspect("apple")["apple"] == {"versions": []}
    assert engine.inspect("none") == {}


def test_inspect_cli_invokes_engine(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from app_publisher.cli import app

    fake = Mock()
    fake.inspect.return_value = {"apple": {"versions": []}}
    monkeypatch.setattr("app_publisher.cli.open_engine", lambda path: fake)
    response = CliRunner().invoke(app, ["inspect", str(tmp_path / "app.yaml")])
    assert response.exit_code == 0
    assert '"apple"' in response.stdout
    fake.inspect.assert_called_once_with("all")


def test_engine_google_one_time_offers_route(project, tmp_path, monkeypatch):
    from app_publisher.core.publication_engine import PublicationEngine
    from app_publisher.models.google_config import GoogleConfig

    project.apple = None
    project.firebase = None
    project.google = GoogleConfig(package_name="com.example", one_time_offers=[offer()])
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    engine.validate = Mock()
    fake = Mock()
    fake.config = project.google
    fake.synchronize.return_value = []
    engine.google = Mock(return_value=fake)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.GoogleOneTimeOffers", lambda api, name: SimpleFakeOffer()
    )
    changes = engine.synchronize(apply=False, provider="google")
    assert changes == ["offer-synced"]
    fake.api.close.assert_called_once()


class SimpleFakeOffer:
    def synchronize(self, offers, *, apply):
        return ["offer-synced"]


def test_beta_group_first_name_without_last_name():
    api = Mock()
    api.paginated.side_effect = [
        [
            {
                "id": "g1",
                "attributes": {"name": "Early Access", "isInternalGroup": False, "publicLinkEnabled": False},
            }
        ],
        [],
        [],
    ]
    api.request.return_value = {"data": {"id": "tester"}}
    assert (
        len(
            AppleBetaGroups(api, "app").synchronize(
                [group(testers=[AppleBetaTester(email="alpha@example.com", first_name="Alpha")])], apply=True
            )
        )
        == 1
    )
    assert api.request.call_args.kwargs["payload"]["data"]["attributes"] == {
        "email": "alpha@example.com",
        "firstName": "Alpha",
    }


def test_apple_promotional_offer_requires_distinct_price_points():
    api = Mock()
    api.paginated.return_value = []
    duplicate = AppleSubscriptionPromotion(
        name="Deal",
        duration="ONE_MONTH",
        number_of_periods=1,
        offer_mode="FREE_TRIAL",
        price_point_ids=["tier1", "tier1"],
    )
    with pytest.raises(UnsafeOperationError, match="repeats"):
        AppleSubscriptionPromotions(api).synchronize("subscription-1", [duplicate], [], apply=True)
    api.request.assert_not_called()
