from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_country_expectation import GoogleCountryExpectation


class StoreAvailability:
    def __init__(self, api: APIClient):
        self.api = api

    def apple(self, app_id: str, expectations: dict[str, bool]) -> list[str]:
        if not expectations:
            return []
        availability = self.api.request("GET", f"apps/{app_id}/appAvailabilityV2")["data"]
        records = self.api.paginated(
            f"appAvailabilities/{availability['id']}/territoryAvailabilities",
            params={"include": "territory", "limit": 200},
            version="v2",
        )
        actual = {
            item["relationships"]["territory"]["data"]["id"]: item["attributes"]["available"]
            for item in records
        }
        for territory, required in expectations.items():
            if territory not in actual:
                raise UnsafeOperationError(
                    f"Apple territory is not present in the app availability response: {territory}"
                )
            if actual[territory] != required:
                raise UnsafeOperationError(
                    f"Apple territory {territory}: expected available={required}, remote={actual[territory]}"
                )
        return [f"Apple availability: verified {len(expectations)} declared territories"]

    def google(self, package_name: str, expectations: list[GoogleCountryExpectation]) -> list[str]:
        if not expectations:
            return []
        created = self.api.request("POST", f"applications/{package_name}/edits", payload={})
        edit_id = str(created["id"])
        base = f"applications/{package_name}/edits/{edit_id}"
        changes: list[str] = []
        try:
            for expected in expectations:
                remote = self.api.request("GET", f"{base}/countryAvailability/{expected.track}")
                actual = {country["countryCode"] for country in remote["countries"]}
                desired = set(expected.countries)
                if actual != desired:
                    raise UnsafeOperationError(
                        f"Google country availability differs for {expected.track}: missing={sorted(desired - actual)}, unexpected={sorted(actual - desired)}"
                    )
                if (
                    expected.sync_with_production is not None
                    and remote["syncWithProduction"] != expected.sync_with_production
                ):
                    raise UnsafeOperationError(f"Google country synchronization differs for {expected.track}")
                if expected.rest_of_world is not None and remote["restOfWorld"] != expected.rest_of_world:
                    raise UnsafeOperationError(
                        f"Google rest-of-world availability differs for {expected.track}"
                    )
                changes.append(
                    f"Google availability: verified track {expected.track} with {len(desired)} countries"
                )
        finally:
            self.api.request("DELETE", base)
        return changes
