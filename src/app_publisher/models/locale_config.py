from pydantic import Field

from app_publisher.models.apple_metadata import AppleMetadata
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.metadata_common import MetadataCommon
from app_publisher.models.strict_model import StrictModel


class LocaleConfig(StrictModel):
    common: MetadataCommon = Field(default_factory=MetadataCommon)
    apple: AppleMetadata | None = None
    google: GoogleMetadata | None = None
