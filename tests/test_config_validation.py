from pathlib import Path

import pytest
import yaml
from PIL import Image
from pydantic import ValidationError

from app_publisher.config import load_project, resolve_path
from app_publisher.core.assets import resolve_assets, verify_image
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.project_config import ProjectConfig


def test_config_loads_file_and_rejects_invalid(tmp_path, project):
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(project.model_dump(mode="json")), encoding="utf-8")
    assert load_project(path) == project
    assert resolve_path(path, Path("images/one.png")) == tmp_path / "images/one.png"
    assert resolve_path(path, tmp_path / "absolute") == tmp_path / "absolute"
    with pytest.raises(ConfigurationError, match="not found"):
        load_project(tmp_path / "missing.yaml")
    path.write_text("- item", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="root"):
        load_project(path)
    path.write_text("invalid: [", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid configuration"):
        load_project(path)
    path.write_text("extra: 123\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Invalid configuration"):
        load_project(path)


def test_strict_models_reject_unknown_and_ambiguous(project):
    data = project.model_dump(mode="python")
    data["secret_option"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProjectConfig.model_validate(data)
    data.pop("secret_option")
    data["apple"]["versions"].append({"platform": "IOS", "version": "3.0"})
    with pytest.raises(ValidationError, match="unique"):
        ProjectConfig.model_validate(data)
    data["apple"]["versions"].pop()
    data["apple"]["versions"][0]["artifact"] = Path("builds/app.ipa")
    with pytest.raises(ValidationError, match="build_number"):
        ProjectConfig.model_validate(data)
    data["apple"]["versions"][0]["artifact"] = None
    data["google"]["release"]["status"] = "inProgress"
    with pytest.raises(ValidationError, match="rollout_fraction"):
        ProjectConfig.model_validate(data)
    data["google"]["release"]["rollout_fraction"] = 0.5
    data["google"]["release"]["status"] = "completed"
    with pytest.raises(ValidationError, match="only valid"):
        ProjectConfig.model_validate(data)
    data["google"]["release"]["rollout_fraction"] = None
    data["app"]["default_locale"] = "fr-FR"
    with pytest.raises(ValidationError, match="default locale"):
        ProjectConfig.model_validate(data)
    data["app"]["default_locale"] = "en-US"
    for name in ["apple", "google", "firebase"]:
        data[name] = None
    with pytest.raises(ValidationError, match="At least one provider"):
        ProjectConfig.model_validate(data)


def test_asset_validation(tmp_path, png):
    assert verify_image(png) == (1200, 1600)
    assert resolve_assets(tmp_path, ["*.png"]) == [png]
    with pytest.raises(ConfigurationError, match="Duplicate screenshot"):
        resolve_assets(tmp_path, ["*.png", "shot.png"])
    with pytest.raises(ConfigurationError, match="no matches"):
        resolve_assets(tmp_path, ["missing/*.png"])
    wrong = tmp_path / "invalid.gif"
    wrong.write_text("GIF")
    with pytest.raises(ConfigurationError, match="Unsupported"):
        verify_image(wrong)
    corrupt = tmp_path / "invalid.png"
    corrupt.write_text("Not a PNG")
    with pytest.raises(ConfigurationError, match="Invalid screenshot"):
        verify_image(corrupt)
    rgb = tmp_path / "screen.jpg"
    Image.new("RGB", (12, 12), "red").save(rgb)
    assert verify_image(rgb) == (12, 12)


def test_limits_images_and_artifacts(tmp_path, project, png):
    assert validate_project(project, tmp_path / "app.yaml") == []
    apple = project.locales["en-US"].apple
    google = project.locales["en-US"].google
    apple.name = "x" * 31
    apple.keywords = "é" * 60
    apple.screenshots = {"bad": ["shot.png"], "APP_IPHONE_65": ["missing.png"]}
    google.title = "x" * 31
    google.short_description = "a" * 81
    google.full_description = "t" * 4001
    google.images = {"phoneScreenshots": ["shot.png"]}
    project.google.data_safety_csv = Path("safety.csv")
    project.google.release.artifact = Path("build/app.aab")
    issues = validate_project(project, tmp_path / "app.yaml")
    assert len(issues) == 9
    assert any("100 bytes" in error for error in issues)
    assert any("must be a placement group" in error for error in issues)
    assert any("Missing file" in error for error in issues)
    (tmp_path / "safety.csv").write_text("csv", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "app.aab").write_bytes(b"app")
    apple.screenshots = {"APP_IPHONE_65": ["shot.png"]}
    apple.name = "Valid"
    apple.keywords = "safe"
    google.title = "Valid"
    google.short_description = "Valid"
    google.full_description = "Valid"
    assert validate_project(project, tmp_path / "app.yaml") == []
