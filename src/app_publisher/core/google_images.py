from pathlib import Path

from PIL import Image

from app_publisher.errors.configuration_error import ConfigurationError

GOOGLE_GRAPHIC_SIZES = {"icon": (512, 512), "featureGraphic": (1024, 500), "tvBanner": (1280, 720)}


def verify_google_store_image(path: Path, image_type: str) -> None:
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
        image_format = image.format
    required = GOOGLE_GRAPHIC_SIZES.get(image_type)
    if required is not None and (width, height) != required:
        raise ConfigurationError(f"Google {image_type} requires {required[0]}x{required[1]} pixels: {path}")
    if image_type == "icon":
        if image_format != "PNG" or mode != "RGBA":
            raise ConfigurationError(f"Google icon must be a 32-bit RGBA PNG: {path}")
        if path.stat().st_size > 1024 * 1024:
            raise ConfigurationError(f"Google icon exceeds 1024 KiB: {path}")
        return
    if image_format not in {"JPEG", "PNG"} or mode != "RGB":
        raise ConfigurationError(
            f"Google {image_type} requires RGB JPEG or 24-bit RGB PNG without alpha: {path}"
        )
    if required is None and (
        min(width, height) < 320 or max(width, height) > 3840 or max(width, height) > 2 * min(width, height)
    ):
        raise ConfigurationError(
            f"Google {image_type} screenshot must be 320-3840 px with an aspect ratio no wider than 2:1: {path}"
        )
