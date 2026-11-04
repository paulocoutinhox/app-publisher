from pydantic import model_validator

from app_publisher.enums.apple_device_family import AppleDeviceFamily
from app_publisher.models.strict_model import StrictModel


class AppleAccessibilityDeclaration(StrictModel):
    device_family: AppleDeviceFamily
    publish: bool = False
    voiceover: bool | None = None
    voice_control: bool | None = None
    larger_text: bool | None = None
    sufficient_contrast: bool | None = None
    dark_interface: bool | None = None
    differentiate_without_color_alone: bool | None = None
    reduced_motion: bool | None = None
    captions: bool | None = None
    audio_descriptions: bool | None = None

    @model_validator(mode="after")
    def validate_declaration(self) -> "AppleAccessibilityDeclaration":
        attributes = self.model_dump(exclude={"device_family", "publish"}, exclude_none=True)
        if not attributes:
            raise ValueError("Accessibility declarations require explicit support values")
        return self
