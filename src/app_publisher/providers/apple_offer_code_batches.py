from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_offer_code_custom_batch import AppleOfferCodeCustomBatch
from app_publisher.models.apple_offer_code_one_time_batch import AppleOfferCodeOneTimeBatch


class AppleOfferCodeBatches:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self,
        offer_code_id: str,
        custom: list[AppleOfferCodeCustomBatch],
        one_time: list[AppleOfferCodeOneTimeBatch],
        *,
        apply: bool,
    ) -> list[str]:
        changes: list[str] = []
        if custom:
            remote = self.api.paginated(
                f"subscriptionOfferCodes/{offer_code_id}/customCodes", params={"limit": 200}
            )
            indexed = {
                (
                    item["attributes"]["customCode"],
                    item["attributes"].get("expirationDate"),
                    item["attributes"]["numberOfCodes"],
                )
                for item in remote
            }
            for batch in custom:
                identity = (batch.custom_code, batch.expiration_date, batch.number_of_codes)
                if identity in indexed:
                    continue
                changes.append(
                    f"Apple custom offer codes: create {batch.number_of_codes} redemptions for {batch.custom_code}"
                )
                if apply:
                    if not batch.confirm_creation:
                        raise UnsafeOperationError(
                            "Apple custom offer code generation requires confirm_creation: true"
                        )
                    attrs = {"customCode": batch.custom_code, "numberOfCodes": batch.number_of_codes}
                    if batch.expiration_date:
                        attrs["expirationDate"] = batch.expiration_date
                    self.api.request(
                        "POST",
                        "subscriptionOfferCodeCustomCodes",
                        payload=self._payload("subscriptionOfferCodeCustomCodes", offer_code_id, attrs),
                    )
        if one_time:
            remote = self.api.paginated(
                f"subscriptionOfferCodes/{offer_code_id}/oneTimeUseCodes", params={"limit": 200}
            )
            indexed = {
                (
                    item["attributes"].get("environment"),
                    item["attributes"]["expirationDate"],
                    item["attributes"]["numberOfCodes"],
                )
                for item in remote
            }
            for batch in one_time:
                identity = (batch.environment, batch.expiration_date, batch.number_of_codes)
                if identity in indexed:
                    continue
                changes.append(
                    f"Apple one-time offer codes: create {batch.number_of_codes} codes expiring {batch.expiration_date}"
                )
                if apply:
                    if not batch.confirm_creation:
                        raise UnsafeOperationError(
                            "Apple one-time offer code generation requires confirm_creation: true"
                        )
                    attrs = {"numberOfCodes": batch.number_of_codes, "expirationDate": batch.expiration_date}
                    if batch.environment:
                        attrs["environment"] = batch.environment
                    self.api.request(
                        "POST",
                        "subscriptionOfferCodeOneTimeUseCodes",
                        payload=self._payload("subscriptionOfferCodeOneTimeUseCodes", offer_code_id, attrs),
                    )
        return changes

    @staticmethod
    def _payload(resource_type: str, offer_code_id: str, attributes: dict[str, object]) -> dict[str, object]:
        return {
            "data": {
                "type": resource_type,
                "attributes": attributes,
                "relationships": {
                    "offerCode": {"data": {"type": "subscriptionOfferCodes", "id": offer_code_id}}
                },
            }
        }
