from collections import defaultdict
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_one_time_offer import GoogleOneTimeOffer
from app_publisher.models.google_one_time_offer_deletion import GoogleOneTimeOfferDeletion


class GoogleOneTimeOffers:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def synchronize(self, offers: list[GoogleOneTimeOffer], *, apply: bool) -> list[str]:
        grouped: dict[tuple[str, str], list[GoogleOneTimeOffer]] = defaultdict(list)
        for offer in offers:
            grouped[(offer.product_id, offer.purchase_option_id)].append(offer)
        changes: list[str] = []
        for (product_id, option_id), items in grouped.items():
            base = f"applications/{self.package_name}/oneTimeProducts/{product_id}/purchaseOptions/{option_id}/offers"
            remote = self._list(base)
            indexed = {item["offerId"]: item for item in remote}
            updates: list[dict[str, Any]] = []
            states: list[tuple[str, str]] = []
            for offer in items:
                self._validate_offer(offer)
                current = indexed.get(offer.offer_id)
                desired = {
                    **offer.data,
                    "packageName": self.package_name,
                    "productId": product_id,
                    "purchaseOptionId": option_id,
                    "offerId": offer.offer_id,
                }
                masks = offer.update_mask
                if current is None or any(
                    self._field(current, mask) != self._field(desired, mask) for mask in masks
                ):
                    changes.append(
                        f"Google one-time offer: synchronize {product_id}/{option_id}/{offer.offer_id}"
                    )
                    updates.append(
                        {
                            "oneTimeProductOffer": desired,
                            "updateMask": ",".join(offer.update_mask),
                            "regionsVersion": {"version": offer.regions_version},
                            "allowMissing": current is None,
                        }
                    )
                if offer.state != "DRAFT" and (current is None or current.get("state") != offer.state):
                    states.append((offer.offer_id, offer.state))
                    changes.append(f"Google one-time offer: set {offer.offer_id} to {offer.state}")
            if apply and updates:
                for start in range(0, len(updates), 100):
                    self.api.request(
                        "POST", f"{base}:batchUpdate", payload={"requests": updates[start : start + 100]}
                    )
            if apply:
                for offer_id, state in states:
                    method = {"ACTIVE": "activate", "INACTIVE": "deactivate", "CANCELLED": "cancel"}[state]
                    self.api.request("POST", f"{base}/{offer_id}:{method}", payload={})
        return changes

    def delete(self, entries: list[GoogleOneTimeOfferDeletion], *, apply: bool) -> list[str]:
        grouped: dict[tuple[str, str], list[GoogleOneTimeOfferDeletion]] = defaultdict(list)
        for entry in entries:
            if not entry.confirm_deletion:
                raise UnsafeOperationError(
                    f"Offer deletion requires confirm_deletion: true for {entry.product_id}/{entry.purchase_option_id}/{entry.offer_id}"
                )
            grouped[(entry.product_id, entry.purchase_option_id)].append(entry)
        changes: list[str] = []
        for (product_id, option_id), offers in grouped.items():
            base = f"applications/{self.package_name}/oneTimeProducts/{product_id}/purchaseOptions/{option_id}/offers"
            remote = self._list(base)
            offer_ids = [item["offerId"] for item in remote]
            if len(offer_ids) != len(set(offer_ids)):
                raise UnsafeOperationError("Remote Google one-time offers contain duplicate identifiers")
            requests: list[dict[str, str]] = []
            for entry in offers:
                if entry.offer_id not in offer_ids:
                    continue
                changes.append(f"Google one-time offer: delete {product_id}/{option_id}/{entry.offer_id}")
                requests.append(
                    {
                        "packageName": self.package_name,
                        "productId": product_id,
                        "purchaseOptionId": option_id,
                        "offerId": entry.offer_id,
                    }
                )
            if apply:
                for start in range(0, len(requests), 100):
                    self.api.request(
                        "POST", f"{base}:batchDelete", payload={"requests": requests[start : start + 100]}
                    )
        return changes

    def _list(self, base: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            params = {"pageSize": 100}
            if token is not None:
                params["pageToken"] = token
            result = self.api.request("GET", base, params=params)
            items.extend(result.get("oneTimeProductOffers", []))
            token = result.get("nextPageToken")
            if not token:
                return items
            if token in seen:
                raise UnsafeOperationError("Google one-time offer pagination repeats a page token")
            seen.add(token)

    @staticmethod
    def _validate_offer(item: GoogleOneTimeOffer) -> None:
        identity = {
            "productId": item.product_id,
            "purchaseOptionId": item.purchase_option_id,
            "offerId": item.offer_id,
        }
        for key, value in identity.items():
            if key in item.data and item.data[key] != value:
                raise UnsafeOperationError(f"Google one-time offer identity mismatch: {key}")
        paths = item.update_mask
        if not paths or any(
            not path or path.strip() != path or path.startswith(".") or path.endswith(".") or ".." in path
            for path in paths
        ):
            raise UnsafeOperationError("Google one-time offer update mask is invalid")
        if len(paths) != len(set(paths)):
            raise UnsafeOperationError("Google one-time offer update mask contains duplicates")

    @staticmethod
    def _field(item: dict[str, Any], path: str) -> Any:
        current: Any = item
        for key in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
