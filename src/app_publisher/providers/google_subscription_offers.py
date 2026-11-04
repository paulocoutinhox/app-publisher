from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_base_plan_state import GoogleBasePlanState
from app_publisher.models.google_subscription_offer import GoogleSubscriptionOffer
from app_publisher.models.google_subscription_offer_deletion import GoogleSubscriptionOfferDeletion


class GoogleSubscriptionOffers:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def synchronize(
        self, offers: list[GoogleSubscriptionOffer], states: list[GoogleBasePlanState], *, apply: bool
    ) -> list[str]:
        changes: list[str] = []
        for item in offers:
            base = f"applications/{self.package_name}/subscriptions/{item.product_id}/basePlans/{item.base_plan_id}/offers"
            endpoint = f"{base}/{item.offer_id}"
            desired: dict[str, Any] = {
                **item.data,
                "packageName": self.package_name,
                "productId": item.product_id,
                "basePlanId": item.base_plan_id,
                "offerId": item.offer_id,
            }
            for key in ("packageName", "productId", "basePlanId", "offerId"):
                if key in item.data and item.data[key] != desired[key]:
                    raise UnsafeOperationError(f"Google offer identity mismatch for {item.offer_id}: {key}")
            try:
                current = self.api.request("GET", endpoint)
            except RemoteAPIError as error:
                if "HTTP 404" not in str(error):
                    raise
                current = None
            keys = item.update_mask
            if not keys or any(
                not key.strip()
                or key != key.strip()
                or key.startswith(".")
                or key.endswith(".")
                or ".." in key
                for key in keys
            ):
                raise UnsafeOperationError("Google offer update mask contains an empty or invalid path")
            if current is None:
                changes.append(f"Google offer: create {item.offer_id}")
                if apply:
                    params = {"offerId": item.offer_id, "regionsVersion.version": item.regions_version}
                    current = self.api.request("POST", base, params=params, payload=desired)
            else:
                changed = any(self._get(current, key) != self._get(desired, key) for key in keys)
                if changed:
                    changes.append(f"Google offer: update {item.offer_id}")
                    if apply:
                        current = self.api.request(
                            "PATCH",
                            endpoint,
                            params={
                                "updateMask": ",".join(item.update_mask),
                                "regionsVersion.version": item.regions_version,
                            },
                            payload=desired,
                        )
            if item.state != "DRAFT" and current and current.get("state") != item.state:
                changes.append(f"Google offer: {item.state.lower()} {item.offer_id}")
                if apply:
                    action = "activate" if item.state == "ACTIVE" else "deactivate"
                    self.api.request("POST", f"{endpoint}:{action}", payload={})
        for state in states:
            endpoint = f"applications/{self.package_name}/subscriptions/{state.product_id}/basePlans/{state.base_plan_id}"
            subscription = self.api.request(
                "GET", f"applications/{self.package_name}/subscriptions/{state.product_id}"
            )
            base_plans = subscription.get("basePlans")
            if not isinstance(base_plans, list):
                raise UnsafeOperationError("Google subscription did not return its base plans")
            matches = [item for item in base_plans if item.get("basePlanId") == state.base_plan_id]
            if len(matches) != 1:
                raise UnsafeOperationError(f"Unknown Google base plan: {state.base_plan_id}")
            if matches[0]["state"] == state.state:
                continue
            changes.append(f"Google base plan: {state.state.lower()} {state.base_plan_id}")
            if apply:
                action = "activate" if state.state == "ACTIVE" else "deactivate"
                self.api.request("POST", f"{endpoint}:{action}", payload={})
        return changes

    def delete(self, deletions: list[GoogleSubscriptionOfferDeletion], *, apply: bool) -> list[str]:
        changes: list[str] = []
        for item in deletions:
            if not item.confirm_deletion:
                raise UnsafeOperationError(
                    f"Subscription offer deletion requires confirm_deletion: true for {item.product_id}/{item.base_plan_id}/{item.offer_id}"
                )
            endpoint = f"applications/{self.package_name}/subscriptions/{item.product_id}/basePlans/{item.base_plan_id}/offers/{item.offer_id}"
            try:
                remote = self.api.request("GET", endpoint)
            except RemoteAPIError as error:
                if "HTTP 404" not in str(error):
                    raise
                continue
            if (
                remote.get("packageName") != self.package_name
                or remote.get("productId") != item.product_id
                or remote.get("basePlanId") != item.base_plan_id
                or remote.get("offerId") != item.offer_id
            ):
                raise UnsafeOperationError("Google subscription offer deletion identity mismatch")
            if remote.get("state") != "DRAFT":
                raise UnsafeOperationError("Only draft Google subscription offers can be deleted")
            changes.append(
                f"Google subscription offer: delete {item.product_id}/{item.base_plan_id}/{item.offer_id}"
            )
            if apply:
                self.api.request("DELETE", endpoint)
        return changes

    @staticmethod
    def _get(value: dict[str, Any], path: str) -> Any:
        current: Any = value
        for key in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
