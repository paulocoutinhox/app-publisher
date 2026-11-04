import re

from pydantic import Field, model_validator

from app_publisher.enums.privacy_api_category import PrivacyApiCategory
from app_publisher.models.strict_model import StrictModel


class PrivacyAccessedAPI(StrictModel):
    category: PrivacyApiCategory
    reasons: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_reasons(self) -> "PrivacyAccessedAPI":
        if any(re.fullmatch(r"[A-Z0-9]{4}\.[0-9]", reason) is None for reason in self.reasons):
            raise ValueError("Required-reason API identifiers must use Apple's XXXX.N format")
        return self
