from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_monetization_product import GoogleMonetizationProduct


class GoogleMonetization:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def synchronize(
        self,
        subscriptions: list[GoogleMonetizationProduct],
        products: list[GoogleMonetizationProduct],
        *,
        apply: bool,
    ) -> list[str]:
        changes: list[str] = []
        for kind, entries in [("subscriptions", subscriptions), ("onetimeproducts", products)]:
            for entry in entries:
                path = f"applications/{self.package_name}/{kind}/{entry.product_id}"
                payload: dict[str, Any] = {
                    **entry.data,
                    "packageName": self.package_name,
                    "productId": entry.product_id,
                }
                if entry.data.get("productId") not in {None, entry.product_id} or entry.data.get(
                    "packageName"
                ) not in {None, self.package_name}:
                    raise UnsafeOperationError(f"Google {kind} identity conflicts with {entry.product_id}")
                current = self.read(path)
                mask = entry.update_mask
                if any("." in key for key in mask):
                    raise UnsafeOperationError(
                        "Nested update masks are not supported by AppPublisher monetization. Use explicit top-level fields"
                    )
                changed = any(current is None or current.get(key) != payload.get(key) for key in mask)
                if not changed:
                    continue
                changes.append(f"Google {kind}: synchronize {entry.product_id}")
                if apply:
                    params = {
                        "updateMask": ",".join(entry.update_mask),
                        "regionsVersion.version": entry.regions_version,
                        "allowMissing": "true",
                    }
                    self.api.request("PATCH", path, params=params, payload=payload)
        return changes

    def read(self, path: str) -> dict[str, Any] | None:
        try:
            return self.api.request("GET", path)
        except RemoteAPIError as error:
            if "HTTP 404" not in str(error):
                raise
            return None
