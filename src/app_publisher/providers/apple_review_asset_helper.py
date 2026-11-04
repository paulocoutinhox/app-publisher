import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper


class AppleReviewAssetHelper:
    def __init__(
        self,
        api: APIClient,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api = api
        self.clock = clock
        self.sleep = sleep

    @staticmethod
    def checksum(path: Path) -> str:
        # Apple requires an MD5 checksum for media delivery.
        digest = hashlib.md5(usedforsecurity=False)

        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)

        return digest.hexdigest()

    @staticmethod
    def state(record: dict[str, Any]) -> str:
        delivery = record["attributes"].get("assetDeliveryState")
        state = delivery.get("state") if isinstance(delivery, dict) else None

        if state not in {"AWAITING_UPLOAD", "UPLOAD_COMPLETE", "COMPLETE", "FAILED"}:
            raise RemoteAPIError("Apple returned an unknown review asset delivery state")

        return state

    def wait(self, resource: str, identity: str, checksum: str, timeout: int) -> None:
        deadline = self.clock() + timeout

        while True:
            record = self.api.request("GET", f"{resource}/{identity}")["data"]
            state = self.state(record)

            if state == "COMPLETE":
                actual = record["attributes"].get("sourceFileChecksum")

                if not isinstance(actual, str) or actual.lower() != checksum:
                    raise RemoteAPIError("Apple review asset checksum does not match the uploaded file")

                return

            if state == "FAILED":
                raise RemoteAPIError("Apple could not process the review asset")

            remaining = deadline - self.clock()

            if remaining <= 0:
                raise RemoteAPIError("Apple review asset processing exceeded its timeout")

            self.sleep(min(2, remaining))

    def synchronize(
        self,
        resource: str,
        relationships: dict[str, Any],
        path: Path,
        current: dict[str, Any] | None,
        *,
        filename: str,
        confirm_replacement: bool,
        timeout: int,
        apply: bool,
    ) -> bool:
        checksum = self.checksum(path)
        replacement = False
        state = None

        if current is not None:
            state = self.state(current)
            actual = current["attributes"].get("sourceFileChecksum")
            same = isinstance(actual, str) and actual.lower() == checksum
            pending_same = (
                state in {"AWAITING_UPLOAD", "UPLOAD_COMPLETE"}
                and current["attributes"].get("fileName") == filename
            )

            if same and state == "COMPLETE":
                return False

            replacement = not (same or pending_same) or state == "FAILED"

        if not apply:
            return True

        if replacement:
            if not confirm_replacement:
                raise UnsafeOperationError(
                    "Replacing an existing review asset requires confirm_replacement: true"
                )

            self.api.request("DELETE", f"{resource}/{current['id']}")
            current = None

        created = current is None

        if created:
            current = self.api.request(
                "POST",
                resource,
                payload={
                    "data": {
                        "type": resource,
                        "attributes": {"fileName": filename, "fileSize": path.stat().st_size},
                        "relationships": relationships,
                    }
                },
            )["data"]

        if created or state == "AWAITING_UPLOAD":
            operations = current["attributes"].get("uploadOperations")

            if not isinstance(operations, list) or not operations:
                raise RemoteAPIError("Apple did not provide upload operations for the review asset")

            AppleAssetUploadHelper.upload_parts(self.api, operations, path)
            self.api.request(
                "PATCH",
                f"{resource}/{current['id']}",
                payload={
                    "data": {
                        "type": resource,
                        "id": current["id"],
                        "attributes": {"uploaded": True, "sourceFileChecksum": checksum},
                    }
                },
            )

        self.wait(resource, current["id"], checksum, timeout)
        return True
