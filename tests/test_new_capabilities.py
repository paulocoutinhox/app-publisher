import pytest
from pydantic import ValidationError

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_app_price import AppleAppPrice
from app_publisher.models.apple_pricing import ApplePricing
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.models.apple_subscription_price import AppleSubscriptionPrice
from app_publisher.models.google_base_plan_state import GoogleBasePlanState
from app_publisher.models.google_subscription_offer import GoogleSubscriptionOffer
from app_publisher.models.product_localization import ProductLocalization
from app_publisher.providers.apple_commercial import AppleCommercial
from app_publisher.providers.apple_product_localizations import AppleProductLocalizations
from app_publisher.providers.apple_subscriptions import AppleSubscriptions
from app_publisher.providers.google_subscription_offers import GoogleSubscriptionOffers


class MemoryAPI:
    def __init__(self, responses=None, lists=None):
        self.responses = responses or {}
        self.lists = lists or {}
        self.calls = []
        self.failures = {}

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if (method, path) in self.failures:
            raise self.failures[(method, path)]
        if (method, path) in self.responses:
            return self.responses[(method, path)]
        if method == "POST":
            return {"data": {"id": "created", "attributes": {"state": "DRAFT"}}, "state": "DRAFT"}
        if method == "PATCH":
            return {"data": {"id": "updated"}, "state": "DRAFT"}
        raise AssertionError(f"Unexpected API call: {method} {path}")

    def paginated(self, path, **kwargs):
        self.calls.append(("LIST", path, kwargs))
        if path not in self.lists:
            raise AssertionError(f"Unexpected pagination: {path}")
        return self.lists[path]


def subscription(product_id="premium", **kwargs):
    return AppleSubscription(product_id=product_id, name="Premium", period="ONE_MONTH", **kwargs)


def offer(state="DRAFT", **kwargs):
    return GoogleSubscriptionOffer(
        product_id="premium",
        base_plan_id="monthly",
        offer_id="trial",
        regions_version="2026/10",
        update_mask=["phases"],
        state=state,
        **({"data": {"phases": [1]}} | kwargs),
    )


def test_apple_pricing_unchanged_and_dry_run():
    api = MemoryAPI(
        {
            ("GET", "apps/123/appPriceSchedule"): {"data": {"id": "sched"}},
            ("GET", "appPriceSchedules/sched/relationships/baseTerritory"): {"data": {"id": "BRA"}},
        },
        {
            "appPriceSchedules/sched/manualPrices": [
                {
                    "attributes": {"startDate": None, "endDate": None},
                    "relationships": {"appPricePoint": {"data": {"id": "price-a"}}},
                }
            ]
        },
    )
    subject = AppleCommercial(api, "123")
    pricing = ApplePricing(base_territory="BRA", prices=[AppleAppPrice(price_point_id="price-a")])
    assert subject.synchronize_pricing(pricing, apply=True) == []
    assert subject.synchronize_pricing(
        pricing.model_copy(update={"prices": [AppleAppPrice(price_point_id="price-b")]}), apply=False
    )
    assert not any(call[0] == "POST" for call in api.calls)


def test_apple_pricing_changes_require_confirmation_and_full_schedule():
    api = MemoryAPI(
        {
            ("GET", "apps/123/appPriceSchedule"): {"data": {"id": "sched"}},
            ("GET", "appPriceSchedules/sched/relationships/baseTerritory"): {"data": {"id": "BRA"}},
        },
        {"appPriceSchedules/sched/manualPrices": []},
    )
    subject = AppleCommercial(api, "123")
    original = ApplePricing(base_territory="BRA", prices=[AppleAppPrice(price_point_id="point-1")])
    with pytest.raises(UnsafeOperationError, match="confirm_price_changes"):
        subject.synchronize_pricing(original, apply=True)
    assert subject.synchronize_pricing(
        original.model_copy(update={"confirm_price_changes": True}), apply=True
    )
    assert api.calls[-1][0:2] == ("POST", "appPriceSchedules")
    payload = api.calls[-1][2]["payload"]
    assert payload["data"]["relationships"]["baseTerritory"]["data"]["id"] == "BRA"
    assert payload["included"][0]["relationships"]["appPricePoint"]["data"]["id"] == "point-1"
    with pytest.raises(UnsafeOperationError, match="Duplicate"):
        subject.synchronize_pricing(
            original.model_copy(update={"prices": [original.prices[0], original.prices[0]]}), apply=False
        )
    with pytest.raises(UnsafeOperationError, match="base territory"):
        subject.synchronize_pricing(original.model_copy(update={"base_territory": "USA"}), apply=False)


def test_apple_preorder_territories_safety_and_updates():
    api = MemoryAPI(
        {("GET", "apps/123/appAvailabilityV2"): {"data": {"id": "availability"}}},
        {
            "appAvailabilities/availability/territoryAvailabilities": [
                {
                    "id": "r1",
                    "attributes": {"preOrderEnabled": True, "available": False},
                    "relationships": {"territory": {"data": {"id": "BRA"}}},
                },
                {
                    "id": "r2",
                    "attributes": {"preOrderEnabled": True, "available": True},
                    "relationships": {"territory": {"data": {"id": "USA"}}},
                },
            ]
        },
    )
    publisher = AppleCommercial(api, "123")
    assert publisher.synchronize_territories({}, apply=True) == []
    assert publisher.synchronize_territories({"BRA": True, "USA": True}, apply=True) == [
        "Apple availability: set BRA to True"
    ]
    assert api.calls[-1][0:2] == ("PATCH", "territoryAvailabilities/r1")
    with pytest.raises(UnsafeOperationError, match="Unrecognized"):
        publisher.synchronize_territories({"ZZZ": True}, apply=False)
    api.lists["appAvailabilities/availability/territoryAvailabilities"][0]["attributes"][
        "preOrderEnabled"
    ] = False
    with pytest.raises(UnsafeOperationError, match="pre-orders"):
        publisher.synchronize_territories({"BRA": True}, apply=True)


def test_apple_localization_new_draft_create_and_reuse():
    api = MemoryAPI(
        lists={
            "inAppPurchases/p1/versions": [],
            "inAppPurchaseVersions/old/localizations": [],
            "inAppPurchaseVersions/draft/localizations": [
                {"id": "loc", "attributes": {"locale": "en-US", "name": "Old", "description": "Old text"}}
            ],
        }
    )
    localizer = AppleProductLocalizations(api)
    desired = {"en-US": ProductLocalization(name="New", description="New description")}
    assert localizer.synchronize("iap", "p1", {}, apply=True) == []
    assert localizer.synchronize("iap", "p1", desired, apply=False)
    assert localizer.synchronize("iap", "p1", desired, apply=True)
    assert any(method == "POST" and endpoint == "inAppPurchaseVersions" for method, endpoint, _ in api.calls)
    assert any(
        method == "POST" and endpoint == "inAppPurchaseLocalizations" and args["version"] == "v2"
        for method, endpoint, args in api.calls
    )
    api.lists["inAppPurchases/p1/versions"] = [
        {"id": "draft", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}}
    ]
    assert localizer.synchronize("iap", "p1", desired, apply=True)
    assert api.calls[-1][0:2] == ("PATCH", "inAppPurchaseLocalizations/loc")
    api.lists["inAppPurchaseVersions/draft/localizations"] = [
        {"id": "loc", "attributes": {"locale": "en-US", "name": "New", "description": "New description"}}
    ]
    assert localizer.synchronize("iap", "p1", desired, apply=True) == []


def test_apple_localization_version_conflicts_and_group_constraints():
    api = MemoryAPI(
        lists={
            "subscriptionGroups/g/versions": [
                {"id": "a", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}},
                {"id": "b", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}},
            ]
        }
    )
    localizer = AppleProductLocalizations(api)
    with pytest.raises(UnsafeOperationError, match="multiple editable"):
        localizer.synchronize("group", "g", {"en-US": "Premium"}, apply=False)
    api.lists["subscriptionGroups/g/versions"] = [
        {"id": "approved", "attributes": {"state": "APPROVED", "version": 1}}
    ]
    api.lists["subscriptionGroupVersions/approved/localizations"] = [
        {"id": "a", "attributes": {"locale": "en-US", "name": "Old"}}
    ]
    assert localizer.synchronize("group", "g", {"en-US": "New"}, apply=True)
    assert any(method == "POST" and path == "subscriptionGroupVersions" for method, path, _ in api.calls)
    with pytest.raises(UnsafeOperationError, match="display name"):
        localizer.synchronize(
            "group", "g", {"en-US": ProductLocalization(name="Name", description="Text")}, apply=False
        )
    api.lists["subscriptions/s/versions"] = []
    with pytest.raises(UnsafeOperationError, match="name and description"):
        localizer.synchronize("subscription", "s", {"en-US": "Text"}, apply=False)


def test_apple_subscription_group_creation_and_dry_run():
    api = MemoryAPI(
        lists={
            "apps/123/subscriptionGroups": [],
            "subscriptionGroups/created/versions": [],
            "subscriptionGroups/created/subscriptions": [],
        }
    )
    subject = AppleSubscriptions(api, "123")
    group = AppleSubscriptionGroup(
        reference_name="Pro", subscriptions=[subscription()], localizations={"en-US": "Pro"}
    )
    assert subject.synchronize([group], apply=False) == [
        "Apple subscription group: create Pro",
        "Apple subscription: create premium",
    ]
    assert subject.synchronize([group], apply=True)
    assert any(method == "POST" and path == "subscriptionGroups" for method, path, _ in api.calls)
    assert any(method == "POST" and path == "subscriptions" for method, path, _ in api.calls)


def test_apple_subscription_updates_prices_and_immutable_fields():
    current = {
        "id": "s1",
        "attributes": {
            "productId": "premium",
            "subscriptionPeriod": "ONE_MONTH",
            "name": "Basic",
            "familySharable": False,
            "reviewNote": "",
            "groupLevel": 1,
        },
    }
    api = MemoryAPI(
        lists={
            "apps/123/subscriptionGroups": [{"id": "group", "attributes": {"referenceName": "Pro"}}],
            "subscriptionGroups/group/subscriptions": [current],
            "subscriptions/s1/versions": [],
            "subscriptions/s1/prices": [],
        }
    )
    manager = AppleSubscriptions(api, "123")
    assert manager.synchronize(
        [
            AppleSubscriptionGroup(
                reference_name="Pro",
                subscriptions=[subscription(prices=[AppleSubscriptionPrice(price_point_id="point")])],
            )
        ],
        apply=False,
    )
    with pytest.raises(UnsafeOperationError, match="require confirm_subscription_price_changes"):
        manager.synchronize(
            [
                AppleSubscriptionGroup(
                    reference_name="Pro",
                    subscriptions=[subscription(prices=[AppleSubscriptionPrice(price_point_id="point")])],
                )
            ],
            apply=True,
        )
    assert manager.synchronize(
        [
            AppleSubscriptionGroup(
                reference_name="Pro",
                subscriptions=[subscription(prices=[AppleSubscriptionPrice(price_point_id="point")])],
            )
        ],
        apply=True,
        allow_price_changes=True,
    )
    assert any(method == "POST" and path == "subscriptionPrices" for method, path, _ in api.calls)
    bad = subscription()
    bad.period = "ONE_YEAR"
    with pytest.raises(UnsafeOperationError, match="immutable period"):
        manager.synchronize([AppleSubscriptionGroup(reference_name="Pro", subscriptions=[bad])], apply=False)


def test_google_offers_create_update_immutable_and_activation():
    api = MemoryAPI(
        {
            ("GET", "applications/com.app/subscriptions/premium/basePlans/monthly/offers/trial"): {
                "phases": [0],
                "state": "INACTIVE",
            }
        }
    )
    manager = GoogleSubscriptionOffers(api, "com.app")
    assert manager.synchronize([offer(state="ACTIVE")], [], apply=False) == [
        "Google offer: update trial",
        "Google offer: active trial",
    ]
    assert manager.synchronize([offer(state="ACTIVE")], [], apply=True)
    assert any(method == "POST" and path.endswith(":activate") for method, path, _ in api.calls)
    api.failures[("GET", "applications/com.app/subscriptions/premium/basePlans/monthly/offers/trial")] = (
        RemoteAPIError("GET returned HTTP 404: missing")
    )
    assert manager.synchronize([offer()], [], apply=True) == ["Google offer: create trial"]
    assert any(method == "POST" and path.endswith("/offers") for method, path, _ in api.calls)
    api.failures[("GET", "applications/com.app/subscriptions/premium/basePlans/monthly/offers/trial")] = (
        RemoteAPIError("GET returned HTTP 403")
    )
    with pytest.raises(RemoteAPIError, match="403"):
        manager.synchronize([offer()], [], apply=False)
    with pytest.raises(UnsafeOperationError, match="identity mismatch"):
        manager.synchronize([offer(data={"packageName": "another", "phases": [1]})], [], apply=False)


def test_google_base_plan_states_and_validation():
    subscription_doc = {"basePlans": [{"basePlanId": "monthly", "state": "INACTIVE"}]}
    api = MemoryAPI({("GET", "applications/com.app/subscriptions/premium"): subscription_doc})
    manager = GoogleSubscriptionOffers(api, "com.app")
    state = GoogleBasePlanState(product_id="premium", base_plan_id="monthly", state="ACTIVE")
    assert manager.synchronize([], [state], apply=False) == ["Google base plan: active monthly"]
    assert manager.synchronize([], [state], apply=True)
    assert api.calls[-1][1].endswith(":activate")
    state.state = "INACTIVE"
    assert manager.synchronize([], [state], apply=False) == []
    state.base_plan_id = "yearly"
    with pytest.raises(UnsafeOperationError, match="Unknown"):
        manager.synchronize([], [state], apply=False)
    subscription_doc["basePlans"] = None
    with pytest.raises(UnsafeOperationError, match="did not return"):
        manager.synchronize([], [state], apply=False)


def test_added_models_reject_invalid_duplicate_ids(project, tmp_path):
    with pytest.raises(ValidationError, match="unique"):
        project.apple.subscription_groups = [
            AppleSubscriptionGroup(reference_name="Pro", subscriptions=[subscription()]),
            AppleSubscriptionGroup(reference_name="Pro"),
        ]
    with pytest.raises(ValidationError):
        ApplePricing(base_territory="BR", prices=[AppleAppPrice(price_point_id="price")])


def test_engine_price_preflight_before_writes(project, tmp_path):
    project.apple.pricing = ApplePricing(base_territory="BRA", prices=[AppleAppPrice(price_point_id="point")])
    engine = PublicationEngine(project, tmp_path / "example.yaml")
    with pytest.raises(UnsafeOperationError, match="confirm_price_changes"):
        engine.synchronize(apply=True, provider="apple")
    project.apple.pricing = None
    project.apple.subscription_groups = [
        AppleSubscriptionGroup(
            reference_name="Pro",
            subscriptions=[subscription(prices=[AppleSubscriptionPrice(price_point_id="point")])],
        )
    ]
    with pytest.raises(UnsafeOperationError, match="confirm_subscription_price_changes"):
        engine.synchronize(apply=True, provider="apple")


def test_engine_synchronizes_new_apple_and_google_resources(monkeypatch, project, tmp_path):
    from types import SimpleNamespace

    recorded = []
    handler = SimpleNamespace(api=SimpleNamespace(close=lambda: None), synchronize=lambda *a, **k: ["base"])
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: handler)
    monkeypatch.setattr(PublicationEngine, "google", lambda self: handler)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleSubscriptions",
        lambda *a: SimpleNamespace(
            synchronize=lambda *args, **kwargs: recorded.append("subscription") or ["group"]
        ),
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleCommercial",
        lambda *a: SimpleNamespace(
            verify_base_territory=lambda *a: ["verified"],
            synchronize_pricing=lambda *args, **kwargs: ["price"],
            synchronize_territories=lambda *args, **kwargs: ["country"],
        ),
    )
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.GoogleSubscriptionOffers",
        lambda *a: SimpleNamespace(synchronize=lambda *args, **kwargs: ["offers"]),
    )
    project.apple.subscription_groups = [AppleSubscriptionGroup(reference_name="Pro")]
    project.apple.pricing = ApplePricing(base_territory="BRA", prices=[AppleAppPrice(price_point_id="p")])
    project.apple.verify_base_territory = "BRA"
    project.apple.preorder_territory_availability = {"BRA": True}
    project.google.subscription_offers = [offer()]
    result = PublicationEngine(project, tmp_path / "app.yaml").synchronize(apply=False, provider="all")
    assert (
        "group" in result
        and "price" in result
        and "country" in result
        and "offers" in result
        and "verified" in result
    )
    assert recorded == ["subscription"]


def test_google_monetization_models_reject_duplicates(project):
    from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
    from app_publisher.models.google_config import GoogleConfig

    item = offer()
    with pytest.raises(ValidationError, match="must be unique"):
        GoogleConfig(package_name="com.demo", subscription_offers=[item, item])
    with pytest.raises(ValidationError, match="must be unique"):
        GoogleConfig(
            package_name="com.demo",
            base_plan_states=[
                GoogleBasePlanState(product_id="pro", base_plan_id="m", state="ACTIVE"),
                GoogleBasePlanState(product_id="pro", base_plan_id="m", state="INACTIVE"),
            ],
        )
    with pytest.raises(ValidationError, match="must be unique"):
        project.apple.in_app_purchases = [
            AppleInAppPurchase(product_id="premium", name="Pro", purchase_type="CONSUMABLE"),
            AppleInAppPurchase(product_id="premium", name="Pro", purchase_type="CONSUMABLE"),
        ]


def test_new_validation_effective_common_fields(tmp_path, project):
    from app_publisher.core.validation import validate_project

    project.locales["en-US"].apple.name = None
    project.locales["en-US"].apple.description = None
    project.locales["en-US"].apple.whats_new = None
    project.locales["en-US"].google.title = None
    project.locales["en-US"].google.full_description = None
    project.locales["en-US"].common.name = "X" * 90
    project.locales["en-US"].common.description = "X" * 4100
    project.locales["en-US"].common.release_notes = "X" * 4100
    project.locales["en-US"].google.images = {
        "icon": ["one.png", "two.png"],
        "phoneScreenshots": ["a.png"] * 9,
    }
    project.locales["bad!locale"] = project.locales.pop("en-US")
    project.app.default_locale = "bad!locale"
    issues = validate_project(project, tmp_path / "app.yaml")
    assert any("Invalid locale identifier" in issue for issue in issues)
    assert any("apple.bad!locale.name" in issue for issue in issues)
    assert any("apple.bad!locale.description" in issue for issue in issues)
    assert any("apple.bad!locale.whats_new" in issue for issue in issues)
    assert any("google.bad!locale.title" in issue for issue in issues)
    assert any("google.bad!locale.full_description" in issue for issue in issues)
    assert any("requires exactly one" in issue for issue in issues)
    assert any("more than eight" in issue for issue in issues)


def test_new_apple_subscription_existing_creation_paths():
    from app_publisher.models.product_localization import ProductLocalization

    existing = {
        "id": "existing",
        "attributes": {
            "productId": "premium",
            "subscriptionPeriod": "ONE_MONTH",
            "name": "Premium",
            "familySharable": False,
            "reviewNote": "",
            "groupLevel": 1,
        },
    }
    api = MemoryAPI(
        lists={
            "apps/123/subscriptionGroups": [{"id": "g", "attributes": {"referenceName": "Pro"}}],
            "subscriptionGroups/g/subscriptions": [existing],
            "subscriptions/existing/versions": [],
            "subscriptions/existing/prices": [
                {
                    "attributes": {"startDate": "2026-12-01", "planType": "UPFRONT"},
                    "relationships": {"subscriptionPricePoint": {"data": {"id": "point"}}},
                }
            ],
        }
    )
    subject = AppleSubscriptions(api, "123")
    item = AppleSubscriptionGroup(
        reference_name="Pro",
        subscriptions=[
            subscription(prices=[AppleSubscriptionPrice(price_point_id="point", start_date="2026-12-01")])
        ],
    )
    assert subject.synchronize([item], apply=True) == []
    item.subscriptions[0].name = "Plus"
    assert subject.synchronize([item], apply=False) == ["Apple subscription: update premium"]
    assert subject.synchronize([item], apply=True) == ["Apple subscription: update premium"]
    assert any(method == "PATCH" and path == "subscriptions/existing" for method, path, _ in api.calls)
    item.subscriptions[0].prices = [AppleSubscriptionPrice(price_point_id="later", start_date="2026-12-25")]
    assert subject.synchronize([item], apply=True, allow_price_changes=True)
    assert any(
        method == "POST"
        and path == "subscriptionPrices"
        and args["payload"]["data"]["attributes"]["startDate"] == "2026-12-25"
        for method, path, args in api.calls
    )
    api.lists["subscriptionGroups/g/subscriptions"] = []
    assert subject.synchronize([item], apply=False) == [
        "Apple subscription: create premium",
        "Apple subscription premium: schedule price later",
    ]
    item.subscriptions[0].localizations = {
        "en-US": ProductLocalization(name="Pro", description="Description")
    }
    assert "Apple subscription premium: synchronize en-US" in subject.synchronize([item], apply=False)


def test_google_offer_nested_mask_and_dry_run_branches():
    manager = GoogleSubscriptionOffers(
        MemoryAPI(
            {
                ("GET", "applications/com.app/subscriptions/premium/basePlans/monthly/offers/trial"): {
                    "state": "DRAFT",
                    "phases": {"intro": None},
                }
            }
        ),
        "com.app",
    )
    bad = offer().model_copy(update={"update_mask": ["phases."]})
    with pytest.raises(UnsafeOperationError, match="invalid"):
        manager.synchronize([bad], [], apply=False)
    item = offer(data={"phases": {"intro": {"price": "low"}}}, state="DRAFT").model_copy(
        update={"update_mask": ["phases.intro"]}
    )
    assert manager.synchronize([item], [], apply=False) == ["Google offer: update trial"]
    assert manager.synchronize([item], [], apply=True) == ["Google offer: update trial"]
    item.data = {"phases": {"intro": None}}
    assert manager.synchronize([item], [], apply=False) == []
    api = MemoryAPI(lists={})
    api.failures[("GET", "applications/com.app/subscriptions/premium/basePlans/monthly/offers/trial")] = (
        RemoteAPIError("HTTP 404")
    )
    second = GoogleSubscriptionOffers(api, "com.app")
    assert second.synchronize([offer(state="ACTIVE")], [], apply=False) == ["Google offer: create trial"]
    assert second.synchronize([offer(state="ACTIVE")], [], apply=True) == [
        "Google offer: create trial",
        "Google offer: active trial",
    ]


def test_new_last_branches_pricing_localizations_and_nested_masks():
    from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
    from app_publisher.providers.apple_in_app_purchase_manager import AppleInAppPurchaseManager

    api = MemoryAPI(lists={"apps/123/inAppPurchasesV2": []})
    purchases = [
        AppleInAppPurchase(
            product_id="lifetime",
            name="Lifetime",
            purchase_type="NON_CONSUMABLE",
            localizations={"en-US": ProductLocalization(name="Lifetime", description="Full access")},
        )
    ]
    assert AppleInAppPurchaseManager(api, "123").synchronize(purchases, apply=False) == [
        "Apple in-app purchase: create lifetime",
        "Apple iap lifetime: create localization en-US",
    ]
    territory = MemoryAPI(
        responses={("GET", "apps/123/appAvailabilityV2"): {"data": {"id": "avail"}}},
        lists={
            "appAvailabilities/avail/territoryAvailabilities": [
                {
                    "id": "r1",
                    "attributes": {"available": False, "preOrderEnabled": True},
                    "relationships": {"territory": {"data": {"id": "BRA"}}},
                }
            ]
        },
    )
    assert AppleCommercial(territory, "123").synchronize_territories({"BRA": True}, apply=False) == [
        "Apple availability: set BRA to True"
    ]
    assert all(call[0] != "PATCH" for call in territory.calls)
    assert GoogleSubscriptionOffers._get({"phases": [1, 2]}, "phases.value") is None
