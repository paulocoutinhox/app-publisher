import httpx
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.google_store_details import GoogleStoreDetails
from app_publisher.providers.google_publisher import GooglePublisher


def test_details_sync_diff_update_and_idempotency():
    recorder = Recorder(
        lambda r: httpx.Response(
            200, json={"contactEmail": "existing@example.com"} if r.method == "GET" else {}
        )
    )
    api = APIClient("https://google.example", lambda: "token", httpx.MockTransport(recorder))
    publisher = GooglePublisher(api, GoogleConfig(package_name="com.demo"))
    assert publisher.synchronize_details("edit", GoogleStoreDetails(), apply=True) == []
    assert (
        publisher.synchronize_details(
            "edit", GoogleStoreDetails(contact_email="existing@example.com"), apply=True
        )
        == []
    )
    details = GoogleStoreDetails(
        contact_email="new@example.com",
        contact_website="https://example.com",
        contact_phone="+5511999999999",
        default_language="pt-BR",
    )
    assert len(publisher.synchronize_details("edit", details, apply=False)) == 1
    assert not [req for req in recorder.calls if req.method == "PATCH"]
    assert len(publisher.synchronize_details("edit", details, apply=True)) == 1
    assert len([req for req in recorder.calls if req.method == "PATCH"]) == 1


def test_google_store_details_integrated(project, tmp_path):
    project.google.store_details = GoogleStoreDetails(contact_email="test@example.com")

    def handler(req):
        if req.url.path.endswith("/edits") and req.method == "POST":
            return httpx.Response(200, json={"id": "edit"})
        if req.url.path.endswith("/details"):
            return httpx.Response(200, json={"contactEmail": "old"})
        if req.url.path.endswith("/listings"):
            return httpx.Response(
                200,
                json={
                    "listings": [
                        {
                            "language": "en-US",
                            "title": "Demo",
                            "shortDescription": "Short demo",
                            "fullDescription": "A demo app",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    publisher = GooglePublisher(
        APIClient("https://google.example", lambda: "token", httpx.MockTransport(rec)), project.google
    )
    changes = publisher.synchronize(project, tmp_path, apply=True)
    assert any("store details" in value for value in changes)
    assert any(req.url.path.endswith("/details") and req.method == "PATCH" for req in rec.calls)
