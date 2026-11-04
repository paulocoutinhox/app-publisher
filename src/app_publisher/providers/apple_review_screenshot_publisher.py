import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.core.assets import verify_image
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.models.apple_review_screenshot import AppleReviewScreenshot
from app_publisher.providers.apple_review_asset_helper import AppleReviewAssetHelper


class AppleReviewScreenshotPublisher:
    def __init__(
        self,
        api: APIClient,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api = api
        self.assets = AppleReviewAssetHelper(api, clock, sleep)

    @staticmethod
    def validate(configuration: AppleReviewScreenshot, directory: Path | None) -> Path:
        if directory is None:
            raise ConfigurationError("A review screenshot requires the project directory")

        path = project_path(directory, configuration.path)
        verify_image(path)
        return path

    @staticmethod
    def definition(kind: str, owner_id: str) -> tuple[str, str, str, str, str]:
        if kind == "subscription":
            return (
                "subscriptionAppStoreReviewScreenshots",
                f"subscriptions/{owner_id}/appStoreReviewScreenshot",
                "v1",
                "subscription",
                "subscriptions",
            )

        if kind == "iap":
            return (
                "inAppPurchaseAppStoreReviewScreenshots",
                f"inAppPurchases/{owner_id}/appStoreReviewScreenshot",
                "v2",
                "inAppPurchaseV2",
                "inAppPurchases",
            )

        raise ConfigurationError("Unknown Apple review screenshot owner type")

    def find(self, endpoint: str, version: str) -> dict[str, Any] | None:
        try:
            return self.api.request("GET", endpoint, version=version)["data"]
        except RemoteAPIError as error:
            if error.status_code == 404:
                return None

            raise

    def synchronize(
        self,
        kind: str,
        owner_id: str,
        configuration: AppleReviewScreenshot,
        directory: Path | None,
        *,
        apply: bool,
    ) -> list[str]:
        resource, endpoint, version, relation, owner_type = self.definition(kind, owner_id)
        path = self.validate(configuration, directory)
        filename = f"review-{self.assets.checksum(path)}{path.suffix.lower()}"
        current = self.find(endpoint, version)
        changed = self.assets.synchronize(
            resource,
            {relation: {"data": {"type": owner_type, "id": owner_id}}},
            path,
            current,
            filename=filename,
            confirm_replacement=configuration.confirm_replacement,
            timeout=configuration.timeout_seconds,
            apply=apply,
        )

        if not changed:
            return []

        return [f"Apple {kind} {owner_id}: synchronize review screenshot {configuration.path}"]
