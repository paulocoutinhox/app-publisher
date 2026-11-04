from pathlib import Path

import yaml
from pydantic import ValidationError

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.project_config import ProjectConfig


def load_project(path: Path) -> ProjectConfig:
    if not path.is_file():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ConfigurationError("The YAML root must be a mapping")
        return ProjectConfig.model_validate(document)
    except ValidationError as error:
        issues = error.errors(include_input=False, include_url=False, include_context=False)
        details = "\n".join(
            f"- {'.'.join(str(part) for part in item['loc'])}: {item['type']}" for item in issues
        )
        raise ConfigurationError(f"Invalid configuration:\n{details}") from None
    except (yaml.YAMLError, UnicodeError):
        raise ConfigurationError(
            "Invalid configuration: YAML encoding or syntax. Source content is hidden to protect credentials"
        ) from None


def resolve_path(config_file: Path, value: Path) -> Path:
    return value if value.is_absolute() else config_file.resolve().parent / value
