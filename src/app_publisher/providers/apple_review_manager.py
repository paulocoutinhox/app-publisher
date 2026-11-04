import os
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_review import AppleReview
from app_publisher.providers.apple_review_attachment_publisher import AppleReviewAttachmentPublisher


class AppleReviewManager:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    @staticmethod
    def attributes(review: AppleReview) -> dict[str, Any]:
        values: dict[str, Any] = {}
        mapping = {
            "contact_first_name": "contactFirstName",
            "contact_last_name": "contactLastName",
            "contact_email": "contactEmail",
            "contact_phone": "contactPhone",
            "demo_account_required": "demoAccountRequired",
            "notes": "notes",
        }

        for key, remote_key in mapping.items():
            value = getattr(review, key)
            if value is not None:
                values[remote_key] = value

        for local, remote in [
            ("demo_account_name_env", "demoAccountName"),
            ("demo_account_password_env", "demoAccountPassword"),
        ]:
            name = getattr(review, local)
            if name is not None:
                if name not in os.environ:
                    raise ConfigurationError(f"Review credential environment variable is not set: {name}")

                values[remote] = os.environ[name]

        return values

    def synchronize_details(
        self, version_id: str, review: AppleReview, *, apply: bool, directory: Path | None = None
    ) -> list[str]:
        for attachment in review.attachments:
            AppleReviewAttachmentPublisher.validate(attachment, directory)

        values = self.attributes(review)

        if not values and not review.attachments:
            return []

        try:
            existing = self.api.request("GET", f"appStoreVersions/{version_id}/appStoreReviewDetail").get(
                "data"
            )
        except RemoteAPIError as error:
            if error.status_code != 404:
                raise

            existing = None

        modified = {
            key: value
            for key, value in values.items()
            if existing is None or existing["attributes"].get(key) != value
        }
        changes = []

        if modified:
            changes.append(f"Apple review details: update {', '.join(modified)}")
        if existing is None and not modified:
            changes.append("Apple review: create details")

        if apply and (modified or existing is None):
            if existing is not None:
                self.api.request(
                    "PATCH",
                    f"appStoreReviewDetails/{existing['id']}",
                    payload={
                        "data": {
                            "id": existing["id"],
                            "type": "appStoreReviewDetails",
                            "attributes": modified,
                        }
                    },
                )
            else:
                existing = self.api.request(
                    "POST",
                    "appStoreReviewDetails",
                    payload={
                        "data": {
                            "type": "appStoreReviewDetails",
                            "attributes": values,
                            "relationships": {
                                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
                            },
                        }
                    },
                )["data"]

        if existing is None:
            changes.extend(f"Apple review: synchronize attachment {item.path}" for item in review.attachments)
            return changes

        changes.extend(
            AppleReviewAttachmentPublisher(self.api).synchronize(
                existing["id"], review.attachments, directory, apply=apply
            )
        )
        return changes

    def submit(self, versions: list[tuple[str, str]], *, apply: bool) -> list[str]:
        existing = self.api.paginated(f"apps/{self.app_id}/reviewSubmissions", params={"limit": 200})
        grouped: dict[str, list[str]] = {}
        for version_id, platform in versions:
            grouped.setdefault(platform, []).append(version_id)
        pending = {
            item["attributes"]["platform"]
            for item in existing
            if item["attributes"].get("state") not in {"COMPLETE", "CANCELED"}
        }
        conflicted = set(grouped) & pending
        if conflicted:
            raise UnsafeOperationError(
                f"Apple review submissions are already active for: {', '.join(sorted(conflicted))}"
            )
        if not apply:
            return [
                f"Apple {platform}: submit version {version_id} for review"
                for platform, identifiers in grouped.items()
                for version_id in identifiers
            ]
        changes: list[str] = []
        for platform, identifiers in grouped.items():
            payload = {
                "data": {
                    "type": "reviewSubmissions",
                    "attributes": {"platform": platform},
                    "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}},
                }
            }
            submission_id = self.api.request("POST", "reviewSubmissions", payload=payload)["data"]["id"]
            for version_id in identifiers:
                item = {
                    "data": {
                        "type": "reviewSubmissionItems",
                        "relationships": {
                            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission_id}},
                            "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}},
                        },
                    }
                }
                self.api.request("POST", "reviewSubmissionItems", payload=item)
            self.api.request(
                "PATCH",
                f"reviewSubmissions/{submission_id}",
                payload={
                    "data": {
                        "type": "reviewSubmissions",
                        "id": submission_id,
                        "attributes": {"submitted": True},
                    }
                },
            )
            changes.append(
                f"Apple {platform}: review submission {submission_id} created for {len(identifiers)} versions"
            )
        return changes
