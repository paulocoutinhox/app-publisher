from pathlib import Path

from pydantic import Field

from app_publisher.models.android_certificate import AndroidCertificate
from app_publisher.models.strict_model import StrictModel


class FirebaseApplication(StrictModel):
    identifier: str = Field(min_length=3)
    output: Path
    display_name: str | None = None
    sha_certificates: list[AndroidCertificate] = Field(default_factory=list)
