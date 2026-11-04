from typing import Any

from app_publisher.core.api_client import APIClient


class StoreInspection:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def apple(self) -> dict[str, Any]:
        versions = self.api.paginated(f"apps/{self.app_id}/appStoreVersions", params={"limit": 200})
        submissions = self.api.paginated(f"apps/{self.app_id}/reviewSubmissions", params={"limit": 200})
        groups = self.api.paginated(f"apps/{self.app_id}/betaGroups", params={"limit": 200})
        return {
            "versions": [
                {
                    "id": item["id"],
                    "platform": item["attributes"].get("platform"),
                    "version": item["attributes"].get("versionString"),
                    "state": item["attributes"].get("appVersionState"),
                }
                for item in versions
            ],
            "review_submissions": [
                {
                    "id": item["id"],
                    "state": item["attributes"].get("state"),
                    "platform": item["attributes"].get("platform"),
                }
                for item in submissions
            ],
            "testflight_groups": [
                {
                    "id": item["id"],
                    "name": item["attributes"].get("name"),
                    "internal": item["attributes"].get("isInternalGroup"),
                }
                for item in groups
            ],
        }

    def google(self, tracks: list[dict[str, Any]]) -> dict[str, Any]:
        return {"tracks": tracks, "paid_state": "NOT_EXPOSED_BY_PUBLIC_API"}
