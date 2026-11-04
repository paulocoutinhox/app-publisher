from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class StoreReviewReply(StrictModel):
    review_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    text: str = Field(min_length=1)
    confirm_publication: bool = False
