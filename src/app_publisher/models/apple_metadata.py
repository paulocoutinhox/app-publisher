from pydantic import Field, HttpUrl

from app_publisher.models.strict_model import StrictModel


class AppleMetadata(StrictModel):
    name: str | None = None
    subtitle: str | None = None
    description: str | None = None
    keywords: str | None = None
    promotional_text: str | None = None
    whats_new: str | None = None
    support_url: HttpUrl | None = None
    marketing_url: HttpUrl | None = None
    privacy_policy_url: HttpUrl | None = None
    screenshots: dict[str, list[str]] = Field(default_factory=dict)
    app_previews: dict[str, list[str]] = Field(default_factory=dict)
    preview_frame_timecode: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}:\d{2}:\d{2}$")
