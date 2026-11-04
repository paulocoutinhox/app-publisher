import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import Recorder
from pydantic import ValidationError
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_listing_deletion import GoogleListingDeletion
from app_publisher.models.google_release import GoogleRelease
from app_publisher.models.store_review_reply import StoreReviewReply
from app_publisher.providers.apple_store_reviews import AppleStoreReviews
from app_publisher.providers.google_publisher import GooglePublisher
from app_publisher.providers.google_store_reviews import GoogleStoreReviews


def test_new_model_restrictions(project):
    with pytest.raises(ValidationError):
        StoreReviewReply(review_id="../../wrong", text="text")
    with pytest.raises(ValidationError):
        GoogleListingDeletion(locale="../bad")
    with pytest.raises(ValidationError):
        project.google.listing_deletions = [
            GoogleListingDeletion(locale="pt-BR"),
            GoogleListingDeletion(locale="pt-BR"),
        ]
    with pytest.raises(ValidationError):
        project.google.review_replies = [
            StoreReviewReply(review_id="a", text="1"),
            StoreReviewReply(review_id="a", text="2"),
        ]
    with pytest.raises(ValidationError):
        project.apple.review_replies = [
            StoreReviewReply(review_id="a", text="1"),
            StoreReviewReply(review_id="a", text="2"),
        ]
    with pytest.raises(ValidationError):
        GoogleRelease(
            deobfuscation_files=[{"version_code": 0, "file_type": "proguard", "path": "symbols.txt"}]
        )


def test_deletion_validation_in_configuration(project, tmp_path):
    project.google.listing_deletions = [GoogleListingDeletion(locale="en-US")]
    assert "Cannot update and delete" in str(
        validate_project(project, tmp_path / "app.yaml", local_files="none")
    )
    project.locales["en-US"].google = None
    project.google.store_details = {"default_language": "en-US"}
    assert "Cannot delete the configured default" in str(
        validate_project(project, tmp_path / "app.yaml", local_files="none")
    )
    project.google.store_details = None
    project.google.release.deobfuscation_files = [
        {"version_code": 8, "file_type": "proguard", "path": "symbols.txt"}
    ]
    assert "Missing deobfuscation file" in str(
        validate_project(project, tmp_path / "app.yaml", local_files="all")
    )


def test_google_listing_deletion_empty(project):
    pub = GooglePublisher(APIClient("https://api.test", lambda: "t"), project.google)
    assert pub.delete_listings([], apply=True) == []
    pub.api.close()


def test_google_listing_deletion_requires_confirmation(project):
    pub = GooglePublisher(APIClient("https://api.test", lambda: "t"), project.google)
    with pytest.raises(UnsafeOperationError, match="confirm_deletion"):
        pub.delete_listings([GoogleListingDeletion(locale="pt-BR")], apply=True)
    pub.api.close()


@pytest.mark.parametrize(
    "apply,remote,present",
    [(False, True, True), (True, True, True), (True, False, False), (False, False, False)],
)
def test_google_listing_deletion_state(project, apply, remote, present):
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET":
            return httpx.Response(200, json={"listings": [{"language": "pt-BR"}] if remote else []})
        return httpx.Response(200, json={})

    recorder = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(recorder)), project.google
    )
    changes = pub.delete_listings([GoogleListingDeletion(locale="pt-BR", confirm_deletion=True)], apply=apply)
    assert bool(changes) is present
    assert any(request.method == "POST" and ":commit" in request.url.path for request in recorder.calls) is (
        apply and remote
    )
    assert any(
        request.method == "DELETE" and request.url.path.endswith("/edits/edit") for request in recorder.calls
    ) is not (apply and remote)
    pub.api.close()


def test_google_listing_deletion_failure_cleans_edit(project):
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET":
            return httpx.Response(200, json={"listings": [{"language": "pt-BR"}]})
        if req.url.path.endswith("/pt-BR"):
            return httpx.Response(500, json={})
        return httpx.Response(200, json={})

    recorder = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(recorder)), project.google
    )
    with pytest.raises(RemoteAPIError):
        pub.delete_listings([GoogleListingDeletion(locale="pt-BR", confirm_deletion=True)], apply=True)
    assert any(req.method == "DELETE" and req.url.path.endswith("/edits/edit") for req in recorder.calls)
    pub.api.close()


@pytest.mark.parametrize("filename,resource", [("app.aab", "bundles"), ("app.apk", "apks")])
def test_upload_bundles_and_apks(project, tmp_path, filename, resource):
    (tmp_path / filename).write_bytes(b"binary")
    project.google.release.artifact = filename
    project.google.release.version_codes = ["99"]
    recorder = Recorder(lambda request: httpx.Response(200, json={"versionCode": 99}))
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(recorder)), project.google
    )
    assert pub.upload_bundle("edit", tmp_path) == "99"
    assert recorder.calls[0].url.path.endswith(f"/{resource}")
    assert recorder.calls[0].content == b"binary"
    pub.api.close()


def test_google_media_errors(project, tmp_path):
    path = tmp_path / "wrong.txt"
    path.write_bytes(b"data")
    project.google.release.artifact = "wrong.txt"
    pub = GooglePublisher(APIClient("https://api.test", lambda: "t"), project.google)
    with pytest.raises(UnsafeOperationError, match="AAB or APK"):
        pub.upload_bundle("edit", tmp_path)
    pub.api.close()
    for response in [
        httpx.Response(403, json={"error": "denied"}),
        httpx.Response(200, json=["bad"]),
        httpx.Response(200, text="bad-json"),
    ]:
        pub = GooglePublisher(
            APIClient("https://api.test", lambda: "t", httpx.MockTransport(lambda _: response)),
            project.google,
        )
        with pytest.raises((RemoteAPIError, ValueError)):
            pub.upload_media("edit", path, "apks")
        pub.api.close()


def test_google_deobfuscation_upload(project, tmp_path):
    (tmp_path / "mapping.txt").write_text("com.example -> a:\n")
    project.google.release.deobfuscation_files = [
        {"version_code": 8, "file_type": "proguard", "path": "mapping.txt"}
    ]

    def handler(request):
        if request.method == "POST" and request.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "e"})
        if "deobfuscationFiles" in request.url.path:
            return httpx.Response(200, json={"deobfuscationFile": {"symbolType": "proguard"}})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    assert pub.publish_release(tmp_path, {}, apply=True)
    assert any("apks/8/deobfuscationFiles/proguard" in req.url.path and req.content for req in rec.calls)
    pub.api.close()


def test_google_deobfuscation_version_mismatch(project, tmp_path):
    project.google.release.deobfuscation_files = [
        {"version_code": 42, "file_type": "nativeCode", "path": "symbol.zip"}
    ]

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "e"})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    with pytest.raises(UnsafeOperationError, match="not part of this release"):
        pub.publish_release(tmp_path, {}, apply=True)
    assert any(req.method == "DELETE" for req in rec.calls)
    pub.api.close()


def test_apple_reviews_empty():
    api = APIClient("https://api.test", lambda: "t")
    assert AppleStoreReviews(api, "123").synchronize([], apply=True) == []
    api.close()


def test_apple_reviews_confirmation():
    api = APIClient("https://api.test", lambda: "t")
    with pytest.raises(UnsafeOperationError, match="confirm_publication"):
        AppleStoreReviews(api, "123").synchronize(
            [StoreReviewReply(review_id="a", text="Thank you")], apply=True
        )
    api.close()


@pytest.mark.parametrize("apply,existing", [(True, None), (False, "Different"), (True, "Thank you")])
def test_apple_review_sync(apply, existing):
    def handler(req):
        if req.url.path.endswith("/customerReviews"):
            return httpx.Response(200, json={"data": [{"id": "1234", "type": "customerReviews"}]})
        if req.url.path.endswith("/customerReviews/1234"):
            return httpx.Response(
                200,
                json={
                    "included": [
                        {"type": "customerReviewResponses", "attributes": {"responseBody": existing}}
                    ]
                    if existing is not None
                    else []
                },
            )
        return httpx.Response(200, json={"data": {"id": "response"}})

    rec = Recorder(handler)
    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec))
    pub = AppleStoreReviews(api, "app")
    assert len(pub.list_reviews()) == 1
    changes = pub.synchronize(
        [StoreReviewReply(review_id="1234", text="Thank you", confirm_publication=True)], apply=apply
    )
    assert bool(changes) is (existing != "Thank you")
    assert any(req.method == "POST" for req in rec.calls) is (apply and existing != "Thank you")
    api.close()


def test_apple_review_wrong_app():
    api = APIClient(
        "https://api.test", lambda: "t", httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
    )
    with pytest.raises(UnsafeOperationError, match="not in the configured app"):
        AppleStoreReviews(api, "123").synchronize(
            [StoreReviewReply(review_id="other", text="Thanks")], apply=False
        )
    api.close()


def test_google_reviews_empty_and_confirmation():
    api = APIClient("https://api.test", lambda: "t")
    pub = GoogleStoreReviews(api, "com.demo")
    assert pub.synchronize([], apply=True) == []
    with pytest.raises(UnsafeOperationError, match="confirm_publication"):
        pub.synchronize([StoreReviewReply(review_id="r1", text="Hi")], apply=True)
    api.close()


def test_google_review_pagination():
    def handler(req):
        token = req.url.params.get("token")
        if token is None:
            return httpx.Response(
                200, json={"reviews": [{"reviewId": "r1"}], "tokenPagination": {"nextPageToken": "next"}}
            )
        return httpx.Response(200, json={"reviews": [{"reviewId": "r2"}]})

    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler))
    assert [entry["reviewId"] for entry in GoogleStoreReviews(api, "com.demo").list_reviews()] == ["r1", "r2"]
    api.close()


def test_google_review_pagination_cycle():
    api = APIClient(
        "https://api.test",
        lambda: "t",
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"reviews": [], "tokenPagination": {"nextPageToken": "again"}})
        ),
    )
    with pytest.raises(RemoteAPIError, match="repeated a token"):
        GoogleStoreReviews(api, "com.demo").list_reviews()
    api.close()


@pytest.mark.parametrize("apply,existing", [(True, "Before"), (False, "Before"), (True, "Thank you")])
def test_google_review_sync(apply, existing):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(
                200,
                json={
                    "reviews": [{"reviewId": "r1", "comments": [{"developerComment": {"text": existing}}]}]
                },
            )
        return httpx.Response(200, json={"result": {"replyText": "Thank you"}})

    rec = Recorder(handler)
    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec))
    changes = GoogleStoreReviews(api, "com.demo").synchronize(
        [StoreReviewReply(review_id="r1", text="Thank you", confirm_publication=True)], apply=apply
    )
    assert bool(changes) is (existing != "Thank you")
    assert any(req.method == "POST" for req in rec.calls) is (apply and existing != "Thank you")
    api.close()


def test_google_review_validation():
    api = APIClient(
        "https://api.test",
        lambda: "t",
        httpx.MockTransport(lambda _: httpx.Response(200, json={"reviews": []})),
    )
    with pytest.raises(UnsafeOperationError, match="350"):
        GoogleStoreReviews(api, "com.demo").synchronize(
            [StoreReviewReply(review_id="r1", text="a" * 351)], apply=False
        )
    with pytest.raises(UnsafeOperationError, match="not in the configured app"):
        GoogleStoreReviews(api, "com.demo").synchronize(
            [StoreReviewReply(review_id="r1", text="OK")], apply=False
        )
    api.close()


def test_google_review_no_developer_comment():
    rec = Recorder(
        lambda _: httpx.Response(
            200, json={"reviews": [{"reviewId": "r1", "comments": [{"userComment": {"text": "Hello"}}]}]}
        )
    )
    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec))
    assert GoogleStoreReviews(api, "com.demo").synchronize(
        [StoreReviewReply(review_id="r1", text="Hello")], apply=False
    )
    api.close()


def test_engine_review_and_listing_commands(project, tmp_path, monkeypatch):
    events = []
    publisher = SimpleNamespace(
        api=SimpleNamespace(close=lambda: events.append("close")),
        identify=lambda: events.append("identify"),
        config=project.google,
        delete_listings=lambda entries, apply: [f"deleted {len(entries)}"],
    )
    monkeypatch.setattr(PublicationEngine, "google", lambda self: publisher)
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    assert engine.delete_listings(apply=False) == ["deleted 0"]
    assert events == ["close"]
    project.google = None
    with pytest.raises(ConfigurationError):
        engine.delete_listings(apply=False)


def test_engine_reviews_routing(project, tmp_path, monkeypatch):
    events = []
    apple = SimpleNamespace(
        api=SimpleNamespace(close=lambda: events.append("apple close")),
        identify=lambda: events.append("identify"),
        config=project.apple,
    )
    google = SimpleNamespace(
        api=SimpleNamespace(close=lambda: events.append("google close")), config=project.google
    )
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: apple)
    monkeypatch.setattr(PublicationEngine, "google", lambda self: google)
    monkeypatch.setattr(AppleStoreReviews, "synchronize", lambda self, replies, apply: ["apple review"])
    monkeypatch.setattr(GoogleStoreReviews, "synchronize", lambda self, replies, apply: ["google review"])
    monkeypatch.setattr(AppleStoreReviews, "list_reviews", lambda self: [{"id": "apple"}])
    monkeypatch.setattr(GoogleStoreReviews, "list_reviews", lambda self: [{"reviewId": "google"}])
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    assert engine.reply_reviews(apply=False) == ["apple review", "google review"]
    assert engine.reply_reviews(apply=False, provider="apple") == ["apple review"]
    assert engine.list_reviews() == {"apple": [{"id": "apple"}], "google": [{"reviewId": "google"}]}
    assert engine.list_reviews(provider="google") == {"google": [{"reviewId": "google"}]}
    assert events.count("identify") == 3


def test_cli_review_operations(monkeypatch, tmp_path):
    from app_publisher import cli

    engine = SimpleNamespace(
        delete_listings=lambda apply: ["deleted"],
        reply_reviews=lambda apply, provider: ["replied"],
        list_reviews=lambda provider: {"google": []},
    )
    monkeypatch.setattr(cli, "open_engine", lambda _: engine)
    runner = CliRunner()
    assert runner.invoke(app, ["delete-listings", str(tmp_path / "app.yaml")]).exit_code == 0
    assert runner.invoke(app, ["reply-reviews", str(tmp_path / "app.yaml")]).exit_code == 0
    result = runner.invoke(app, ["reviews", str(tmp_path / "app.yaml")])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["google"] == []


def test_google_listing_deletion_mixed_existing_and_missing(project):
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET":
            return httpx.Response(200, json={"listings": [{"language": "pt-BR"}]})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    pub = GooglePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), project.google
    )
    assert pub.delete_listings(
        [
            GoogleListingDeletion(locale="pt-BR", confirm_deletion=True),
            GoogleListingDeletion(locale="fr-FR", confirm_deletion=True),
        ],
        apply=True,
    ) == ["Google listing pt-BR: delete"]
    assert sum(req.method == "DELETE" and req.url.path.endswith("/pt-BR") for req in rec.calls) == 1
    assert not any(req.method == "DELETE" and req.url.path.endswith("/fr-FR") for req in rec.calls)
    pub.api.close()


def test_google_review_duplicates_validate_without_other_errors(project):
    with pytest.raises(ValidationError, match="review replies"):
        project.google.review_replies = [
            StoreReviewReply(review_id="r1", text="One"),
            StoreReviewReply(review_id="r1", text="Two"),
        ]


def test_google_deobfuscation_file_exists(project, tmp_path):
    project.google.release.deobfuscation_files = [
        {"version_code": 8, "file_type": "nativeCode", "path": "symbols.zip"}
    ]
    (tmp_path / "symbols.zip").write_bytes(b"archive")
    assert not any(
        "deobfuscation file" in item
        for item in validate_project(project, tmp_path / "app.yaml", local_files="all")
    )
    assert not any(
        "deobfuscation file" in item
        for item in validate_project(project, tmp_path / "app.yaml", local_files="none")
    )


def test_google_listing_deletion_no_conflict(project, tmp_path):
    project.google.listing_deletions = [GoogleListingDeletion(locale="pt-BR")]
    project.google.store_details = {"default_language": "en-US"}
    assert not any(
        "delete" in item for item in validate_project(project, tmp_path / "app.yaml", local_files="none")
    )


def test_engine_review_routes_when_provider_missing(project, tmp_path, monkeypatch):
    project.google = None
    monkeypatch.setattr(AppleStoreReviews, "list_reviews", lambda self: [])
    monkeypatch.setattr(AppleStoreReviews, "synchronize", lambda self, replies, apply: [])
    apple = SimpleNamespace(api=SimpleNamespace(close=lambda: None), identify=lambda: None)
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: apple)
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    assert engine.list_reviews(provider="all") == {"apple": []}
    assert engine.reply_reviews(apply=False, provider="all") == []
    project.apple = None
    assert engine.list_reviews() == {}
    assert engine.reply_reviews(apply=False) == []


def test_google_no_release_validation(project, tmp_path):
    project.google.release = None
    assert validate_project(project, tmp_path / "app.yaml", local_files="none") == []


def test_google_review_id_accepts_provider_format():
    assert StoreReviewReply(review_id="gp:AOqpTO.AB-123", text="Thank you").review_id == "gp:AOqpTO.AB-123"
