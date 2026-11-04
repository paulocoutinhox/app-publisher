from pydantic import Field

from app_publisher.models.apple_certificate_issuance import AppleCertificateIssuance
from app_publisher.models.apple_registered_device import AppleRegisteredDevice
from app_publisher.models.apple_signing_certificate import AppleSigningCertificate
from app_publisher.models.apple_signing_profile import AppleSigningProfile
from app_publisher.models.strict_model import StrictModel


class AppleSigningConfig(StrictModel):
    certificates: list[AppleSigningCertificate] = Field(default_factory=list)
    profiles: list[AppleSigningProfile] = Field(default_factory=list)
    devices: list[AppleRegisteredDevice] = Field(default_factory=list)
    issuance: list[AppleCertificateIssuance] = Field(default_factory=list)
