import plistlib
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.privacy_manifest_writer import PrivacyManifestWriter
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_privacy_manifest import ApplePrivacyManifest


def configured_privacy():
    return ApplePrivacyManifest(
        output="Sources/PrivacyInfo.xcprivacy",
        tracking=True,
        tracking_domains=["analytics.example.com"],
        collected_data=[
            {
                "data_type": "NSPrivacyCollectedDataTypeEmailAddress",
                "linked": True,
                "tracking": False,
                "purposes": ["NSPrivacyCollectedDataTypePurposeAppFunctionality"],
            }
        ],
        accessed_apis=[{"category": "NSPrivacyAccessedAPICategoryUserDefaults", "reasons": ["CA92.1"]}],
    )


def test_privacy_schema_validations():
    config = configured_privacy()
    assert config.accessed_apis[0].reasons == ["CA92.1"]
    cases = [
        ({"tracking": True, "tracking_domains": []}, "Tracking requires"),
        ({"tracking": False}, "Tracking domains must not"),
        ({"tracking_domains": ["https://tracking.example.com"]}, "must be domain names"),
        (
            {
                "collected_data": [config.collected_data[0].model_copy(update={"tracking": True})],
                "tracking": False,
                "tracking_domains": [],
            },
            "Tracking data types require",
        ),
        ({"accessed_apis": [config.accessed_apis[0], config.accessed_apis[0]]}, "must be unique"),
        ({"collected_data": [config.collected_data[0], config.collected_data[0]]}, "must be unique"),
    ]
    for modification, message in cases:
        with pytest.raises(ValidationError, match=message):
            ApplePrivacyManifest.model_validate({**config.model_dump(), **modification})
    with pytest.raises(ValidationError, match="Required-reason API"):
        ApplePrivacyManifest.model_validate(
            {
                **config.model_dump(),
                "accessed_apis": [
                    {"category": "NSPrivacyAccessedAPICategoryUserDefaults", "reasons": ["invalid"]}
                ],
            }
        )
    with pytest.raises(ValidationError, match="NSPrivacyCollectedDataType"):
        ApplePrivacyManifest.model_validate(
            {
                **config.model_dump(),
                "collected_data": [
                    {
                        "data_type": "NotAnAppleDataType",
                        "linked": False,
                        "tracking": False,
                        "purposes": ["NSPrivacyCollectedDataTypePurposeAnalytics"],
                    }
                ],
            }
        )


def test_privacy_manifest_render_and_reuse(tmp_path):
    config = configured_privacy()
    writer = PrivacyManifestWriter()
    expected = ["Apple privacy manifest: update Sources/PrivacyInfo.xcprivacy"]
    assert writer.synchronize(config, tmp_path, apply=False) == expected
    target = tmp_path / config.output
    assert not target.exists()
    assert writer.synchronize(config, tmp_path, apply=True) == expected
    assert target.is_file()
    data = plistlib.loads(target.read_bytes())
    assert data["NSPrivacyTracking"] is True
    assert data["NSPrivacyTrackingDomains"] == ["analytics.example.com"]
    assert data["NSPrivacyCollectedDataTypes"][0]["NSPrivacyCollectedDataTypeLinked"] is True
    assert data["NSPrivacyAccessedAPITypes"][0]["NSPrivacyAccessedAPITypeReasons"] == ["CA92.1"]
    assert writer.synchronize(config, tmp_path, apply=False) == []
    config.collected_data[0].linked = False
    assert writer.synchronize(config, tmp_path, apply=True) == expected
    assert (
        plistlib.loads(target.read_bytes())["NSPrivacyCollectedDataTypes"][0][
            "NSPrivacyCollectedDataTypeLinked"
        ]
        is False
    )
    assert (
        writer.document(ApplePrivacyManifest(output="PrivacyInfo.xcprivacy"))["NSPrivacyTrackingDomains"]
        == []
    )


def test_privacy_manifest_path_validation_and_atomic_cleanup(tmp_path, monkeypatch):
    writer = PrivacyManifestWriter()
    config = configured_privacy()
    for path in ["../outside.xcprivacy", "Sources/not-plist.txt", "."]:
        unsafe = config.model_copy(update={"output": Path(path)})
        with pytest.raises(UnsafeOperationError, match="must be an .xcprivacy file inside"):
            writer.synchronize(unsafe, tmp_path, apply=False)
    (tmp_path / "Sources").mkdir()
    (tmp_path / "Sources" / "folder.xcprivacy").mkdir()
    with pytest.raises(UnsafeOperationError, match="cannot be a directory"):
        writer.synchronize(
            config.model_copy(update={"output": Path("Sources/folder.xcprivacy")}), tmp_path, apply=False
        )
    from app_publisher.core import privacy_manifest_writer as privacy_manifest

    monkeypatch.setattr(
        privacy_manifest.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replacement failed"))
    )
    with pytest.raises(OSError, match="replacement failed"):
        writer.synchronize(config, tmp_path, apply=True)
    assert list((tmp_path / "Sources").glob(".app-publisher-*")) == []


def test_privacy_engine_and_cli(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    with pytest.raises(ConfigurationError, match="privacy_manifest is not configured"):
        engine.privacy(apply=False)
    project.apple.privacy_manifest = configured_privacy()
    assert engine.privacy(apply=False) == ["Apple privacy manifest: update Sources/PrivacyInfo.xcprivacy"]
    monkeypatch.setattr("app_publisher.cli.open_engine", lambda config: engine)
    response = CliRunner().invoke(app, ["privacy-manifest", "config.yaml", "--apply"])
    assert response.exit_code == 0
    assert (tmp_path / "Sources" / "PrivacyInfo.xcprivacy").is_file()
    project.apple = None
    with pytest.raises(ConfigurationError, match="not configured"):
        engine.privacy(apply=False)


def test_privacy_manifest_tempfile_failure(tmp_path, monkeypatch):
    from app_publisher.core import privacy_manifest_writer as privacy_manifest

    monkeypatch.setattr(
        privacy_manifest.tempfile,
        "NamedTemporaryFile",
        lambda **kwargs: (_ for _ in ()).throw(OSError("no disk space")),
    )
    with pytest.raises(OSError, match="no disk space"):
        PrivacyManifestWriter().synchronize(configured_privacy(), tmp_path, apply=True)
