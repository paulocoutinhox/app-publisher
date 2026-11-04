from glob import glob
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError


def resolve_files(base: Path, patterns: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for pattern in patterns:
        absolute = project_path(base, pattern)
        paths = sorted(Path(candidate) for candidate in glob(str(absolute)))
        if not paths:
            raise ConfigurationError(f"Screenshot pattern has no matches: {pattern}")
        resolved.extend(project_path(base, path.relative_to(base.resolve())) for path in paths)
    if len(resolved) != len(set(resolved)):
        raise ConfigurationError("Duplicate screenshot paths are not allowed")
    return resolved


def resolve_assets(base: Path, patterns: list[str]) -> list[Path]:
    resolved = resolve_files(base, patterns)
    for path in resolved:
        verify_image(path)
    return resolved


def verify_image(path: Path) -> tuple[int, int]:
    if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ConfigurationError(f"Unsupported screenshot: {path}")
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            return source.size
    except (OSError, UnidentifiedImageError, ValueError) as error:
        raise ConfigurationError(f"Invalid screenshot {path}: {error}") from error
