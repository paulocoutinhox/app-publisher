from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_subscription_availability import AppleSubscriptionAvailability


class AppleSubscriptionAvailabilityPublisher:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self, subscription_id: str, declarations: list[AppleSubscriptionAvailability], *, apply: bool
    ) -> list[str]:
        if not declarations:
            return []

        territories = self.api.paginated("territories", params={"limit": 200})
        known = {item["id"] for item in territories}
        remote = self.api.paginated(
            f"subscriptions/{subscription_id}/planAvailabilities", params={"limit": 200}
        )
        changes = []

        for declaration in declarations:
            if not set(declaration.territories).issubset(known):
                raise ConfigurationError("Subscription availability contains an unknown Apple territory")

            matches = [item for item in remote if item["attributes"]["planType"] == declaration.plan_type]

            if len(matches) > 1:
                raise UnsafeOperationError(
                    "Multiple availability resources exist for the same subscription plan"
                )

            attributes = {"availableInNewTerritories": declaration.available_in_new_territories}
            desired = [{"type": "territories", "id": identity} for identity in declaration.territories]

            if not matches:
                changes.append(
                    f"Apple subscription {subscription_id}: create {declaration.plan_type} availability"
                )

                if apply:
                    self.api.request(
                        "POST",
                        "subscriptionPlanAvailabilities",
                        payload={
                            "data": {
                                "type": "subscriptionPlanAvailabilities",
                                "attributes": {**attributes, "planType": declaration.plan_type},
                                "relationships": {
                                    "subscription": {
                                        "data": {"type": "subscriptions", "id": subscription_id}
                                    },
                                    "availableTerritories": {"data": desired},
                                },
                            }
                        },
                    )

                continue

            current = matches[0]
            path = f"subscriptionPlanAvailabilities/{current['id']}"
            existing = self.api.paginated(f"{path}/availableTerritories", params={"limit": 200})
            territory_change = {item["id"] for item in existing} != set(declaration.territories)
            attribute_change = (
                current["attributes"].get("availableInNewTerritories")
                != declaration.available_in_new_territories
            )

            if not territory_change and not attribute_change:
                continue

            changes.append(
                f"Apple subscription {subscription_id}: update {declaration.plan_type} availability"
            )

            if not apply:
                continue

            if not declaration.confirm_territory_changes:
                raise UnsafeOperationError(
                    "Existing subscription availability changes require confirm_territory_changes: true"
                )

            if attribute_change:
                self.api.request(
                    "PATCH",
                    path,
                    payload={
                        "data": {
                            "type": "subscriptionPlanAvailabilities",
                            "id": current["id"],
                            "attributes": attributes,
                        }
                    },
                )

            if territory_change:
                self.api.request(
                    "PATCH", f"{path}/relationships/availableTerritories", payload={"data": desired}
                )

        return changes
