from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_config import AppleConfig


class AppleProductReview:
    def __init__(self, api: APIClient, config: AppleConfig):
        self.api = api
        self.config = config

    def candidates(self) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if self.config.in_app_purchases:
            products = self.api.paginated(
                f"apps/{self.config.app_id}/inAppPurchasesV2", params={"limit": 200}
            )
            indexed = {item["attributes"]["productId"]: item for item in products}
            for product in self.config.in_app_purchases:
                if not product.localizations:
                    continue
                if product.product_id not in indexed:
                    raise UnsafeOperationError(f"Apple purchase is not registered: {product.product_id}")
                candidates.extend(
                    self._draft(
                        f"inAppPurchases/{indexed[product.product_id]['id']}/versions",
                        "inAppPurchaseVersion",
                        product.product_id,
                        version="v2",
                    )
                )
        if self.config.subscription_groups:
            groups = self.api.paginated(
                f"apps/{self.config.app_id}/subscriptionGroups", params={"limit": 200}
            )
            indexed_groups = {item["attributes"]["referenceName"]: item for item in groups}
            for group in self.config.subscription_groups:
                if group.reference_name not in indexed_groups:
                    raise UnsafeOperationError(
                        f"Apple subscription group is not registered: {group.reference_name}"
                    )
                group_id = indexed_groups[group.reference_name]["id"]
                if group.localizations:
                    candidates.extend(
                        self._draft(
                            f"subscriptionGroups/{group_id}/versions",
                            "subscriptionGroupVersion",
                            group.reference_name,
                        )
                    )
                if not group.subscriptions:
                    continue
                subscriptions = self.api.paginated(
                    f"subscriptionGroups/{group_id}/subscriptions", params={"limit": 200}
                )
                indexed = {item["attributes"]["productId"]: item for item in subscriptions}
                for subscription in group.subscriptions:
                    if not subscription.localizations:
                        continue
                    if subscription.product_id not in indexed:
                        raise UnsafeOperationError(
                            f"Apple subscription is not registered: {subscription.product_id}"
                        )
                    candidates.extend(
                        self._draft(
                            f"subscriptions/{indexed[subscription.product_id]['id']}/versions",
                            "subscriptionVersion",
                            subscription.product_id,
                        )
                    )
        return candidates

    def _draft(
        self, endpoint: str, relation: str, name: str, *, version: str = "v1"
    ) -> list[tuple[str, str]]:
        versions = self.api.paginated(endpoint, params={"limit": 200}, version=version)
        drafts = [item for item in versions if item["attributes"].get("state") == "PREPARE_FOR_SUBMISSION"]
        if len(drafts) != 1:
            raise UnsafeOperationError(f"Apple product {name} must have exactly one editable draft version")
        return [(relation, drafts[0]["id"])]

    def submit(self, platform: str, *, apply: bool, first_purchase_review_completed: bool) -> list[str]:
        if not first_purchase_review_completed:
            raise UnsafeOperationError(
                "Apple requires the first in-app purchase to be submitted with an app binary through App Store Connect"
            )
        candidates = self.candidates()
        if not candidates:
            return []
        reviews = self.api.paginated(f"apps/{self.config.app_id}/reviewSubmissions", params={"limit": 200})
        if any(
            item["attributes"].get("platform") == platform
            and item["attributes"].get("state") not in {"COMPLETE", "CANCELED"}
            for item in reviews
        ):
            raise UnsafeOperationError(f"An Apple {platform} review submission is already active")
        changes = [
            f"Apple {platform}: submit {kind} {identifier} for review" for kind, identifier in candidates
        ]
        if not apply:
            return changes
        payload = {
            "data": {
                "type": "reviewSubmissions",
                "attributes": {"platform": platform},
                "relationships": {"app": {"data": {"type": "apps", "id": self.config.app_id}}},
            }
        }
        review_id = self.api.request("POST", "reviewSubmissions", payload=payload)["data"]["id"]
        types = {
            "inAppPurchaseVersion": "inAppPurchaseVersions",
            "subscriptionVersion": "subscriptionVersions",
            "subscriptionGroupVersion": "subscriptionGroupVersions",
        }
        for relation, identifier in candidates:
            payload = {
                "data": {
                    "type": "reviewSubmissionItems",
                    "relationships": {
                        "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": review_id}},
                        relation: {"data": {"type": types[relation], "id": identifier}},
                    },
                }
            }
            self.api.request("POST", "reviewSubmissionItems", payload=payload)
        payload = {"data": {"type": "reviewSubmissions", "id": review_id, "attributes": {"submitted": True}}}
        self.api.request("PATCH", f"reviewSubmissions/{review_id}", payload=payload)
        return changes
