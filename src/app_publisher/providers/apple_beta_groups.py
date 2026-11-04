from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_beta_group import AppleBetaGroup
from app_publisher.models.apple_beta_tester import AppleBetaTester


class AppleBetaGroups:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def synchronize(self, groups: list[AppleBetaGroup], *, apply: bool) -> list[str]:
        if not groups:
            return []
        remote = self.api.paginated(f"apps/{self.app_id}/betaGroups", params={"limit": 200})
        names = [entry["attributes"]["name"] for entry in remote]
        if len(names) != len(set(names)):
            raise UnsafeOperationError("Apple TestFlight groups have ambiguous names")
        existing = {entry["attributes"]["name"]: entry for entry in remote}
        changes: list[str] = []
        for group in groups:
            current = existing.get(group.name)
            attributes = {"name": group.name, "isInternalGroup": group.internal}
            if not group.internal:
                attributes["publicLinkEnabled"] = group.public_link_enabled
                if group.public_link_limit is not None:
                    attributes["publicLinkLimit"] = group.public_link_limit
                    attributes["publicLinkLimitEnabled"] = True
            if group.feedback_enabled is not None:
                attributes["feedbackEnabled"] = group.feedback_enabled
            if current is None:
                changes.append(f"Apple TestFlight: create group {group.name}")
                if not apply:
                    changes.extend(
                        f"Apple TestFlight {group.name}: add tester {tester.email}"
                        for tester in group.testers
                    )
                    continue
                payload = {
                    "data": {
                        "type": "betaGroups",
                        "attributes": attributes,
                        "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}},
                    }
                }
                current = self.api.request("POST", "betaGroups", payload=payload)["data"]
            else:
                if current["attributes"].get("isInternalGroup") != group.internal:
                    raise UnsafeOperationError(f"TestFlight group type cannot be changed: {group.name}")
                updates = {
                    key: value
                    for key, value in attributes.items()
                    if key != "isInternalGroup" and current["attributes"].get(key) != value
                }
                if updates:
                    changes.append(f"Apple TestFlight: update group {group.name}")
                    if apply:
                        self.api.request(
                            "PATCH",
                            f"betaGroups/{current['id']}",
                            payload={
                                "data": {"id": current["id"], "type": "betaGroups", "attributes": updates}
                            },
                        )
            changes.extend(self._testers(current["id"], group.testers, apply=apply))
        return changes

    def _testers(self, group_id: str, testers: list[AppleBetaTester], *, apply: bool) -> list[str]:
        if not testers:
            return []
        current = self.api.paginated(f"betaGroups/{group_id}/betaTesters", params={"limit": 200})
        existing = {item["attributes"]["email"].casefold(): item for item in current}
        changes: list[str] = []
        for tester in testers:
            if tester.email.casefold() in existing:
                continue
            matches = self.api.paginated("betaTesters", params={"filter[email]": tester.email, "limit": 200})
            if len(matches) > 1:
                raise UnsafeOperationError(f"Multiple Apple beta testers use {tester.email}")
            changes.append(f"Apple TestFlight: add tester {tester.email} to group {group_id}")
            if not apply:
                continue
            if matches:
                tester_id = matches[0]["id"]
                self.api.request(
                    "POST",
                    f"betaGroups/{group_id}/relationships/betaTesters",
                    payload={"data": [{"type": "betaTesters", "id": tester_id}]},
                )
            else:
                attrs = {"email": tester.email}
                if tester.first_name is not None:
                    attrs["firstName"] = tester.first_name
                if tester.last_name is not None:
                    attrs["lastName"] = tester.last_name
                payload = {
                    "data": {
                        "type": "betaTesters",
                        "attributes": attrs,
                        "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": group_id}]}},
                    }
                }
                tester_id = self.api.request("POST", "betaTesters", payload=payload)["data"]["id"]
            if tester.invite:
                invitation = {
                    "data": {
                        "type": "betaTesterInvitations",
                        "relationships": {
                            "app": {"data": {"type": "apps", "id": self.app_id}},
                            "betaTester": {"data": {"type": "betaTesters", "id": tester_id}},
                        },
                    }
                }
                self.api.request("POST", "betaTesterInvitations", payload=invitation)
        return changes
