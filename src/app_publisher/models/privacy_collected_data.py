from pydantic import Field

from app_publisher.enums.privacy_data_purpose import PrivacyDataPurpose
from app_publisher.models.strict_model import StrictModel


class PrivacyCollectedData(StrictModel):
    data_type: str = Field(pattern=r"^NSPrivacyCollectedDataType[A-Za-z]+$")
    linked: bool
    tracking: bool
    purposes: list[PrivacyDataPurpose] = Field(min_length=1)
