from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion


class AppleLaunch:
    def __init__(self, api: APIClient):
        self.api = api

    def launch(self, version: AppleVersion, remote: dict, *, apply: bool) -> list[str]:
        if (
            remote["attributes"]["platform"] != version.platform
            or remote["attributes"]["versionString"] != version.version
        ):
            raise UnsafeOperationError("Apple release identity mismatch")
        identifier = remote["id"]
        state = remote["attributes"]["appVersionState"]
        changes: list[str] = []
        if version.phased_release:
            phased = self.read_phased_release(identifier)
            if phased is None:
                if state not in {
                    "PREPARE_FOR_SUBMISSION",
                    "READY_FOR_REVIEW",
                    "WAITING_FOR_REVIEW",
                    "IN_REVIEW",
                    "PENDING_DEVELOPER_RELEASE",
                }:
                    raise UnsafeOperationError(f"Apple phased release cannot be configured in state {state}")
                changes.append(f"Apple {version.platform} {version.version}: enable phased release")
                if apply:
                    body = {
                        "data": {
                            "type": "appStoreVersionPhasedReleases",
                            "relationships": {
                                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": identifier}}
                            },
                        }
                    }
                    self.api.request("POST", "appStoreVersionPhasedReleases", payload=body)
        if version.manual_release:
            if version.release_type != "MANUAL":
                raise UnsafeOperationError("Apple manual release requires release_type MANUAL")
            if state != "PENDING_DEVELOPER_RELEASE":
                raise UnsafeOperationError(
                    f"Apple manual release requires PENDING_DEVELOPER_RELEASE, got {state}"
                )
            changes.append(f"Apple {version.platform} {version.version}: release approved version")
            if apply:
                body = {
                    "data": {
                        "type": "appStoreVersionReleaseRequests",
                        "relationships": {
                            "appStoreVersion": {"data": {"type": "appStoreVersions", "id": identifier}}
                        },
                    }
                }
                self.api.request("POST", "appStoreVersionReleaseRequests", payload=body)
        return changes

    def read_phased_release(self, version_id: str) -> dict | None:
        try:
            return self.api.request("GET", f"appStoreVersions/{version_id}/appStoreVersionPhasedRelease").get(
                "data"
            )
        except RemoteAPIError as error:
            if "HTTP 404" not in str(error):
                raise
            return None
