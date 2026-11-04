from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription_promotion import AppleSubscriptionPromotion
from app_publisher.models.apple_subscription_win_back import AppleSubscriptionWinBack


class AppleSubscriptionPromotions:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self,
        subscription_id: str,
        promotions: list[AppleSubscriptionPromotion],
        winbacks: list[AppleSubscriptionWinBack],
        *,
        apply: bool,
    ) -> list[str]:
        changes: list[str] = []
        if promotions:
            remote = self.api.paginated(
                f"subscriptions/{subscription_id}/promotionalOffers", params={"limit": 200}
            )
            indexed = {item["attributes"]["name"]: item for item in remote}
            for offer in promotions:
                attrs = {
                    "name": offer.name,
                    "duration": offer.duration,
                    "numberOfPeriods": offer.number_of_periods,
                    "offerMode": offer.offer_mode,
                }
                if offer.target_subscription_plan_type:
                    attrs["targetSubscriptionPlanType"] = offer.target_subscription_plan_type
                changes.extend(
                    self._create_if_missing(
                        "subscriptionPromotionalOffers",
                        "name",
                        indexed,
                        attrs,
                        subscription_id,
                        offer.price_point_ids,
                        apply=apply,
                    )
                )
        if winbacks:
            remote = self.api.paginated(
                f"subscriptions/{subscription_id}/winBackOffers", params={"limit": 200}
            )
            indexed = {item["attributes"]["offerId"]: item for item in remote}
            for offer in winbacks:
                attrs = {
                    "referenceName": offer.reference_name,
                    "offerId": offer.offer_id,
                    "duration": offer.duration,
                    "offerMode": offer.offer_mode,
                    "periodCount": offer.period_count,
                    "startDate": offer.start_date,
                    "endDate": offer.end_date,
                    "priority": offer.priority,
                    "promotionIntent": offer.promotion_intent,
                }
                changes.extend(
                    self._create_if_missing(
                        "winBackOffers",
                        "offerId",
                        indexed,
                        attrs,
                        subscription_id,
                        offer.price_point_ids,
                        apply=apply,
                    )
                )
        return changes

    def _create_if_missing(
        self,
        resource: str,
        identity: str,
        existing: dict,
        attrs: dict,
        subscription_id: str,
        price_points: list[str],
        *,
        apply: bool,
    ) -> list[str]:
        key = attrs[identity]
        current = existing.get(key)
        if current:
            mismatched = [name for name, value in attrs.items() if current["attributes"].get(name) != value]
            if mismatched:
                raise UnsafeOperationError(
                    f"Apple offer {key} differs in fields that require an explicit offer migration: {', '.join(mismatched)}"
                )
            return []
        if len(set(price_points)) != len(price_points):
            raise UnsafeOperationError(f"Apple offer {key} repeats a price point")
        if apply:
            price_type = (
                "winBackOfferPrices" if resource == "winBackOffers" else "subscriptionPromotionalOfferPrices"
            )
            references = [
                {"type": price_type, "id": f"${{{resource}-price-{index}}}"}
                for index in range(len(price_points))
            ]
            included = [
                {
                    "type": price_type,
                    "id": entry["id"],
                    "relationships": {
                        "subscriptionPricePoint": {"data": {"type": "subscriptionPricePoints", "id": point}}
                    },
                }
                for entry, point in zip(references, price_points, strict=True)
            ]
            payload = {
                "data": {
                    "type": resource,
                    "attributes": attrs,
                    "relationships": {
                        "subscription": {"data": {"type": "subscriptions", "id": subscription_id}},
                        "prices": {"data": references},
                    },
                },
                "included": included,
            }
            self.api.request("POST", resource, payload=payload)
        return [f"Apple subscription: create {resource} {key}"]
