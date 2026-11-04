from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription_introductory_offer import AppleSubscriptionIntroductoryOffer
from app_publisher.models.apple_subscription_offer_code import AppleSubscriptionOfferCode
from app_publisher.providers.apple_offer_code_batches import AppleOfferCodeBatches


class AppleSubscriptionIntroOffers:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self,
        subscription_id: str,
        introductory: list[AppleSubscriptionIntroductoryOffer],
        offer_codes: list[AppleSubscriptionOfferCode],
        *,
        apply: bool,
    ) -> list[str]:
        changes: list[str] = []
        if introductory:
            remote = self.api.paginated(
                f"subscriptions/{subscription_id}/introductoryOffers", params={"limit": 200}
            )
            indexed = {(self._territory(item), item["attributes"].get("startDate")): item for item in remote}
            if len(indexed) != len(remote):
                raise UnsafeOperationError(
                    "Apple introductory offers have ambiguous territory and start-date combinations"
                )
            for offer in introductory:
                identity = (offer.territory, offer.start_date)
                if identity in indexed:
                    stored = indexed[identity]
                    expected = {
                        "endDate": offer.end_date,
                        "duration": offer.duration,
                        "numberOfPeriods": offer.number_of_periods,
                        "offerMode": offer.offer_mode,
                    }
                    if offer.target_subscription_plan_type:
                        expected["targetSubscriptionPlanType"] = offer.target_subscription_plan_type
                    linked_price = (
                        stored.get("relationships", {}).get("subscriptionPricePoint", {}).get("data")
                    )
                    invalid = [
                        key for key, value in expected.items() if stored["attributes"].get(key) != value
                    ]
                    if linked_price and linked_price.get("id") != offer.price_point_id:
                        invalid.append("subscriptionPricePoint")
                    if invalid:
                        raise UnsafeOperationError(
                            f"Apple introductory offer {identity} differs in immutable fields: {', '.join(invalid)}"
                        )
                    continue
                if offer.start_date > offer.end_date:
                    raise UnsafeOperationError(
                        f"Apple introductory offer dates are invalid for {offer.territory}"
                    )
                changes.append(
                    f"Apple subscription: create introductory offer {offer.territory} from {offer.start_date}"
                )
                if apply:
                    attrs = {
                        "startDate": offer.start_date,
                        "endDate": offer.end_date,
                        "duration": offer.duration,
                        "numberOfPeriods": offer.number_of_periods,
                        "offerMode": offer.offer_mode,
                    }
                    if offer.target_subscription_plan_type:
                        attrs["targetSubscriptionPlanType"] = offer.target_subscription_plan_type
                    relationships = {
                        "subscription": {"data": {"type": "subscriptions", "id": subscription_id}},
                        "territory": {"data": {"type": "territories", "id": offer.territory}},
                        "subscriptionPricePoint": {
                            "data": {"type": "subscriptionPricePoints", "id": offer.price_point_id}
                        },
                    }
                    self.api.request(
                        "POST",
                        "subscriptionIntroductoryOffers",
                        payload={
                            "data": {
                                "type": "subscriptionIntroductoryOffers",
                                "attributes": attrs,
                                "relationships": relationships,
                            }
                        },
                    )
        if offer_codes:
            remote = self.api.paginated(f"subscriptions/{subscription_id}/offerCodes", params={"limit": 200})
            existing = {item["attributes"]["name"]: item for item in remote}
            if len(existing) != len(remote):
                raise UnsafeOperationError("Apple subscription offer codes have ambiguous names")
            for offer in offer_codes:
                attrs = {
                    "name": offer.name,
                    "duration": offer.duration,
                    "numberOfPeriods": offer.number_of_periods,
                    "offerMode": offer.offer_mode,
                    "customerEligibilities": offer.customer_eligibilities,
                    "offerEligibility": offer.offer_eligibility,
                }
                if offer.target_subscription_plan_type:
                    attrs["targetSubscriptionPlanType"] = offer.target_subscription_plan_type
                code_id: str | None = None
                if offer.name in existing:
                    conflicting = [
                        key
                        for key, value in attrs.items()
                        if existing[offer.name]["attributes"].get(key) != value
                    ]
                    if conflicting:
                        raise UnsafeOperationError(
                            f"Apple subscription offer code {offer.name} differs in immutable fields: {', '.join(conflicting)}"
                        )
                    if not offer.custom_code_batches and not offer.one_time_code_batches:
                        continue
                    code_id = existing[offer.name]["id"]
                if code_id is None and len(set(offer.price_point_ids)) != len(offer.price_point_ids):
                    raise UnsafeOperationError(
                        f"Apple subscription offer code {offer.name} repeats a price point"
                    )
                if code_id is None:
                    changes.append(f"Apple subscription: create offer code {offer.name}")
                if apply and code_id is None:
                    references = [
                        {"type": "subscriptionOfferCodePrices", "id": f"${{offer-code-{index}}}"}
                        for index in range(len(offer.price_point_ids))
                    ]
                    included = [
                        {
                            "type": "subscriptionOfferCodePrices",
                            "id": entry["id"],
                            "relationships": {
                                "subscriptionPricePoint": {
                                    "data": {"type": "subscriptionPricePoints", "id": point}
                                }
                            },
                        }
                        for entry, point in zip(references, offer.price_point_ids, strict=True)
                    ]
                    payload = {
                        "data": {
                            "type": "subscriptionOfferCodes",
                            "attributes": attrs,
                            "relationships": {
                                "subscription": {"data": {"type": "subscriptions", "id": subscription_id}},
                                "prices": {"data": references},
                            },
                        },
                        "included": included,
                    }
                    result = self.api.request("POST", "subscriptionOfferCodes", payload=payload)
                    if offer.custom_code_batches or offer.one_time_code_batches:
                        code_id = result["data"]["id"]
                if code_id is not None:
                    changes.extend(
                        AppleOfferCodeBatches(self.api).synchronize(
                            code_id, offer.custom_code_batches, offer.one_time_code_batches, apply=apply
                        )
                    )
                if code_id is None:
                    changes.extend(
                        f"Apple custom offer codes: create {item.number_of_codes} redemptions for {item.custom_code}"
                        for item in offer.custom_code_batches
                    )
                    changes.extend(
                        f"Apple one-time offer codes: create {item.number_of_codes} codes expiring {item.expiration_date}"
                        for item in offer.one_time_code_batches
                    )
        return changes

    @staticmethod
    def _territory(item: dict) -> str | None:
        linked = item.get("relationships", {}).get("territory", {}).get("data")
        if linked is None:
            return None
        return linked.get("id")
