import re
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_review_attachment import AppleReviewAttachment
from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper


class AppleReviewAttachmentPublisher:
    def __init__(self, api: APIClient):
        self.api = api
        self.assets = AppleReviewAssetHelper(api)

    @staticmethod
    def validate(configuration: AppleReviewAttachment, directory: Path | None) -> Path:
        if directory is None:
            raise ConfigurationError("App Review attachments require the project directory")

        path = project_path(directory, configuration.path)

        if not path.is_file() or path.stat().st_size == 0:
            raise ConfigurationError(f"App Review attachment must be a nonempty file: {configuration.path}")

        return path

    @staticmethod
    def find(records: list[dict[str, Any]], path: Path) -> dict[str, Any] | None:
        pattern = rf"{re.escape(path.stem)}-[0-9a-f]{{32}}{re.escape(path.suffix.lower())}"
        matches = [
            item
            for item in records
            if item["attributes"]["fileName"] == path.name
            or re.fullmatch(pattern, item["attributes"]["fileName"])
        ]

        if len(matches) > 1:
            raise UnsafeOperationError("Multiple Apple review attachments match the configured filename")

        return matches[0] if matches else None

    def synchronize(
        self, review_id: str, attachments: list[AppleReviewAttachment], directory: Path | None, *, apply: bool
    ) -> list[str]:
        if not attachments:
            return []

        paths = [self.validate(item, directory) for item in attachments]
        existing = self.api.paginated(
            f"appStoreReviewDetails/{review_id}/appStoreReviewAttachments", params={"limit": 200}
        )
        changes = []

        for item, path in zip(attachments, paths, strict=True):
            filename = f"{path.stem}-{self.assets.checksum(path)}{path.suffix.lower()}"
            changed = self.assets.synchronize(
                "appStoreReviewAttachments",
                {"appStoreReviewDetail": {"data": {"type": "appStoreReviewDetails", "id": review_id}}},
                path,
                self.find(existing, path),
                filename=filename,
                confirm_replacement=item.confirm_replacement,
                timeout=item.timeout_seconds,
                apply=apply,
            )

            if changed:
                changes.append(f"Apple review: synchronize attachment {item.path}")

        return changes
