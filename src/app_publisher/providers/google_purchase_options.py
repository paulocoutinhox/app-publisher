from collections import defaultdict

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_purchase_option_deletion import GooglePurchaseOptionDeletion
from app_publisher.models.google_purchase_option_state import GooglePurchaseOptionState


class GooglePurchaseOptions:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def synchronize(self, states: list[GooglePurchaseOptionState], *, apply: bool) -> list[str]:
        groups: dict[str, list[GooglePurchaseOptionState]] = defaultdict(list)
        for state in states:
            groups[state.product_id].append(state)
        changes: list[str] = []
        for product_id, entries in groups.items():
            path = f"applications/{self.package_name}/oneTimeProducts/{product_id}"
            product = self.api.request("GET", path)
            if product.get("productId") != product_id or product.get("packageName") != self.package_name:
                raise UnsafeOperationError(
                    "Google one-time product identity differs from the configured application"
                )
            indexed = {option["purchaseOptionId"]: option for option in product.get("purchaseOptions", [])}
            requests: list[dict[str, dict[str, str]]] = []
            for entry in entries:
                if entry.purchase_option_id not in indexed:
                    raise UnsafeOperationError(
                        f"Unknown purchase option: {entry.product_id}/{entry.purchase_option_id}"
                    )
                if indexed[entry.purchase_option_id]["state"] == entry.state:
                    continue
                changes.append(
                    f"Google purchase option: {entry.state.lower()} {product_id}/{entry.purchase_option_id}"
                )
                operation = (
                    "activatePurchaseOptionRequest"
                    if entry.state == "ACTIVE"
                    else "deactivatePurchaseOptionRequest"
                )
                requests.append(
                    {
                        operation: {
                            "packageName": self.package_name,
                            "productId": product_id,
                            "purchaseOptionId": entry.purchase_option_id,
                        }
                    }
                )
            if apply and requests:
                for start in range(0, len(requests), 100):
                    self.api.request(
                        "POST",
                        f"{path}/purchaseOptions:batchUpdateStates",
                        payload={"requests": requests[start : start + 100]},
                    )
        return changes

    def delete(self, deletions: list[GooglePurchaseOptionDeletion], *, apply: bool) -> list[str]:
        changes: list[str] = []
        for entry in deletions:
            if not entry.confirm_deletion:
                raise UnsafeOperationError(
                    f"Purchase option deletion requires confirm_deletion: true for {entry.product_id}/{entry.purchase_option_id}"
                )
            path = f"applications/{self.package_name}/oneTimeProducts/{entry.product_id}"
            remote = self.api.request("GET", path)
            if remote.get("packageName") != self.package_name or remote.get("productId") != entry.product_id:
                raise UnsafeOperationError("Google purchase option deletion identity mismatch")
            candidates = [
                item
                for item in remote.get("purchaseOptions", [])
                if item.get("purchaseOptionId") == entry.purchase_option_id
            ]
            if len(candidates) > 1:
                raise UnsafeOperationError("Remote purchase options contain duplicate identifiers")
            if not candidates:
                continue
            changes.append(f"Google purchase option: delete {entry.product_id}/{entry.purchase_option_id}")
            if apply:
                request = {
                    "packageName": self.package_name,
                    "productId": entry.product_id,
                    "purchaseOptionId": entry.purchase_option_id,
                    "force": entry.force,
                }
                self.api.request(
                    "POST", f"{path}/purchaseOptions:batchDelete", payload={"requests": [request]}
                )
        return changes
