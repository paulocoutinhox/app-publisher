import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_review import AppleReview
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_monetization_product import GoogleMonetizationProduct
from app_publisher.providers.apple_beta_manager import AppleBetaManager
from app_publisher.providers.apple_commercial import AppleCommercial
from app_publisher.providers.apple_review_manager import AppleReviewManager
from app_publisher.providers.firebase_certificates import FirebaseCertificates
from app_publisher.providers.google_monetization import GoogleMonetization


def api(handler):
    rec = Recorder(handler)
    return APIClient("https://publisher.example", lambda: "test", httpx.MockTransport(rec)), rec


def test_apple_review_details_update_create_and_env(monkeypatch):
    def handler(req):
        if req.url.path.endswith("appStoreReviewDetail"):
            return httpx.Response(
                200, json={"data": {"id": "review-id", "attributes": {"contactEmail": "old"}}}
            )
        return httpx.Response(200, json={})

    client, rec = api(handler)
    manager = AppleReviewManager(client, "123")
    assert manager.synchronize_details("version", AppleReview(), apply=True) == []
    changes = manager.synchronize_details(
        "version", AppleReview(contact_email="review@example.com"), apply=False
    )
    assert len(changes) == 1
    assert (
        manager.synchronize_details("version", AppleReview(contact_email="review@example.com"), apply=True)
        == changes
    )
    assert any(req.method == "PATCH" for req in rec.calls)
    monkeypatch.setenv("DEMO_USER", "demo")
    assert manager.synchronize_details("version", AppleReview(demo_account_name_env="DEMO_USER"), apply=True)
    with pytest.raises(ConfigurationError, match="environment variable"):
        manager.synchronize_details(
            "version", AppleReview(demo_account_password_env="MISSING_DEMO_PASSWORD_XX"), apply=True
        )
    empty, calls = api(lambda r: httpx.Response(200, json={"data": None}))
    AppleReviewManager(empty, "123").synchronize_details("v", AppleReview(notes="Instructions"), apply=True)
    assert any(r.url.path == "/appStoreReviewDetails" and r.method == "POST" for r in calls.calls)
    client2, _ = api(
        lambda r: httpx.Response(200, json={"data": {"id": "id", "attributes": {"notes": "same"}}})
    )
    assert (
        AppleReviewManager(client2, "123").synchronize_details("v", AppleReview(notes="same"), apply=True)
        == []
    )


def test_apple_review_submits_and_prevents_duplicate():
    def handler(req):
        if req.url.path == "/apps/123/reviewSubmissions":
            return httpx.Response(200, json={"data": []})
        if req.url.path == "/reviewSubmissions" and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "sub-id"}})
        return httpx.Response(200, json={})

    client, rec = api(handler)
    manager = AppleReviewManager(client, "123")
    assert "submit version" in manager.submit([("version", "IOS")], apply=False)[0]
    assert "sub-id" in manager.submit([("version", "IOS")], apply=True)[0]
    assert len([r for r in rec.calls if r.method == "POST"]) == 2
    other, _ = api(
        lambda r: httpx.Response(
            200, json={"data": [{"attributes": {"state": "WAITING_FOR_REVIEW", "platform": "IOS"}}]}
        )
    )
    with pytest.raises(UnsafeOperationError, match="already active"):
        AppleReviewManager(other, "123").submit([("v", "IOS")], apply=False)


def test_apple_beta_group_and_price():
    def handler(req):
        if req.url.path.endswith("/preReleaseVersion"):
            return httpx.Response(200, json={"data": {"attributes": {"version": "2.0", "platform": "IOS"}}})
        if req.url.path == "/builds":
            return httpx.Response(
                200,
                json={"data": [{"id": "build", "attributes": {"version": "42", "processingState": "VALID"}}]},
            )
        if req.url.path.endswith("/builds"):
            return httpx.Response(200, json={"data": []})
        if "appPriceSchedule" in req.url.path and "relationships" not in req.url.path:
            return httpx.Response(200, json={"data": {"id": "price-id"}})
        if "baseTerritory" in req.url.path:
            return httpx.Response(200, json={"data": {"id": "BRA"}})
        return httpx.Response(200, json={})

    client, rec = api(handler)
    beta = AppleBetaManager(client, "123")
    version = AppleVersion(platform="IOS", version="2.0", build_number="42", beta={"group_ids": ["group-id"]})
    assert len(beta.distribute(version, apply=False)) == 1
    assert len(beta.distribute(version, apply=True)) == 1
    assert any(req.method == "POST" for req in rec.calls)
    assert AppleCommercial(client, "123").verify_base_territory("BRA")
    with pytest.raises(UnsafeOperationError, match="expected USA"):
        AppleCommercial(client, "123").verify_base_territory("USA")
    with pytest.raises(UnsafeOperationError, match="build number"):
        beta.distribute(AppleVersion(platform="IOS", version="2.0", beta={"group_ids": ["g"]}), apply=True)
    assert beta.distribute(AppleVersion(platform="IOS", version="2.0"), apply=True) == []
    no_build, _ = api(lambda r: httpx.Response(200, json={"data": []}))
    with pytest.raises(UnsafeOperationError, match="Expected one"):
        AppleBetaManager(no_build, "123").distribute(version, apply=False)

    def existing_handler(request):
        if request.url.path.endswith("/preReleaseVersion"):
            return httpx.Response(200, json={"data": {"attributes": {"version": "2.0", "platform": "IOS"}}})
        return httpx.Response(
            200, json={"data": [{"id": "build", "attributes": {"version": "42", "processingState": "VALID"}}]}
        )

    existing, calls = api(existing_handler)
    assert AppleBetaManager(existing, "123").distribute(version, apply=True) == []
    assert not [r for r in calls.calls if r.method == "POST"]


def test_firebase_certificates_create_once():
    def handler(req):
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "certificates": [
                        {
                            "shaHash": "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD",
                            "certType": "SHA_256",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    client, rec = api(handler)
    sync = FirebaseCertificates(client)
    assert sync.synchronize("projects/demo/androidApps/id", []) == []
    entries = [
        {"sha_hash": "AABBCCDDEEFF00112233445566778899AABBCCDD", "certificate_type": "SHA_256"},
        {"sha_hash": "C" * 40, "certificate_type": "SHA_1"},
    ]
    from app_publisher.models.android_certificate import AndroidCertificate

    assert (
        len(
            sync.synchronize(
                "projects/demo/androidApps/id", [AndroidCertificate.model_validate(item) for item in entries]
            )
        )
        == 1
    )
    assert len([req for req in rec.calls if req.method == "POST"]) == 1


def test_google_monetization_read_diff_write_and_identity():
    data = {"listings": [{"languageCode": "en-US", "title": "Example"}]}
    subscription = GoogleMonetizationProduct(
        product_id="premium", update_mask=["listings"], regions_version="2026/10", data=data
    )

    def handler(req):
        if req.method == "GET":
            return httpx.Response(404, json={"error": "Not found"})
        return httpx.Response(200, json={})

    client, rec = api(handler)
    publisher = GoogleMonetization(client, "com.demo")
    assert len(publisher.synchronize([subscription], [subscription], apply=False)) == 2
    assert len(publisher.synchronize([subscription], [], apply=True)) == 1
    assert any(
        req.method == "PATCH" and req.url.params.get("regionsVersion.version") == "2026/10"
        for req in rec.calls
    )
    with pytest.raises(UnsafeOperationError, match="identity conflicts"):
        publisher.synchronize(
            [
                GoogleMonetizationProduct(
                    product_id="premium",
                    update_mask=["listings"],
                    regions_version="1",
                    data={"productId": "wrong"},
                )
            ],
            [],
            apply=False,
        )
    with pytest.raises(UnsafeOperationError, match="Nested update masks"):
        publisher.synchronize(
            [
                GoogleMonetizationProduct(
                    product_id="premium",
                    update_mask=["listings.title"],
                    regions_version="1",
                    data={"listings": []},
                )
            ],
            [],
            apply=False,
        )
    match, _ = api(lambda req: httpx.Response(200, json={"listings": data["listings"]}))
    assert GoogleMonetization(match, "com.demo").synchronize([subscription], [], apply=True) == []
    other, _ = api(lambda req: httpx.Response(403, json={"error": "Forbidden"}))
    with pytest.raises(RemoteAPIError, match="HTTP 403"):
        GoogleMonetization(other, "com.demo").read("applications/com.demo/subscriptions/premium")


def test_review_detail_404_and_other_remote_error():
    missing, _ = api(
        lambda r: (
            httpx.Response(404, json={"error": "Not found"})
            if r.method == "GET"
            else httpx.Response(201, json={"data": {"id": "created"}})
        )
    )
    assert AppleReviewManager(missing, "123").synchronize_details("v", AppleReview(notes="Demo"), apply=True)
    forbidden, _ = api(lambda r: httpx.Response(403, json={"error": "Permission denied"}))
    with pytest.raises(RemoteAPIError, match="HTTP 403"):
        AppleReviewManager(forbidden, "123").synchronize_details("v", AppleReview(notes="Demo"), apply=True)


def test_review_versions_grouped_by_platform():
    def handler(req):
        if req.url.path.endswith("reviewSubmissions") and req.method == "GET":
            return httpx.Response(200, json={"data": []})
        if req.url.path == "/reviewSubmissions" and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "review"}})
        return httpx.Response(200, json={})

    client, rec = api(handler)
    manager = AppleReviewManager(client, "123")
    result = manager.submit([("ios-version", "IOS"), ("mac-version", "MAC_OS")], apply=True)
    assert len(result) == 2
    assert "IOS" in result[0] and "MAC_OS" in result[1]
    assert len([r for r in rec.calls if r.url.path == "/reviewSubmissionItems"]) == 2
    assert len([r for r in rec.calls if r.url.path == "/reviewSubmissions" and r.method == "POST"]) == 2
