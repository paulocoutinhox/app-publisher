import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from app_publisher.core.apple_review_file_helper import AppleReviewFileHelper
from app_publisher.core.assets import resolve_files
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError

Provider = Literal["all", "apple", "google", "firebase"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_manifest(engine: Any) -> dict[str, str]:
    project = engine.project
    root = engine.directory
    files: set[Path] = set()
    for localized in project.locales.values():
        if localized.apple is not None:
            for patterns in [*localized.apple.screenshots.values(), *localized.apple.app_previews.values()]:
                files.update(resolve_files(root, patterns))
        if localized.google is not None:
            for patterns in localized.google.images.values():
                files.update(resolve_files(root, patterns))
    for design in project.publication.screenshot_designs:
        files.add(project_path(root, design.source))
        files.add(project_path(root, design.font))
    if project.apple is not None:
        for path in AppleReviewFileHelper.paths(project.apple):
            files.add(project_path(root, path))

        for version in project.apple.versions:
            if version.artifact is not None:
                files.add(project_path(root, version.artifact))
            if version.build is not None:
                files.add(project_path(root, version.build.export_options))
    if project.google is not None:
        if project.google.data_safety_csv is not None:
            files.add(project_path(root, project.google.data_safety_csv))
        release = project.google.release
        if release is not None:
            if release.artifact is not None:
                files.add(project_path(root, release.artifact))
            for symbols in release.deobfuscation_files:
                files.add(project_path(root, symbols.path))
            if release.build is not None:
                files.add(project_path(root, release.build.gradle_wrapper))
    return {
        path.relative_to(root).as_posix(): sha256_file(path) if path.is_file() else "MISSING"
        for path in sorted(files)
    }


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def plan_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def generate_plan(engine: Any, provider: Provider = "all") -> dict[str, Any]:
    engine.validate(local_files="store")
    assets = asset_manifest(engine)
    changes = engine.synchronize(apply=False, provider=provider)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "provider": provider,
        "application": engine.project.app.id,
        "apple_app_id": engine.project.apple.app_id if engine.project.apple is not None else None,
        "google_package": engine.project.google.package_name if engine.project.google is not None else None,
        "firebase_project": engine.project.firebase.project_id
        if engine.project.firebase is not None
        else None,
        "config_sha256": sha256_file(engine.file),
        "assets": assets,
        "changes": changes,
        "caveats": [
            "Changes across stores are not atomic.",
            "Google dry runs create and discard an edit without publishing it.",
            "A store may change after the last remote-state check.",
        ],
    }
    return {**payload, "plan_sha256": plan_digest(payload)}


def store_plan(plan: dict[str, Any], target: Path) -> Path:
    if target.is_symlink():
        raise UnsafeOperationError("Refusing to write a plan through a symbolic link")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as error:
        raise UnsafeOperationError(f"Refusing to overwrite an existing plan: {target}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def load_plan(file: Path) -> dict[str, Any]:
    if file.is_symlink() or not file.is_file():
        raise ConfigurationError("Plan must be an existing regular file, not a symbolic link")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ConfigurationError("Invalid JSON publication plan") from error
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("plan_sha256"), str)
    ):
        raise ConfigurationError("Unsupported publication plan format")
    body = {key: value for key, value in data.items() if key != "plan_sha256"}
    if (
        body.keys()
        != {
            "schema_version",
            "provider",
            "application",
            "apple_app_id",
            "google_package",
            "firebase_project",
            "config_sha256",
            "assets",
            "changes",
            "caveats",
        }
        or plan_digest(body) != data["plan_sha256"]
    ):
        raise UnsafeOperationError("Publication plan content or digest has been modified")
    if data["provider"] not in {"all", "apple", "google", "firebase"} or not isinstance(
        data["changes"], list
    ):
        raise ConfigurationError("Publication plan contains an invalid provider or change list")
    return data


def apply_plan(engine: Any, saved: dict[str, Any], *, apply: bool = False) -> list[str]:
    provider: Provider = saved["provider"]
    if sha256_file(engine.file) != saved["config_sha256"]:
        raise UnsafeOperationError("YAML changed since the plan was generated. Generate a new plan")
    if engine.project.app.id != saved["application"]:
        raise UnsafeOperationError("Plan application identity does not match the YAML")
    identities = (
        engine.project.apple.app_id if engine.project.apple else None,
        engine.project.google.package_name if engine.project.google else None,
        engine.project.firebase.project_id if engine.project.firebase else None,
    )
    if identities != (saved["apple_app_id"], saved["google_package"], saved["firebase_project"]):
        raise UnsafeOperationError("Plan store identity does not match the YAML")
    if asset_manifest(engine) != saved["assets"]:
        raise UnsafeOperationError("Local assets changed since the plan was generated. Generate a new plan")
    current = engine.synchronize(apply=False, provider=provider)
    if current != saved["changes"]:
        raise UnsafeOperationError(
            "Remote store state changed since planning. Nothing was applied. Generate a new plan"
        )
    if not apply:
        return current

    return engine.synchronize(apply=True, provider=provider)
