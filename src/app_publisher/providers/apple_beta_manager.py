from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion
from app_publisher.providers.apple_build_manager import AppleBuildManager


class AppleBetaManager:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def distribute(self, version: AppleVersion, *, apply: bool) -> list[str]:
        if version.beta is None:
            return []
        if version.build_number is None:
            raise UnsafeOperationError("TestFlight distribution requires an explicit build number")
        manager = AppleBuildManager(self.api, self.app_id)
        selected = manager.require_valid(manager.find(version))
        build_id = selected["id"]
        changes: list[str] = []
        for group in version.beta.group_ids:
            existing = self.api.paginated(f"betaGroups/{group}/builds", params={"limit": 200})
            if any(item["id"] == build_id for item in existing):
                continue
            changes.append(f"Apple TestFlight: add build {build_id} to group {group}")
            if apply:
                self.api.request(
                    "POST",
                    f"betaGroups/{group}/relationships/builds",
                    payload={"data": [{"type": "builds", "id": build_id}]},
                )
        return changes
