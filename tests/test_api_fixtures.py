import httpx
import pytest

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.models.apple_config import AppleConfig
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_availability import AppleSubscriptionAvailability
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.models.apple_subscription_price import AppleSubscriptionPrice
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.firebase_config import FirebaseConfig
from app_publisher.models.google_monetization_product import GoogleMonetizationProduct
from app_publisher.providers.apple_build_manager import AppleBuildManager
from app_publisher.providers.apple_publisher import ApplePublisher
from app_publisher.providers.apple_subscription_availability_publisher import (
    AppleSubscriptionAvailabilityPublisher,
)
from app_publisher.providers.apple_subscriptions import AppleSubscriptions
from app_publisher.providers.firebase_publisher import FirebasePublisher
from app_publisher.providers.google_monetization import GoogleMonetization
from app_publisher.providers.store_inspection import StoreInspection


def test_apple_app_and_build_with_fixed_responses(api_fixture):
    app = api_fixture.load("apple/app.json")["body"]["data"]
    build = api_fixture.load("apple/builds.json")["body"]["data"][0]
    prerelease = api_fixture.load("apple/pre-release-version.json")["body"]["data"]

    def handler(request):
        if request.url.path == f"/apps/{app['id']}":
            return api_fixture.response("apple/app.json")
        if request.url.path == "/builds":
            assert request.url.params["filter[app]"] == app["id"]
            return api_fixture.response("apple/builds.json")
        if request.url.path == f"/builds/{build['id']}/preReleaseVersion":
            return api_fixture.response("apple/pre-release-version.json")
        raise AssertionError(f"Unexpected mocked request: {request.method} {request.url.path}")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    version = AppleVersion(
        platform=prerelease["attributes"]["platform"],
        version=prerelease["attributes"]["version"],
        build_number=build["attributes"]["version"],
    )
    config = AppleConfig(app_id=app["id"], bundle_id=app["attributes"]["bundleId"], versions=[version])
    assert ApplePublisher(client, config).identify()["id"] == app["id"]
    assert AppleBuildManager(client, app["id"]).wait(version)["attributes"]["processingState"] == "VALID"


def test_subscription_availability_with_fixed_responses(api_fixture):
    declaration = AppleSubscriptionAvailability(plan_type="upfront", territories=["BRA"])
    availability = api_fixture.load("apple/subscription-plan-availabilities.json")["body"]["data"][0]

    def handler(request):
        if request.url.path == "/territories" or request.url.path.endswith("/availableTerritories"):
            return api_fixture.response("apple/available-territories.json")
        if request.url.path.endswith("/planAvailabilities"):
            return api_fixture.response("apple/subscription-plan-availabilities.json")
        raise AssertionError(f"Unexpected mocked request: {request.method} {request.url.path}")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    assert availability["attributes"]["planType"] == declaration.plan_type
    assert (
        AppleSubscriptionAvailabilityPublisher(client).synchronize(
            "subscription-monthly", [declaration], apply=True
        )
        == []
    )


def test_subscription_reconciliation_preserves_existing_fixed_prices(api_fixture):
    group = api_fixture.load("apple/subscription-groups.json")["body"]["data"][0]
    subscription = next(
        item
        for item in api_fixture.load("apple/subscriptions.json")["body"]["data"]
        if item["attributes"]["subscriptionPeriod"] == "ONE_MONTH"
    )
    price = api_fixture.load("apple/subscription-prices.json")["body"]["data"][0]
    availability = api_fixture.load("apple/subscription-plan-availabilities.json")["body"]["data"][0]

    def handler(request):
        if request.url.path.endswith("/subscriptionGroups"):
            return api_fixture.response("apple/subscription-groups.json")
        if request.url.path.endswith("/subscriptions"):
            return api_fixture.response("apple/subscriptions.json")
        if request.url.path.endswith("/planAvailabilities"):
            return api_fixture.response("apple/subscription-plan-availabilities.json")
        if request.url.path == "/territories" or request.url.path.endswith("/availableTerritories"):
            return api_fixture.response("apple/available-territories.json")
        if request.url.path.endswith("/prices"):
            assert request.url.params["include"] == "subscriptionPricePoint"
            return api_fixture.response("apple/subscription-prices.json")
        raise AssertionError(f"Unexpected mocked request: {request.method} {request.url.path}")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    item = AppleSubscription(
        product_id=subscription["attributes"]["productId"],
        name=subscription["attributes"]["name"],
        period=subscription["attributes"]["subscriptionPeriod"],
        prices=[
            AppleSubscriptionPrice(
                price_point_id=price["relationships"]["subscriptionPricePoint"]["data"]["id"],
                plan_type=price["attributes"]["planType"],
            )
        ],
        availability=[
            AppleSubscriptionAvailability(
                plan_type=availability["attributes"]["planType"], territories=["BRA"]
            )
        ],
    )
    declared = AppleSubscriptionGroup(
        reference_name=group["attributes"]["referenceName"], subscriptions=[item]
    )
    assert (
        AppleSubscriptions(client, "123").synchronize([declared], apply=True, allow_price_changes=True) == []
    )


def test_google_listing_reconciliation_with_fixed_response(api_fixture):
    subscription = api_fixture.load("google/subscription-monthly.json")["body"]

    def handler(request):
        assert request.method == "GET"
        assert (
            request.url.path
            == f"/applications/{subscription['packageName']}/subscriptions/{subscription['productId']}"
        )
        return api_fixture.response("google/subscription-monthly.json")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    entry = GoogleMonetizationProduct(
        product_id=subscription["productId"],
        update_mask=["listings"],
        regions_version="2026/01",
        data={"listings": subscription["listings"]},
    )
    assert GoogleMonetization(client, subscription["packageName"]).synchronize([entry], [], apply=True) == []


def test_firebase_disabled_service_response_is_not_treated_as_missing_project(api_fixture):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return api_fixture.response("firebase/project.json")

    client = APIClient("https://firebase.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    cloud = APIClient(
        "https://cloud.test",
        lambda: "synthetic-token",
        httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("No Cloud mutation is allowed"))
        ),
    )
    publisher = FirebasePublisher(
        client, cloud, FirebaseConfig(project_id="example-project", create_if_missing=True)
    )
    with pytest.raises(RemoteAPIError, match="HTTP 403"):
        publisher.ensure_project()
    assert len(calls) == 1


def test_fixture_files_have_stable_response_envelopes(api_fixture):
    paths = sorted(api_fixture.directory.rglob("*.json"))
    assert paths
    for path in paths:
        fixture = api_fixture.load(path.relative_to(api_fixture.directory).as_posix())
        assert isinstance(fixture["body"], dict)
        assert isinstance(fixture["status_code"], int)
        assert 100 <= fixture["status_code"] <= 599


def test_current_apple_version_state_with_fixed_responses(api_fixture):
    version = api_fixture.load("apple/app-store-versions.json")["body"]["data"][0]
    endpoints = {
        "/apps/123/appStoreVersions": "apple/app-store-versions.json",
        "/apps/123/reviewSubmissions": "apple/review-submissions.json",
        "/apps/123/betaGroups": "apple/beta-groups.json",
    }

    def handler(request):
        assert request.method == "GET"
        return api_fixture.response(endpoints[request.url.path])

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    config = AppleConfig(
        app_id="123", bundle_id="com.example.app", versions=[AppleVersion(platform="IOS", version="1.0.0")]
    )
    publisher = ApplePublisher(client, config)
    assert publisher.ensure_version(config.versions[0], publisher.versions(), apply=False) == version["id"]
    inspected = StoreInspection(client, "123").apple()
    assert inspected["versions"][0]["state"] == version["attributes"]["appVersionState"]


def test_uploaded_review_asset_waits_for_processing_with_fixed_response(api_fixture):
    from unittest.mock import Mock

    from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper

    fixture = api_fixture.load("apple/review-screenshot-uploaded.json")["body"]["data"]
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith(f"/{fixture['id']}")
        return api_fixture.response("apple/review-screenshot-uploaded.json")

    client = APIClient("https://api.test/v1", lambda: "synthetic-token", httpx.MockTransport(handler))
    publisher = AppleReviewAssetHelper(client, clock=Mock(side_effect=[0, 0, 2]), sleep=Mock())
    with pytest.raises(RemoteAPIError, match="timeout"):
        publisher.wait(fixture["type"], fixture["id"], fixture["attributes"]["sourceFileChecksum"], 1)
    assert len(calls) == 2
    publisher.sleep.assert_called_once_with(1)


def test_apple_image_specifications_use_fixed_api_reference_data(api_fixture, tmp_path):
    from PIL import Image

    from app_publisher.errors.configuration_error import ConfigurationError
    from app_publisher.providers.apple_asset_library import AppleAssetLibrary

    def handler(request):
        assert request.url.path == "/appAssetLibraryRefData"
        assert request.url.params["filter[features]"] == "APP_STORE_VERSIONS"
        return api_fixture.response("apple/asset-reference-data.json")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    library = AppleAssetLibrary(client, "123")
    reference = library.reference_data()
    group = library.resolve_group("IPAD_97_PROFILE", reference)
    valid = tmp_path / "tablet.png"
    Image.new("RGB", (2048, 1536)).save(valid)
    library.validate_dimensions(valid, group, reference)
    invalid = tmp_path / "incorrect-size.png"
    Image.new("RGB", (780, 1688)).save(invalid)
    with pytest.raises(ConfigurationError, match="dimensions"):
        library.validate_dimensions(invalid, group, reference)
    with pytest.raises(ConfigurationError, match="ambiguous"):
        library.resolve_group("IPAD_97_DISPLAY", reference)


def test_completed_review_asset_verifies_fixed_response_checksum(api_fixture):
    from unittest.mock import Mock

    from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper

    fixture = api_fixture.load("apple/review-screenshot-complete.json")["body"]["data"]

    def handler(request):
        assert request.method == "GET"
        assert request.url.path.endswith(f"/{fixture['id']}")
        return api_fixture.response("apple/review-screenshot-complete.json")

    client = APIClient("https://api.test/v1", lambda: "synthetic-token", httpx.MockTransport(handler))
    sleep = Mock()
    AppleReviewAssetHelper(client, sleep=sleep).wait(
        fixture["type"], fixture["id"], fixture["attributes"]["sourceFileChecksum"], 1
    )
    sleep.assert_not_called()


def test_app_review_attachments_are_idempotent_with_fixed_responses(api_fixture, tmp_path, monkeypatch):
    from unittest.mock import Mock

    from PIL import Image

    from app_publisher.models.apple_review import AppleReview
    from app_publisher.models.apple_review_attachment import AppleReviewAttachment
    from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper
    from app_publisher.providers.apple_review_manager import AppleReviewManager

    attachment = api_fixture.load("apple/app-review-attachments.json")["body"]["data"][0]
    assert attachment["attributes"]["assetDeliveryState"]["state"] == "COMPLETE"
    image = tmp_path / "guide.png"
    Image.new("RGB", (20, 20)).save(image)
    monkeypatch.setattr(
        AppleReviewAssetHelper, "checksum", Mock(return_value=attachment["attributes"]["sourceFileChecksum"])
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/appStoreReviewDetail"):
            return api_fixture.response("apple/app-review-details.json")
        assert request.url.path.endswith("/appStoreReviewAttachments")
        return api_fixture.response("apple/app-review-attachments.json")

    client = APIClient("https://api.test/v1", lambda: "synthetic-token", httpx.MockTransport(handler))
    review = AppleReview(attachments=[AppleReviewAttachment(path=image.name)])
    assert (
        AppleReviewManager(client, "123").synchronize_details(
            "version", review, directory=tmp_path, apply=True
        )
        == []
    )
    assert len(calls) == 2


def test_app_review_contact_error_preserves_remote_failure_without_write_retry(api_fixture):
    from app_publisher.models.apple_review import AppleReview
    from app_publisher.providers.apple_review_manager import AppleReviewManager

    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return api_fixture.response("apple/app-review-details.json")
        assert request.method == "PATCH"
        return api_fixture.response("apple/app-review-contact-required.json")

    client = APIClient("https://api.test/v1", lambda: "synthetic-token", httpx.MockTransport(handler))
    with pytest.raises(RemoteAPIError, match="contactFirstName") as failure:
        AppleReviewManager(client, "123").synchronize_details(
            "version", AppleReview(demo_account_required=False), apply=True
        )
    assert failure.value.status_code == 409
    assert "contactPhone" in str(failure.value)
    assert [request.method for request in calls] == ["GET", "PATCH"]


def test_google_store_metadata_noop_uses_fixed_api_responses(api_fixture, tmp_path):
    from app_publisher.models.google_config import GoogleConfig
    from app_publisher.models.google_store_details import GoogleStoreDetails
    from app_publisher.models.project_config import ProjectConfig
    from app_publisher.providers.google_publisher import GooglePublisher

    details = api_fixture.load("google/store-details.json")["body"]
    listings = api_fixture.load("google/store-listings.json")["body"]["listings"]
    config = GoogleConfig(
        package_name="com.example.app",
        store_details=GoogleStoreDetails(
            default_language=details["defaultLanguage"],
            contact_website=details["contactWebsite"],
            contact_email=details["contactEmail"],
        ),
    )
    project = ProjectConfig.model_validate(
        {
            "schema_version": 1,
            "app": {"id": "example", "paid": False},
            "google": config,
            "publication": {"submit_for_review": True},
            "locales": {
                item["language"]: {
                    "common": {"name": item["title"], "description": item["fullDescription"]},
                    "google": {"short_description": item["shortDescription"]},
                }
                for item in listings
            },
        }
    )
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert request.url.path.endswith("/edits")
            return api_fixture.response("google/edit.json")
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        assert request.method == "GET"
        if request.url.path.endswith("/details"):
            return api_fixture.response("google/store-details.json")
        assert request.url.path.endswith("/listings")
        return api_fixture.response("google/store-listings.json")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    assert GooglePublisher(client, config).synchronize(project, tmp_path, apply=True) == []
    assert [request.method for request in calls] == ["POST", "GET", "GET", "DELETE"]


def test_complete_review_contact_and_notes_are_idempotent_with_fixed_response(api_fixture):
    from app_publisher.models.apple_review import AppleReview
    from app_publisher.providers.apple_review_manager import AppleReviewManager

    attributes = api_fixture.load("apple/app-review-details-complete.json")["body"]["data"]["attributes"]
    review = AppleReview(
        contact_first_name=attributes["contactFirstName"],
        contact_last_name=attributes["contactLastName"],
        contact_email=attributes["contactEmail"],
        contact_phone=attributes["contactPhone"],
        demo_account_required=attributes["demoAccountRequired"],
        notes=attributes["notes"],
    )
    assert review.demo_account_required is False
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith("/appStoreReviewDetail")
        return api_fixture.response("apple/app-review-details-complete.json")

    client = APIClient("https://api.test", lambda: "synthetic-token", httpx.MockTransport(handler))
    assert AppleReviewManager(client, "123").synchronize_details("version", review, apply=True) == []
    assert len(calls) == 1
