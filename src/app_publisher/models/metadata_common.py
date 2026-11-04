from app_publisher.models.strict_model import StrictModel


class MetadataCommon(StrictModel):
    name: str | None = None
    description: str | None = None
    release_notes: str | None = None
