from pathlib import Path

from app_publisher.errors.configuration_error import ConfigurationError


def project_path(directory: Path, configured: Path | str) -> Path:
    relative = Path(configured)
    if relative.is_absolute():
        raise ConfigurationError(f"Project paths must be relative: {configured}")
    root = directory.resolve()
    destination = (root / relative).resolve()
    if not destination.is_relative_to(root) or destination == root:
        raise ConfigurationError(f"Path escapes the configured project directory: {configured}")
    return destination
