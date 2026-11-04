from pathlib import Path

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.models.apple_subscription_price import AppleSubscriptionPrice
from app_publisher.providers.apple_product_localizations import AppleProductLocalizations
from app_publisher.providers.apple_review_screenshot_publisher import AppleReviewScreenshotPublisher
from app_publisher.providers.apple_subscription_availability_publisher import (
    AppleSubscriptionAvailabilityPublisher,
)
from app_publisher.providers.apple_subscription_intro_offers import AppleSubscriptionIntroOffers
from app_publisher.providers.apple_subscription_promotions import AppleSubscriptionPromotions


class AppleSubscriptions:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id
        self.localizations = AppleProductLocalizations(api)

    def synchronize(
        self,
        groups: list[AppleSubscriptionGroup],
        *,
        apply: bool,
        allow_price_changes: bool = False,
        directory: Path | None = None,
    ) -> list[str]:
        for group in groups:
            for item in group.subscriptions:
                if item.review_screenshot is not None:
                    AppleReviewScreenshotPublisher.validate(item.review_screenshot, directory)

        remote_groups = self.api.paginated(f"apps/{self.app_id}/subscriptionGroups", params={"limit": 200})
        indexed_groups = {entry["attributes"]["referenceName"]: entry for entry in remote_groups}
        changes: list[str] = []
        for group in groups:
            current_group = indexed_groups.get(group.reference_name)
            if current_group is None:
                changes.append(f"Apple subscription group: create {group.reference_name}")
                if not apply:
                    for item in group.subscriptions:
                        changes.extend(self.preview_subscription(item))
                    continue
                payload = {
                    "data": {
                        "type": "subscriptionGroups",
                        "attributes": {"referenceName": group.reference_name},
                        "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}},
                    }
                }
                current_group = self.api.request("POST", "subscriptionGroups", payload=payload)["data"]
            group_id = current_group["id"]
            changes.extend(
                self.localizations.synchronize("group", group_id, group.localizations, apply=apply)
            )
            existing = self.api.paginated(
                f"subscriptionGroups/{group_id}/subscriptions", params={"limit": 200}
            )
            indexed = {entry["attributes"]["productId"]: entry for entry in existing}
            for subscription in group.subscriptions:
                changes.extend(
                    self._subscription(
                        group_id,
                        subscription,
                        indexed.get(subscription.product_id),
                        apply=apply,
                        allow_price_changes=allow_price_changes,
                        directory=directory,
                    )
                )
        return changes

    @staticmethod
    def preview_subscription(subscription: AppleSubscription) -> list[str]:
        changes = [f"Apple subscription: create {subscription.product_id}"]
        changes.extend(
            f"Apple subscription {subscription.product_id}: synchronize {locale}"
            for locale in subscription.localizations
        )
        changes.extend(
            f"Apple subscription {subscription.product_id}: schedule price {item.price_point_id}"
            for item in subscription.prices
        )
        changes.extend(
            f"Apple subscription {subscription.product_id}: create promotional offer {offer.name}"
            for offer in subscription.promotional_offers
        )
        changes.extend(
            f"Apple subscription {subscription.product_id}: create win-back offer {offer.offer_id}"
            for offer in subscription.win_back_offers
        )
        changes.extend(
            f"Apple subscription {subscription.product_id}: create introductory offer in {offer.territory}"
            for offer in subscription.introductory_offers
        )
        changes.extend(
            f"Apple subscription {subscription.product_id}: create offer code {offer.name}"
            for offer in subscription.offer_codes
        )
        if subscription.review_screenshot is not None:
            changes.append(f"Apple subscription {subscription.product_id}: upload review screenshot")

        return changes

    def _subscription(
        self,
        group_id: str,
        subscription: AppleSubscription,
        current: dict | None,
        *,
        apply: bool,
        allow_price_changes: bool,
        directory: Path | None = None,
    ) -> list[str]:
        attributes = {
            "name": subscription.name,
            "subscriptionPeriod": subscription.period,
            "familySharable": subscription.family_sharable,
            "groupLevel": subscription.group_level,
        }
        if subscription.review_note is not None:
            attributes["reviewNote"] = subscription.review_note

        changes: list[str] = []
        if current is None:
            changes.append(f"Apple subscription: create {subscription.product_id}")
            if not apply:
                return self.preview_subscription(subscription)
            payload = {
                "data": {
                    "type": "subscriptions",
                    "attributes": {**attributes, "productId": subscription.product_id},
                    "relationships": {"group": {"data": {"type": "subscriptionGroups", "id": group_id}}},
                }
            }
            current = self.api.request("POST", "subscriptions", payload=payload)["data"]
        else:
            if current["attributes"].get("subscriptionPeriod") != subscription.period:
                raise UnsafeOperationError(
                    f"Apple subscription {subscription.product_id} period differs from configured immutable period"
                )
            updates = {
                key: value for key, value in attributes.items() if current["attributes"].get(key) != value
            }
            if updates:
                changes.append(f"Apple subscription: update {subscription.product_id}")
                if apply:
                    payload = {"data": {"type": "subscriptions", "id": current["id"], "attributes": updates}}
                    self.api.request("PATCH", f"subscriptions/{current['id']}", payload=payload)
        changes.extend(
            self.localizations.synchronize(
                "subscription", current["id"], subscription.localizations, apply=apply
            )
        )
        changes.extend(
            AppleSubscriptionAvailabilityPublisher(self.api).synchronize(
                current["id"], subscription.availability, apply=apply
            )
        )
        changes.extend(
            self._prices(
                current["id"],
                subscription.product_id,
                subscription.prices,
                apply=apply,
                allow_price_changes=allow_price_changes,
            )
        )
        if subscription.review_screenshot is not None:
            changes.extend(
                AppleReviewScreenshotPublisher(self.api).synchronize(
                    "subscription", current["id"], subscription.review_screenshot, directory, apply=apply
                )
            )

        changes.extend(
            AppleSubscriptionPromotions(self.api).synchronize(
                current["id"], subscription.promotional_offers, subscription.win_back_offers, apply=apply
            )
        )
        changes.extend(
            AppleSubscriptionIntroOffers(self.api).synchronize(
                current["id"], subscription.introductory_offers, subscription.offer_codes, apply=apply
            )
        )
        return changes

    def _prices(
        self,
        subscription_id: str,
        product_id: str,
        prices: list[AppleSubscriptionPrice],
        *,
        apply: bool,
        allow_price_changes: bool,
    ) -> list[str]:
        if not prices:
            return []
        existing = self.api.paginated(
            f"subscriptions/{subscription_id}/prices",
            params={"limit": 200, "include": "subscriptionPricePoint"},
        )
        indexed = set()

        for item in existing:
            point = item.get("relationships", {}).get("subscriptionPricePoint", {}).get("data")

            if not point or not point.get("id") or not item["attributes"].get("planType"):
                raise RemoteAPIError("Apple did not return the requested price-point identity or plan type")

            indexed.add((point["id"], item["attributes"].get("startDate"), item["attributes"]["planType"]))

        changes: list[str] = []
        for price in prices:
            if (price.price_point_id, price.start_date, price.plan_type) in indexed:
                continue
            changes.append(
                f"Apple subscription {product_id}: schedule price {price.price_point_id} on {price.start_date or 'next available date'}"
            )
            if not apply:
                continue
            if not allow_price_changes:
                raise UnsafeOperationError(
                    "Price modifications require confirm_subscription_price_changes: true"
                )
            attributes = {"preserveCurrentPrice": price.preserve_current_price, "planType": price.plan_type}

            if price.start_date:
                attributes["startDate"] = price.start_date
            payload = {
                "data": {
                    "type": "subscriptionPrices",
                    "attributes": attributes,
                    "relationships": {
                        "subscription": {"data": {"type": "subscriptions", "id": subscription_id}},
                        "subscriptionPricePoint": {
                            "data": {"type": "subscriptionPricePoints", "id": price.price_point_id}
                        },
                    },
                }
            }
            self.api.request("POST", "subscriptionPrices", payload=payload)
        return changes
