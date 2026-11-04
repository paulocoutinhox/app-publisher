from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.product_localization import ProductLocalization


class AppleProductLocalizations:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self, kind: str, product_id: str, localizations: dict[str, ProductLocalization | str], *, apply: bool
    ) -> list[str]:
        if not localizations:
            return []
        definitions = {
            "iap": (
                f"inAppPurchases/{product_id}/versions",
                "inAppPurchaseVersions",
                "inAppPurchase",
                "inAppPurchaseLocalizations",
            ),
            "subscription": (
                f"subscriptions/{product_id}/versions",
                "subscriptionVersions",
                "subscription",
                "subscriptionLocalizations",
            ),
            "group": (
                f"subscriptionGroups/{product_id}/versions",
                "subscriptionGroupVersions",
                "subscriptionGroup",
                "subscriptionGroupLocalizations",
            ),
        }
        endpoint, version_type, relation, localization_type = definitions[kind]
        versions = self.api.paginated(
            endpoint, params={"limit": 200}, version="v2" if kind == "iap" else "v1"
        )
        drafts = [item for item in versions if item["attributes"]["state"] == "PREPARE_FOR_SUBMISSION"]
        if len(drafts) > 1:
            raise UnsafeOperationError(f"Apple {kind} has multiple editable draft versions")
        draft = drafts[0] if drafts else None
        latest = (
            draft
            if draft
            else (max(versions, key=lambda item: int(item["attributes"]["version"])) if versions else None)
        )
        existing = self._localizations(version_type, latest["id"]) if latest else {}
        changed = {
            locale: entry
            for locale, entry in localizations.items()
            if any(
                existing.get(locale, {}).get("attributes", {}).get(key) != value
                for key, value in self._attributes(locale, entry, kind).items()
            )
        }
        if not changed:
            return []
        changes = [f"Apple {kind} {product_id}: synchronize {locale}" for locale in changed]
        if not apply:
            return changes
        if draft is None:
            payload = {
                "data": {
                    "type": version_type,
                    "relationships": {
                        relation: {
                            "data": {
                                "type": "inAppPurchases"
                                if kind == "iap"
                                else "subscriptions"
                                if kind == "subscription"
                                else "subscriptionGroups",
                                "id": product_id,
                            }
                        }
                    },
                }
            }
            draft = self.api.request("POST", version_type, payload=payload)["data"]
            existing = {}
        for locale, entry in changed.items():
            attributes = self._attributes(locale, entry, kind)
            current = existing.get(locale)
            if current is not None:
                updates = {
                    key: value
                    for key, value in attributes.items()
                    if current["attributes"].get(key) != value and key != "locale"
                }
                payload = {"data": {"type": localization_type, "id": current["id"], "attributes": updates}}
                self.api.request(
                    "PATCH", f"{localization_type}/{current['id']}", payload=payload, version="v2"
                )
                continue
            payload = {
                "data": {
                    "type": localization_type,
                    "attributes": attributes,
                    "relationships": {"version": {"data": {"type": version_type, "id": draft["id"]}}},
                }
            }
            self.api.request("POST", localization_type, payload=payload, version="v2")
        return changes

    def _localizations(self, version_type: str, version_id: str) -> dict[str, dict[str, Any]]:
        resources = self.api.paginated(f"{version_type}/{version_id}/localizations", params={"limit": 200})
        return {item["attributes"]["locale"]: item for item in resources}

    @staticmethod
    def _attributes(locale: str, entry: ProductLocalization | str, kind: str) -> dict[str, str]:
        if kind == "group":
            if not isinstance(entry, str):
                raise UnsafeOperationError("Apple subscription group localizations require a display name")
            return {"locale": locale, "name": entry}
        if not isinstance(entry, ProductLocalization):
            raise UnsafeOperationError("Apple purchase localizations require a name and description")
        return {"locale": locale, "name": entry.name, "description": entry.description}
