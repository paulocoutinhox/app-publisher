import json
import plistlib
from pathlib import Path
from typing import Any

from app_publisher.errors.configuration_error import ConfigurationError


class ConfigurationFileHelper:
    @staticmethod
    def read(path: Path, *, apple: bool) -> dict[str, Any]:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ConfigurationError("A required native configuration is missing or exceeds the size limit")

        try:
            raw = path.read_bytes()
            document = plistlib.loads(raw) if apple else json.loads(raw)
        except (ValueError, UnicodeError, plistlib.InvalidFileException):
            raise ConfigurationError(
                "A native configuration could not be decoded. Values are hidden"
            ) from None

        if not isinstance(document, dict):
            raise ConfigurationError("A native configuration must contain a dictionary")

        return document
