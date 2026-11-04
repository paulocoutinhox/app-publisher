from pydantic import Field, HttpUrl, field_validator

from app_publisher.enums.google_image_type import GoogleImageType
from app_publisher.models.strict_model import StrictModel


class GoogleMetadata(StrictModel):
    title: str | None = None
    short_description: str | None = None
    full_description: str | None = None
    video: HttpUrl | None = None
    release_notes: str | None = None
    images: dict[
        GoogleImageType,
        list[str],
    ] = Field(default_factory=dict)

    @field_validator("images", mode="before")
    @classmethod
    def normalize_image_types(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("Google image groups must be a mapping")

        normalized = {}

        for name, paths in value.items():
            canonical = GoogleImageType(name).value

            if canonical in normalized:
                raise ValueError("Duplicate Google image group after case normalization")

            normalized[canonical] = paths

        return normalized
