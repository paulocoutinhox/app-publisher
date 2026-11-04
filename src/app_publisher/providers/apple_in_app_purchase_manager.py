from pathlib import Path

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
from app_publisher.providers.apple_product_localizations import AppleProductLocalizations
from app_publisher.providers.apple_review_screenshot_publisher import AppleReviewScreenshotPublisher


class AppleInAppPurchaseManager:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def synchronize(
        self, purchases: list[AppleInAppPurchase], *, apply: bool, directory: Path | None = None
    ) -> list[str]:
        if not purchases:
            return []
        for item in purchases:
            if item.review_screenshot is not None:
                AppleReviewScreenshotPublisher.validate(item.review_screenshot, directory)

        existing = self.api.paginated(f"apps/{self.app_id}/inAppPurchasesV2", params={"limit": 200})
        indexed = {item["attributes"]["productId"]: item for item in existing}
        changes: list[str] = []
        localization_manager = AppleProductLocalizations(self.api)
        for purchase in purchases:
            attributes = {
                "name": purchase.name,
                "reviewNote": purchase.review_note,
                "availableInAllTerritories": purchase.available_in_all_territories,
            }
            current = indexed.get(purchase.product_id)
            if current is None:
                changes.append(f"Apple in-app purchase: create {purchase.product_id}")
                if apply:
                    attributes.update(
                        {"productId": purchase.product_id, "inAppPurchaseType": purchase.purchase_type}
                    )
                    payload = {
                        "data": {
                            "type": "inAppPurchases",
                            "attributes": attributes,
                            "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}},
                        }
                    }
                    created = self.api.request("POST", "inAppPurchases", payload=payload, version="v2")[
                        "data"
                    ]
                    changes.extend(
                        localization_manager.synchronize(
                            "iap", created["id"], purchase.localizations, apply=apply
                        )
                    )
                    if purchase.review_screenshot is not None:
                        changes.extend(
                            AppleReviewScreenshotPublisher(self.api).synchronize(
                                "iap", created["id"], purchase.review_screenshot, directory, apply=apply
                            )
                        )
                else:
                    changes.extend(
                        f"Apple iap {purchase.product_id}: create localization {locale}"
                        for locale in purchase.localizations
                    )
                    if purchase.review_screenshot is not None:
                        changes.append(f"Apple iap {purchase.product_id}: upload review screenshot")

                continue

            if current["attributes"].get("inAppPurchaseType") != purchase.purchase_type:
                raise UnsafeOperationError(
                    f"Apple purchase {purchase.product_id} has a different immutable purchase type"
                )
            updates = {
                key: value for key, value in attributes.items() if current["attributes"].get(key) != value
            }
            if updates:
                changes.append(f"Apple in-app purchase: update {purchase.product_id}: {', '.join(updates)}")
            if apply and updates:
                payload = {"data": {"type": "inAppPurchases", "id": current["id"], "attributes": updates}}
                self.api.request("PATCH", f"inAppPurchases/{current['id']}", payload=payload, version="v2")
            changes.extend(
                localization_manager.synchronize("iap", current["id"], purchase.localizations, apply=apply)
            )
            if purchase.review_screenshot is not None:
                changes.extend(
                    AppleReviewScreenshotPublisher(self.api).synchronize(
                        "iap", current["id"], purchase.review_screenshot, directory, apply=apply
                    )
                )
        return changes
