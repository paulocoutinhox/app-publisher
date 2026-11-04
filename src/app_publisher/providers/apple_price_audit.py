from datetime import date
from decimal import Decimal, InvalidOperation

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError


class ApplePriceAudit:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def inspect(self, *, today: date | None = None) -> dict[str, object]:
        current_day = today or date.today()
        schedule = self.api.request("GET", f"apps/{self.app_id}/appPriceSchedule")["data"]
        schedule_id = schedule["id"]
        territory = self.api.request("GET", f"appPriceSchedules/{schedule_id}/relationships/baseTerritory")[
            "data"
        ]["id"]
        prices = self.api.paginated(f"appPriceSchedules/{schedule_id}/manualPrices", params={"limit": 200})
        eligible = []
        for entry in prices:
            attrs = entry["attributes"]
            starts = attrs.get("startDate")
            ends = attrs.get("endDate")
            entry_territory = entry.get("relationships", {}).get("territory", {}).get("data")
            if entry_territory and entry_territory["id"] != territory:
                continue
            if starts and date.fromisoformat(starts) > current_day:
                continue
            if ends and date.fromisoformat(ends) < current_day:
                continue
            eligible.append(entry)
        if len(eligible) != 1:
            raise UnsafeOperationError(
                "Apple price verification requires exactly one effective manual base-territory price"
            )
        point_id = eligible[0]["relationships"]["appPricePoint"]["data"]["id"]
        price_point = self.api.request("GET", f"appPricePoints/{point_id}")["data"]
        try:
            amount = Decimal(str(price_point["attributes"]["customerPrice"]))
        except (KeyError, ValueError, InvalidOperation) as error:
            raise UnsafeOperationError("Apple price point does not contain a valid customer price") from error
        if not amount.is_finite() or amount < 0:
            raise UnsafeOperationError("Apple price point must contain a finite nonnegative price")
        return {
            "base_territory": territory,
            "price_point_id": point_id,
            "customer_price": str(amount),
            "paid": amount > 0,
        }

    def verify(self, paid: bool, *, today: date | None = None) -> dict[str, object]:
        result = self.inspect(today=today)
        if result["paid"] != paid:
            raise UnsafeOperationError(
                f"Apple app paid state differs: configured={paid}, current={result['paid']}"
            )
        return result
