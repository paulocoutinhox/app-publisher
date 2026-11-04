from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.store_review_reply import StoreReviewReply


class AppleStoreReviews:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def list_reviews(self) -> list[dict[str, Any]]:
        return self.api.paginated(
            f"apps/{self.app_id}/customerReviews", params={"limit": 200, "sort": "-createdDate"}
        )

    def synchronize(self, replies: list[StoreReviewReply], *, apply: bool) -> list[str]:
        if not replies:
            return []
        if apply and any(not reply.confirm_publication for reply in replies):
            raise UnsafeOperationError("Apple review replies require confirm_publication: true")
        reviews = {review["id"]: review for review in self.list_reviews()}
        changes: list[str] = []
        for reply in replies:
            if reply.review_id not in reviews:
                raise UnsafeOperationError(f"Apple review {reply.review_id} is not in the configured app")
            details = self.api.request(
                "GET", f"customerReviews/{reply.review_id}", params={"include": "response"}
            )
            existing = next(
                (
                    entry["attributes"]["responseBody"]
                    for entry in details.get("included", [])
                    if entry["type"] == "customerReviewResponses"
                ),
                None,
            )
            if existing == reply.text:
                continue
            changes.append(f"Apple review {reply.review_id}: publish response")
            if apply:
                payload = {
                    "data": {
                        "type": "customerReviewResponses",
                        "attributes": {"responseBody": reply.text},
                        "relationships": {
                            "review": {"data": {"type": "customerReviews", "id": reply.review_id}}
                        },
                    }
                }
                self.api.request("POST", "customerReviewResponses", payload=payload)
        return changes
