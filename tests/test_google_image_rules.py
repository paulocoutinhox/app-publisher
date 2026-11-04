import os

import pytest
from PIL import Image

from app_publisher.core.google_images import verify_google_store_image
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError


def test_google_graphic_dimensions_and_modes(tmp_path):
    cases = [
        ("icon", (512, 512), "RGBA", "PNG"),
        ("featureGraphic", (1024, 500), "RGB", "PNG"),
        ("tvBanner", (1280, 720), "RGB", "PNG"),
        ("phoneScreenshots", (1200, 1600), "RGB", "PNG"),
    ]
    for kind, size, mode, _ in cases:
        output = tmp_path / f"{kind}.png"
        Image.new(mode, size).save(output)
        assert verify_google_store_image(output, kind) is None
        invalid = tmp_path / f"{kind}-wrong.png"
        Image.new(mode, (400, 400)).save(invalid)
        if kind not in {"phoneScreenshots"}:
            with pytest.raises(ConfigurationError, match="requires"):
                verify_google_store_image(invalid, kind)
    source = tmp_path / "icon.png"
    Image.new("RGB", (512, 512)).save(source)
    with pytest.raises(ConfigurationError, match="RGBA PNG"):
        verify_google_store_image(source, "icon")
    source = tmp_path / "featureGraphic.png"
    Image.new("RGBA", (1024, 500)).save(source)
    with pytest.raises(ConfigurationError, match="without alpha"):
        verify_google_store_image(source, "featureGraphic")


def test_google_icon_size_and_image_encoding(tmp_path):
    icon = tmp_path / "noisy.png"
    Image.frombytes("RGBA", (512, 512), os.urandom(512 * 512 * 4)).save(icon)
    assert icon.stat().st_size > 1024 * 1024
    with pytest.raises(ConfigurationError, match="1024 KiB"):
        verify_google_store_image(icon, "icon")
    unsupported = tmp_path / "palette.png"
    Image.new("P", (640, 640)).save(unsupported)
    with pytest.raises(ConfigurationError, match="24-bit RGB"):
        verify_google_store_image(unsupported, "wearScreenshots")
    tall = tmp_path / "tall.png"
    Image.new("RGB", (500, 1400)).save(tall)
    with pytest.raises(ConfigurationError, match="aspect ratio"):
        verify_google_store_image(tall, "phoneScreenshots")
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (250, 300)).save(tiny)
    with pytest.raises(ConfigurationError, match="320-3840"):
        verify_google_store_image(tiny, "phoneScreenshots")
    huge = tmp_path / "huge.png"
    Image.new("RGB", (500, 3841)).save(huge)
    with pytest.raises(ConfigurationError, match="320-3840"):
        verify_google_store_image(huge, "phoneScreenshots")
    jpeg = tmp_path / "photo.jpg"
    Image.new("RGB", (1280, 720)).save(jpeg)
    assert verify_google_store_image(jpeg, "tvScreenshots") is None


def test_google_image_validation_detects_expanded_wildcards(project, tmp_path):
    for index in range(9):
        Image.new("RGB", (720, 1280)).save(tmp_path / f"screen-{index}.png")
    project.locales["en-US"].google.images = {"phoneScreenshots": ["screen-*.png"]}
    issues = validate_project(project, tmp_path / "app.yaml")
    assert any("expands to more than eight" in issue for issue in issues)
    project.locales["en-US"].google.images = {"featureGraphic": ["screen-0.png"]}
    issues = validate_project(project, tmp_path / "app.yaml")
    assert any("requires 1024x500" in issue for issue in issues)
