from pathlib import Path

from pydantic import Field

from app_publisher.enums.google_deobfuscation_type import GoogleDeobfuscationType
from app_publisher.models.strict_model import StrictModel


class GoogleDeobfuscationFile(StrictModel):
    version_code: int = Field(gt=0)
    file_type: GoogleDeobfuscationType
    path: Path
