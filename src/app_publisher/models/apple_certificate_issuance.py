from pathlib import Path

from pydantic import Field

from app_publisher.enums.apple_certificate_type import AppleCertificateType
from app_publisher.models.strict_model import StrictModel


class AppleCertificateIssuance(StrictModel):
    certificate_type: AppleCertificateType
    common_name: str = Field(min_length=3)
    email_address: str = Field(min_length=3)
    private_key_output: Path
    csr_output: Path
    certificate_output: Path
    password_env: str = Field(min_length=1)
    confirm_creation: bool = False
