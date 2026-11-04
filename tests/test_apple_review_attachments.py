import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.sync_plan import asset_manifest
from app_publisher.core.validation import validate_project
from app_publisher.core.workflow_runner import WorkflowRunner
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_review import AppleReview
from app_publisher.models.apple_review_attachment import AppleReviewAttachment
from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper
from app_publisher.providers.apple_review_attachment_publisher import AppleReviewAttachmentPublisher
from app_publisher.providers.apple_review_manager import AppleReviewManager


@pytest.fixture
def attachment(tmp_path):
    path = tmp_path / "guide.txt"
    path.write_bytes(b"Example review instructions.")
    return path


def record(path, state="COMPLETE", **attributes):
    digest = AppleReviewAssetHelper.checksum(path)
    return {
        "type": "appStoreReviewAttachments",
        "id": "attachment",
        "attributes": {
            "fileName": f"{path.stem}-{digest}{path.suffix}",
            "sourceFileChecksum": digest,
            "assetDeliveryState": {"state": state},
            **attributes,
        },
    }


def test_attachment_upload_and_unchanged_file(attachment):
    calls = []
    uploaded = False

    def handler(request):
        nonlocal uploaded
        calls.append(request)
        if request.url.host == "upload.example.invalid":
            assert "authorization" not in request.headers
            assert request.content == attachment.read_bytes()
            return httpx.Response(200)
        if request.url.path.endswith("/appStoreReviewAttachments") and request.method == "GET":
            return httpx.Response(200, json={"data": [record(attachment)] if uploaded else []})
        if request.method == "POST":
            data = json.loads(request.content)["data"]
            assert data["relationships"]["appStoreReviewDetail"]["data"] == {
                "type": "appStoreReviewDetails",
                "id": "review",
            }
            return httpx.Response(
                201,
                json={
                    "data": record(
                        attachment,
                        "AWAITING_UPLOAD",
                        uploadOperations=[
                            {
                                "offset": 0,
                                "length": attachment.stat().st_size,
                                "method": "PUT",
                                "url": "https://upload.example.invalid/attachment",
                            }
                        ],
                    )
                },
            )
        if request.method == "PATCH":
            uploaded = True
            assert json.loads(request.content)["data"]["attributes"]["uploaded"] is True
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"data": record(attachment)})

    api = APIClient("https://api.test/v1", lambda: "token", httpx.MockTransport(handler))
    publisher = AppleReviewAttachmentPublisher(api)
    item = AppleReviewAttachment(path=attachment.name)
    assert publisher.synchronize("review", [], attachment.parent, apply=True) == []
    assert publisher.synchronize("review", [item], attachment.parent, apply=False)
    assert all(request.method == "GET" for request in calls)
    assert publisher.synchronize("review", [item], attachment.parent, apply=True)
    assert publisher.synchronize("review", [item], attachment.parent, apply=True) == []
    assert len([request for request in calls if request.method == "POST"]) == 1


def test_attachment_identity_and_replacement_are_explicit(attachment):
    same = record(attachment)
    assert AppleReviewAttachmentPublisher.find([same], attachment) == same
    assert AppleReviewAttachmentPublisher.find([record(attachment, fileName=attachment.name)], attachment)
    assert (
        AppleReviewAttachmentPublisher.find([record(attachment, fileName="another.txt")], attachment) is None
    )
    with pytest.raises(UnsafeOperationError, match="Multiple"):
        AppleReviewAttachmentPublisher.find([same, same], attachment)
    api = Mock()
    api.paginated.return_value = [
        record(attachment, fileName=attachment.name, sourceFileChecksum="different")
    ]
    publisher = AppleReviewAttachmentPublisher(api)
    with pytest.raises(UnsafeOperationError, match="confirm_replacement"):
        publisher.synchronize(
            "review", [AppleReviewAttachment(path=attachment.name)], attachment.parent, apply=True
        )
    api.request.assert_not_called()


def test_validation_happens_before_api_access(attachment, project):
    item = AppleReviewAttachment(path=attachment.name)
    with pytest.raises(ConfigurationError, match="directory"):
        AppleReviewAttachmentPublisher.validate(item, None)
    missing = AppleReviewAttachment(path="missing.txt")
    api = Mock()
    publisher = AppleReviewAttachmentPublisher(api)
    with pytest.raises(ConfigurationError, match="nonempty"):
        publisher.synchronize("review", [missing], attachment.parent, apply=True)
    api.paginated.assert_not_called()
    with pytest.raises(ValidationError, match="unique"):
        AppleReview(attachments=[item, AppleReviewAttachment(path="other/guide.txt")])
    project.apple.review = AppleReview(attachments=[item])
    config = attachment.parent / "config.yaml"
    engine = PublicationEngine(project, config)
    assert attachment.name in asset_manifest(engine)
    assert attachment.name in WorkflowRunner(engine).artifacts()
    assert not validate_project(project, config, local_files="store")
    attachment.write_bytes(b"")
    assert len(validate_project(project, config, local_files="store")) == 1
    assert not validate_project(project, config, local_files="none")


def test_review_detail_creation_without_invented_contact_fields(attachment, monkeypatch):
    api = Mock()
    api.request.return_value = {"data": None}
    review = AppleReview(attachments=[AppleReviewAttachment(path=attachment.name)])
    manager = AppleReviewManager(api, "123")
    pending = manager.synchronize_details("version", review, directory=attachment.parent, apply=False)
    assert pending == [
        "Apple review: create details",
        f"Apple review: synchronize attachment {attachment.name}",
    ]
    assert [call.args[0] for call in api.request.call_args_list] == ["GET"]
    api.reset_mock()
    api.request.side_effect = [{"data": None}, {"data": {"id": "new-review", "attributes": {}}}]
    synchronize = Mock(return_value=["attachment uploaded"])
    monkeypatch.setattr(AppleReviewAttachmentPublisher, "synchronize", synchronize)
    assert manager.synchronize_details("version", review, directory=attachment.parent, apply=True) == [
        "Apple review: create details",
        "attachment uploaded",
    ]
    assert api.request.call_args.kwargs["payload"]["data"]["attributes"] == {}
    assert synchronize.call_args.args[0] == "new-review"
    assert synchronize.call_args.args[2] == attachment.parent


def test_existing_review_details_are_preserved_when_only_attaching(attachment, monkeypatch):
    api = Mock()
    api.request.return_value = {
        "data": {"id": "review", "attributes": {"contactEmail": "person@example.invalid"}}
    }
    monkeypatch.setattr(AppleReviewAttachmentPublisher, "synchronize", Mock(return_value=[]))
    manager = AppleReviewManager(api, "123")
    review = AppleReview(attachments=[AppleReviewAttachment(path=attachment.name)])
    assert manager.synchronize_details("version", review, directory=attachment.parent, apply=True) == []
    assert [call.args[0] for call in api.request.call_args_list] == ["GET"]
