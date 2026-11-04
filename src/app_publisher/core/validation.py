from pathlib import Path
from typing import Literal

from app_publisher.core.apple_review_file_helper import AppleReviewFileHelper
from app_publisher.core.assets import resolve_assets, resolve_files
from app_publisher.core.google_images import verify_google_store_image
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.project_config import ProjectConfig
from app_publisher.providers.apple_review_attachment_publisher import AppleReviewAttachmentPublisher
from app_publisher.providers.apple_review_screenshot_publisher import AppleReviewScreenshotPublisher

APPLE_LIMITS = {
    "name": 30,
    "subtitle": 30,
    "description": 4000,
    "keywords": 100,
    "promotional_text": 170,
    "whats_new": 4000,
}
GOOGLE_LIMITS = {"title": 30, "short_description": 80, "full_description": 4000, "release_notes": 500}


def validate_project(
    project: ProjectConfig, config_path: Path, *, local_files: Literal["all", "store", "none"] = "all"
) -> list[str]:
    issues: list[str] = []
    directory = config_path.resolve().parent
    if project.google is not None:
        configured_locales = {locale for locale, value in project.locales.items() if value.google is not None}
        for deletion in project.google.listing_deletions:
            if deletion.locale in configured_locales:
                issues.append(f"Cannot update and delete Google listing {deletion.locale} in the same YAML")
            if (
                project.google.store_details is not None
                and deletion.locale == project.google.store_details.default_language
            ):
                issues.append(f"Cannot delete the configured default Google listing {deletion.locale}")
        if project.google.release is not None:
            for symbols in project.google.release.deobfuscation_files:
                if local_files == "all" and not (directory / symbols.path).is_file():
                    issues.append(f"Missing deobfuscation file: {symbols.path}")
    for locale, config in project.locales.items():
        if len(locale) > 35 or not locale or not all(part.isalnum() for part in locale.split("-")):
            issues.append(f"Invalid locale identifier: {locale}")
        if config.apple is not None:
            for field, limit in APPLE_LIMITS.items():
                value = getattr(config.apple, field)
                if value is None and field == "name":
                    value = config.common.name
                if value is None and field == "description":
                    value = config.common.description
                if value is None and field == "whats_new":
                    value = config.common.release_notes
                if value is None:
                    continue
                length = len(value.encode("utf-8")) if field == "keywords" else len(value)
                if length > limit:
                    issues.append(
                        f"apple.{locale}.{field} exceeds {limit} {'bytes' if field == 'keywords' else 'characters'}"
                    )
            for preview_group, patterns in config.apple.app_previews.items():
                if not preview_group.strip() or preview_group != preview_group.upper():
                    issues.append(
                        f"apple.{locale}.app_previews.{preview_group} must be a placement group or display class identifier"
                    )
                if local_files != "none":
                    try:
                        paths = resolve_files(directory, patterns)
                        if len(paths) > 3:
                            issues.append(
                                f"apple.{locale}.app_previews.{preview_group} exceeds three App Previews"
                            )
                        for path in paths:
                            if path.suffix.lower() not in {".mp4", ".mov", ".m4v"}:
                                issues.append(
                                    f"apple.{locale}.app_previews: unsupported video extension {path.suffix}"
                                )
                    except ConfigurationError as error:
                        issues.append(str(error))
            for image_type, patterns in config.apple.screenshots.items():
                if not image_type.strip() or image_type != image_type.upper():
                    issues.append(
                        f"apple.{locale}.screenshots.{image_type} must be a placement group or display class identifier"
                    )
                if local_files != "none":
                    try:
                        resolve_assets(directory, patterns)
                    except ConfigurationError as error:
                        issues.append(str(error))
        if config.google is not None:
            for field, limit in GOOGLE_LIMITS.items():
                value = getattr(config.google, field)
                if value is None and field == "title":
                    value = config.common.name
                if value is None and field == "full_description":
                    value = config.common.description
                if value is None and field == "release_notes":
                    value = config.common.release_notes
                if value is not None and len(value) > limit:
                    issues.append(f"google.{locale}.{field} exceeds {limit} characters")
            for image_type, patterns in config.google.images.items():
                if image_type in {"icon", "featureGraphic", "tvBanner"} and len(patterns) != 1:
                    issues.append(f"google.{locale}.{image_type} requires exactly one image pattern")
                if image_type.endswith("Screenshots") and len(patterns) > 8:
                    issues.append(f"google.{locale}.{image_type} cannot declare more than eight screenshots")
                if local_files != "none":
                    try:
                        paths = resolve_assets(directory, patterns)
                        if image_type.endswith("Screenshots") and len(paths) > 8:
                            issues.append(
                                f"google.{locale}.{image_type} expands to more than eight screenshots"
                            )
                        for path in paths:
                            verify_google_store_image(path, image_type)
                    except ConfigurationError as error:
                        issues.append(str(error))
    for design in project.publication.screenshot_designs:
        if (
            design.output.is_absolute()
            or design.output.suffix.lower() != ".png"
            or directory not in (directory / design.output).resolve().parents
        ):
            issues.append(f"Invalid screenshot artwork output: {design.output}")
        for source in [design.source, design.font]:
            if local_files == "all" and not (directory / source).is_file():
                issues.append(f"Missing screenshot artwork input: {source}")
        if (
            design.width - 2 * design.padding <= 0
            or design.height - 3 * design.padding - design.font_size <= 0
        ):
            issues.append(f"Screenshot artwork has no drawable area: {design.output}")
    for plan in project.publication.screenshot_plans:
        for scene in plan.scenes:
            if (
                scene.output.is_absolute()
                or scene.output.suffix.lower() != ".png"
                or directory not in (directory / scene.output).resolve().parents
            ):
                issues.append(f"Invalid screenshot output for scene: {scene.name}")
            if not scene.url.startswith(("https://", "http://")) and "://" not in scene.url:
                issues.append(f"Screenshot scene URL must include a scheme: {scene.name}")
    if local_files == "all" and project.google is not None:
        if (
            project.google.release
            and project.google.release.build
            and not (directory / project.google.release.build.gradle_wrapper).is_file()
        ):
            issues.append(f"Missing Gradle wrapper: {project.google.release.build.gradle_wrapper}")
        for path in [
            project.google.data_safety_csv,
            project.google.release.artifact if project.google.release else None,
        ]:
            if path is not None and not (directory / path).is_file():
                issues.append(f"Missing file: {path}")
    if local_files != "none" and project.apple is not None:
        for screenshot in AppleReviewFileHelper.review_screenshots(project.apple):
            try:
                AppleReviewScreenshotPublisher.validate(screenshot, directory)
            except ConfigurationError as error:
                issues.append(str(error))

        if project.apple.review is not None:
            for attachment in project.apple.review.attachments:
                try:
                    AppleReviewAttachmentPublisher.validate(attachment, directory)
                except ConfigurationError as error:
                    issues.append(str(error))

    if local_files == "all" and project.apple is not None:
        for version in project.apple.versions:
            if version.build is not None and not (directory / version.build.export_options).is_file():
                issues.append(f"Missing Apple export options: {version.build.export_options}")
            if version.artifact is not None and not (directory / version.artifact).is_file():
                issues.append(f"Missing file: {version.artifact}")
    return issues
