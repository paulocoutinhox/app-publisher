from pydantic import Field

from app_publisher.enums.apple_signing_platform import AppleSigningPlatform
from app_publisher.models.strict_model import StrictModel


class AppleRegisteredDevice(StrictModel):
    name: str = Field(min_length=1)
    udid: str = Field(min_length=5)
    platform: AppleSigningPlatform
