from pydantic import Field, model_validator

from app_publisher.models.apple_review_attachment import AppleReviewAttachment
from app_publisher.models.strict_model import StrictModel


class AppleReview(StrictModel):
    contact_first_name: str | None = None
    contact_last_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    demo_account_required: bool | None = None
    demo_account_name_env: str | None = None
    demo_account_password_env: str | None = None
    notes: str | None = None
    attachments: list[AppleReviewAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_attachment_names(self) -> "AppleReview":
        names = [item.path.name for item in self.attachments]

        if len(names) != len(set(names)):
            raise ValueError("App Review attachment filenames must be unique")

        return self
