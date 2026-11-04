from pydantic import Field

from app_publisher.enums.android_certificate_type import AndroidCertificateType
from app_publisher.models.strict_model import StrictModel


class AndroidCertificate(StrictModel):
    sha_hash: str = Field(min_length=40)
    certificate_type: AndroidCertificateType
