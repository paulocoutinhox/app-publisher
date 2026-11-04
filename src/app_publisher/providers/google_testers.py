import sys

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.models.google_tester_group import GoogleTesterGroup


class GoogleTesters:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def synchronize(self, groups: list[GoogleTesterGroup], *, apply: bool) -> list[str]:
        if not groups:
            return []
        root = f"applications/{self.package_name}/edits"
        edit_id = str(self.api.request("POST", root, payload={})["id"])
        path = f"{root}/{edit_id}"
        committed = False
        try:
            changes = []
            for entry in groups:
                endpoint = f"{path}/testers/{entry.track}"
                remote = self.api.request("GET", endpoint)
                if set(remote.get("googleGroups", [])) == set(entry.google_groups):
                    continue
                changes.append(
                    f"Google testers {entry.track}: update {len(entry.google_groups)} Google Groups"
                )
                if apply:
                    self.api.request("PUT", endpoint, payload={"googleGroups": entry.google_groups})
            if apply and changes:
                self.api.request("POST", f"{path}:validate", payload={})
                self.api.request(
                    "POST",
                    f"{path}:commit",
                    params={
                        "changesNotSentForReview": "true",
                        "changesInReviewBehavior": "ERROR_IF_IN_REVIEW",
                    },
                    payload={},
                )
                committed = True
            return changes
        finally:
            if not committed:
                original = sys.exception()
                try:
                    self.api.request("DELETE", path)
                except RemoteAPIError as error:
                    if original is None:
                        raise
                    original.add_note(f"Google tester edit cleanup also failed: {error}")
