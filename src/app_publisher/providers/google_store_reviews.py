from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.store_review_reply import StoreReviewReply


class GoogleStoreReviews:
    def __init__(self, api: APIClient, package_name: str):
        self.api = api
        self.package_name = package_name

    def list_reviews(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            params = {"maxResults": 100, "token": token} if token is not None else {"maxResults": 100}
            response = self.api.request("GET", f"applications/{self.package_name}/reviews", params=params)
            items.extend(response.get("reviews", []))
            next_token = response.get("tokenPagination", {}).get("nextPageToken")
            if next_token is None:
                return items
            if next_token in seen:
                raise RemoteAPIError("Google review pagination repeated a token")
            seen.add(next_token)
            token = next_token

    def synchronize(self, replies: list[StoreReviewReply], *, apply: bool) -> list[str]:
        if not replies:
            return []
        if apply and any(not reply.confirm_publication for reply in replies):
            raise UnsafeOperationError("Google review replies require confirm_publication: true")
        reviews = {review["reviewId"]: review for review in self.list_reviews()}
        changes: list[str] = []
        for reply in replies:
            if len(reply.text) > 350:
                raise UnsafeOperationError("Google review responses must not exceed 350 characters")
            review = reviews.get(reply.review_id)
            if review is None:
                raise UnsafeOperationError(f"Google review {reply.review_id} is not in the configured app")
            existing = [
                comment["developerComment"]["text"]
                for comment in review.get("comments", [])
                if "developerComment" in comment
            ]
            if existing and existing[-1] == reply.text:
                continue
            changes.append(f"Google review {reply.review_id}: publish response")
            if apply:
                self.api.request(
                    "POST",
                    f"applications/{self.package_name}/reviews/{reply.review_id}:reply",
                    payload={"replyText": reply.text},
                )
        return changes
