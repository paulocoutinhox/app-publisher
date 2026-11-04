import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_new_capabilities import MemoryAPI

from app_publisher import cli
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_signing_certificate import AppleSigningCertificate
from app_publisher.models.apple_signing_config import AppleSigningConfig
from app_publisher.models.apple_signing_profile import AppleSigningProfile
from app_publisher.providers.apple_signing_manager import AppleSigningManager


def _profile(creating=False, **kwargs):
    return AppleSigningProfile(
        name="My Distribution",
        profile_type="IOS_APP_STORE",
        certificate_ids=["cert"],
        output=Path("signing/app.mobileprovision"),
        create_if_missing=creating,
        **kwargs,
    )


def _remote_profile(**kwargs):
    return {
        "data": {
            "id": "p1",
            "attributes": {
                "profileType": "IOS_APP_STORE",
                "profileContent": base64.b64encode(b"profile-bytes").decode(),
            },
            "relationships": {
                "bundleId": {"data": {"id": "bundle"}},
                "certificates": {"data": [{"id": "cert"}]},
                "devices": {"data": []},
            },
            **kwargs,
        }
    }


def _signing_api(existing=True):
    lists = {
        "bundleIds": [{"id": "bundle", "attributes": {"identifier": "com.demo"}}],
        "profiles": [{"id": "p1", "attributes": {"name": "My Distribution"}}] if existing else [],
    }
    responses = {
        ("GET", "certificates/cert"): {
            "data": {
                "id": "cert",
                "attributes": {"certificateContent": base64.b64encode(b"certificate-bytes").decode()},
            }
        },
        ("GET", "profiles/p1"): _remote_profile(),
        ("GET", "profiles/created"): _remote_profile(),
    }
    return MemoryAPI(responses=responses, lists=lists)


def test_apple_signing_download_certificate_and_existing_profile(tmp_path):
    api = _signing_api()
    subject = AppleSigningManager(api, "com.demo")
    config = AppleSigningConfig(
        certificates=[AppleSigningCertificate(certificate_id="cert", output=Path("signing/cert.cer"))],
        profiles=[_profile()],
    )
    assert subject.synchronize(config, tmp_path, apply=False) == [
        "Apple signing: download signing/cert.cer",
        "Apple signing: download signing/app.mobileprovision",
    ]
    assert subject.synchronize(config, tmp_path, apply=True) == [
        "Apple signing: download signing/cert.cer",
        "Apple signing: download signing/app.mobileprovision",
    ]
    assert (tmp_path / "signing/cert.cer").read_bytes() == b"certificate-bytes"
    assert (tmp_path / "signing/app.mobileprovision").read_bytes() == b"profile-bytes"
    assert subject.synchronize(config, tmp_path, apply=True) == []
    (tmp_path / "signing/cert.cer").write_bytes(b"wrong")
    with pytest.raises(UnsafeOperationError, match="different bytes"):
        subject.synchronize(config, tmp_path, apply=True)


def test_apple_signing_profiles_created_explicitly(tmp_path):
    api = _signing_api(existing=False)
    config = AppleSigningConfig(profiles=[_profile(creating=True)])
    subject = AppleSigningManager(api, "com.demo")
    assert subject.synchronize(config, tmp_path, apply=False) == [
        "Apple signing: create profile My Distribution"
    ]
    assert subject.synchronize(config, tmp_path, apply=True) == [
        "Apple signing: create profile My Distribution",
        "Apple signing: download signing/app.mobileprovision",
    ]
    created = [call for call in api.calls if call[0] == "POST" and call[1] == "profiles"]
    assert created[0][2]["payload"]["data"]["relationships"]["bundleId"]["data"]["id"] == "bundle"
    assert (tmp_path / "signing/app.mobileprovision").read_bytes() == b"profile-bytes"
    api.lists["profiles"] = [{"id": "p1", "attributes": {"name": "My Distribution"}}]
    assert subject.synchronize(config, tmp_path, apply=True) == []


def test_apple_signing_profile_devices_and_mismatches(tmp_path):
    api = _signing_api(existing=False)
    remote = _remote_profile()
    remote["data"]["relationships"]["devices"]["data"] = [{"id": "test-device"}]
    api.responses[("GET", "profiles/created")] = remote
    config = AppleSigningConfig(
        profiles=[_profile(creating=True).model_copy(update={"device_ids": ["test-device"]})]
    )
    subject = AppleSigningManager(api, "com.demo")
    assert subject.synchronize(config, tmp_path, apply=True)
    assert any(
        call[0] == "POST"
        and call[2]["payload"]["data"]["relationships"]["devices"]["data"][0]["id"] == "test-device"
        for call in api.calls
    )
    api.lists["bundleIds"] = []
    with pytest.raises(UnsafeOperationError, match="exactly one"):
        subject.synchronize(config, tmp_path, apply=False)
    api.lists["bundleIds"] = [{"id": "bundle", "attributes": {"identifier": "com.demo"}}]
    api.lists["profiles"] = [
        {"id": "one", "attributes": {"name": "My Distribution"}},
        {"id": "two", "attributes": {"name": "My Distribution"}},
    ]
    with pytest.raises(UnsafeOperationError, match="ambiguous"):
        subject.synchronize(config, tmp_path, apply=False)


def test_apple_signing_profile_create_missing_and_mismatched_relationships(tmp_path):
    api = _signing_api(existing=False)
    subject = AppleSigningManager(api, "com.demo")
    with pytest.raises(UnsafeOperationError, match="create_if_missing"):
        subject.synchronize(AppleSigningConfig(profiles=[_profile()]), tmp_path, apply=True)
    api.lists["profiles"] = [{"id": "p1", "attributes": {"name": "My Distribution"}}]
    profile = _profile()
    wrong_type = _remote_profile()
    wrong_type["data"]["attributes"]["profileType"] = "IOS_APP_DEVELOPMENT"
    api.responses[("GET", "profiles/p1")] = wrong_type
    with pytest.raises(UnsafeOperationError, match="incompatible type"):
        subject.synchronize(AppleSigningConfig(profiles=[profile]), tmp_path, apply=False)
    wrong_type["data"]["attributes"]["profileType"] = "IOS_APP_STORE"
    wrong_type["data"]["relationships"]["bundleId"]["data"]["id"] = "other"
    with pytest.raises(UnsafeOperationError, match="different Bundle ID"):
        subject.synchronize(AppleSigningConfig(profiles=[profile]), tmp_path, apply=False)
    wrong_type["data"]["relationships"]["bundleId"]["data"]["id"] = "bundle"
    wrong_type["data"]["relationships"]["certificates"]["data"] = []
    with pytest.raises(UnsafeOperationError, match="certificates do not match"):
        subject.synchronize(AppleSigningConfig(profiles=[profile]), tmp_path, apply=False)
    wrong_type["data"]["relationships"]["certificates"]["data"] = [{"id": "cert"}]
    wrong_type["data"]["relationships"]["devices"]["data"] = [{"id": "extra"}]
    with pytest.raises(UnsafeOperationError, match="devices do not match"):
        subject.synchronize(AppleSigningConfig(profiles=[profile]), tmp_path, apply=False)


def test_apple_signing_certificate_identity_content_and_path(tmp_path):
    api = _signing_api()
    subject = AppleSigningManager(api, "com.demo")
    api.responses[("GET", "certificates/cert")]["data"]["id"] = "wrong"
    config = AppleSigningConfig(
        certificates=[AppleSigningCertificate(certificate_id="cert", output=Path("signing/cert.cer"))]
    )
    with pytest.raises(UnsafeOperationError, match="certificate identifier"):
        subject.synchronize(config, tmp_path, apply=True)
    api.responses[("GET", "certificates/cert")]["data"]["id"] = "cert"
    api.responses[("GET", "certificates/cert")]["data"]["attributes"]["certificateContent"] = "bad*&"
    with pytest.raises(UnsafeOperationError, match="malformed signing data"):
        subject.synchronize(config, tmp_path, apply=True)
    with pytest.raises(UnsafeOperationError, match="outside the configuration directory"):
        AppleSigningManager._save(b"anything", tmp_path, Path("../outside.cer"), apply=False)


def test_apple_signing_invalid_model_rejected():
    with pytest.raises(ValidationError):
        AppleSigningProfile(
            name="X", profile_type="NOT_A_REAL_TYPE", certificate_ids=["one"], output=Path("out")
        )


def test_apple_signing_engine_and_cli(monkeypatch, project, tmp_path):
    project.apple.signing = AppleSigningConfig()
    event = []
    wrapper = SimpleNamespace(
        config=project.apple, identify=lambda: None, api=SimpleNamespace(close=lambda: event.append("closed"))
    )
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: wrapper)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleSigningManager",
        lambda *args: SimpleNamespace(synchronize=lambda *args, **kwargs: ["signing success"]),
    )
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    assert engine.signing(apply=False) == ["signing success"]
    assert event == ["closed"]
    project.apple.signing = None
    with pytest.raises(ConfigurationError, match="signing configuration is required"):
        engine.signing(apply=False)
    result = []
    monkeypatch.setattr(
        cli,
        "open_engine",
        lambda config: SimpleNamespace(signing=lambda **kwargs: result.append(kwargs) or ["signing success"]),
    )
    monkeypatch.setattr(cli, "show_changes", lambda changes: result.extend(changes))
    cli.signing(Path("app.yaml"), apply=True)
    assert result == [{"apply": True}, "signing success"]


def test_apple_signing_certificate_only(tmp_path):
    api = _signing_api()
    config = AppleSigningConfig(
        certificates=[AppleSigningCertificate(certificate_id="cert", output=Path("signing/cert.cer"))]
    )
    assert AppleSigningManager(api, "com.demo").synchronize(config, tmp_path, apply=False) == [
        "Apple signing: download signing/cert.cer"
    ]
    assert all(item[1] != "bundleIds" for item in api.calls)
