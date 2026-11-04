from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_pricing import ApplePricing


class AppleCommercial:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def verify_base_territory(self, expected: str) -> list[str]:
        schedule = self.api.request("GET", f"apps/{self.app_id}/appPriceSchedule")["data"]
        result = self.api.request("GET", f"appPriceSchedules/{schedule['id']}/relationships/baseTerritory")[
            "data"
        ]
        if result["id"] != expected:
            raise UnsafeOperationError(
                f"Apple price schedule base territory is {result['id']}, expected {expected}"
            )
        return [f"Apple pricing: base territory {expected} verified"]

    def synchronize_pricing(self, pricing: ApplePricing, *, apply: bool) -> list[str]:
        schedule = self.api.request("GET", f"apps/{self.app_id}/appPriceSchedule")["data"]
        schedule_id = schedule["id"]
        territory = self.api.request("GET", f"appPriceSchedules/{schedule_id}/relationships/baseTerritory")[
            "data"
        ]["id"]
        if territory != pricing.base_territory:
            raise UnsafeOperationError("Changing the Apple base territory is not supported by this operation")
        existing = self.api.paginated(
            f"appPriceSchedules/{schedule_id}/manualPrices", params={"limit": 200, "include": "appPricePoint"}
        )
        normalized = {
            (
                item["relationships"]["appPricePoint"]["data"]["id"],
                item["attributes"].get("startDate"),
                item["attributes"].get("endDate"),
            )
            for item in existing
        }
        requested = {(item.price_point_id, item.start_date, item.end_date) for item in pricing.prices}
        if requested == normalized:
            return []
        if len(requested) != len(pricing.prices):
            raise UnsafeOperationError("Duplicate Apple price schedule entries")
        if not pricing.confirm_price_changes and apply:
            raise UnsafeOperationError("Apple price schedule changes require confirm_price_changes: true")
        changes = [f"Apple pricing: replace schedule with {len(pricing.prices)} declared prices"]
        if not apply:
            return changes
        included = []
        references = []
        for index, item in enumerate(pricing.prices):
            identifier = f"${{price-{index}}}"
            references.append({"type": "appPrices", "id": identifier})
            included.append(
                {
                    "type": "appPrices",
                    "id": identifier,
                    "attributes": {"startDate": item.start_date, "endDate": item.end_date},
                    "relationships": {
                        "appPricePoint": {"data": {"type": "appPricePoints", "id": item.price_point_id}}
                    },
                }
            )
        payload = {
            "data": {
                "type": "appPriceSchedules",
                "attributes": {},
                "relationships": {
                    "app": {"data": {"type": "apps", "id": self.app_id}},
                    "baseTerritory": {"data": {"type": "territories", "id": pricing.base_territory}},
                    "manualPrices": {"data": references},
                },
            },
            "included": included,
        }
        self.api.request("POST", "appPriceSchedules", payload=payload)
        return changes

    def synchronize_territories(self, territory_availability: dict[str, bool], *, apply: bool) -> list[str]:
        if not territory_availability:
            return []
        availability = self.api.request("GET", f"apps/{self.app_id}/appAvailabilityV2")["data"]
        resources = self.api.paginated(
            f"appAvailabilities/{availability['id']}/territoryAvailabilities",
            params={"limit": 200, "include": "territory"},
            version="v2",
        )
        current = {item["relationships"]["territory"]["data"]["id"]: item for item in resources}
        missing = set(territory_availability) - set(current)
        if missing:
            raise UnsafeOperationError(f"Unrecognized Apple territory codes: {', '.join(sorted(missing))}")
        changes: list[str] = []
        for territory, desired in territory_availability.items():
            record = current[territory]
            if not record["attributes"].get("preOrderEnabled"):
                raise UnsafeOperationError(
                    "Territory availability writes are supported only for app pre-orders by the public API"
                )
            if record["attributes"].get("available") == desired:
                continue
            changes.append(f"Apple availability: set {territory} to {desired}")
            if apply:
                payload = {
                    "data": {
                        "id": record["id"],
                        "type": "territoryAvailabilities",
                        "attributes": {"available": desired},
                    }
                }
                self.api.request("PATCH", f"territoryAvailabilities/{record['id']}", payload=payload)
        return changes
