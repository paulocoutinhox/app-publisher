from pathlib import Path

from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class AppleSigningCertificate(StrictModel):
    certificate_id: str = Field(min_length=1)
    output: Path
