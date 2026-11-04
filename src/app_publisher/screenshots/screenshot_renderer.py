from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.screenshot_design import ScreenshotDesign


class ScreenshotRenderer:
    def render(self, design: ScreenshotDesign, directory: Path) -> Path:
        source = project_path(directory, design.source)
        font_file = project_path(directory, design.font)
        if not source.is_file() or not font_file.is_file():
            raise ConfigurationError(f"Screenshot source or font is missing: {design.source}, {design.font}")
        with Image.open(source) as picture:
            screenshot = picture.convert("RGBA")
        canvas = Image.new("RGBA", (design.width, design.height), design.background)
        draw = ImageDraw.Draw(canvas)
        title_font = ImageFont.truetype(str(font_file), design.font_size)
        title_width = design.width - 2 * design.padding
        if draw.textbbox((0, 0), design.title, font=title_font)[2] > title_width:
            raise ConfigurationError(f"Screenshot title exceeds the available width: {design.title}")
        text_x = (design.width - draw.textbbox((0, 0), design.title, font=title_font)[2]) // 2
        draw.text((text_x, design.padding), design.title, font=title_font, fill=design.foreground)
        header = design.padding * 2 + design.font_size
        available = (design.width - 2 * design.padding, design.height - header - design.padding)
        screenshot.thumbnail(available, Image.Resampling.LANCZOS)
        position = ((design.width - screenshot.width) // 2, header + (available[1] - screenshot.height) // 2)
        canvas.alpha_composite(screenshot, position)
        destination = project_path(directory, design.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(destination, format="PNG", optimize=True)
        return destination
