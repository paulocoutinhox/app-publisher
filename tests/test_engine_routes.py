from types import SimpleNamespace

import pytest

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_config import GoogleConfig


class FakeApple:
    def __init__(self):
        self.api = SimpleNamespace(close=lambda: None)
        self.calls = []

    def synchronize(self, project, directory, *, apply):
        self.calls.append(("sync", apply))
        return ["apple"]

    def identify(self):
        self.calls.append(("identify",))

    def upload_build(self, version, directory):
        self.calls.append(("upload", version.version))

    def versions(self):
        return [
            {
                "attributes": {
                    "platform": "IOS",
                    "versionString": "2.0",
                    "appVersionState": "PREPARE_FOR_SUBMISSION",
                }
            }
        ]


class FakeGoogle:
    def __init__(self, project):
        self.api = SimpleNamespace(close=lambda: None, request=lambda method, path: {"tracks": []})
        self.config = project.google
        self.calls = []

    def synchronize(self, project, directory, *, apply):
        self.calls.append(("sync", apply))
        return ["google"]

    def publish_release(self, directory, locales, *, apply, submit_for_review):
        self.calls.append(("release", apply, locales))
        return ["google release"]

    def start_edit(self):
        return "edit"

    def edit_path(self, edit):
        return f"applications/com.demo/edits/{edit}"


class FakeFirebase:
    def __init__(self):
        self.api = SimpleNamespace(close=lambda: None)
        self.cloud = SimpleNamespace(close=lambda: None)
        self.calls = []

    def synchronize(self, directory, *, apply):
        self.calls.append(apply)
        return ["firebase"]


def test_engine_routes_all_providers(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    apple, google, firebase = FakeApple(), FakeGoogle(project), FakeFirebase()
    monkeypatch.setattr(engine, "apple", lambda: apple)
    monkeypatch.setattr(engine, "google", lambda: google)
    monkeypatch.setattr(engine, "firebase", lambda: firebase)
    assert engine.synchronize(apply=False) == ["apple", "google", "firebase"]
    assert engine.synchronize(apply=True, provider="firebase") == ["firebase"]
    assert firebase.calls == [False, True]
    assert engine.release(apply=False, provider="all") == ["google release"]
    project.apple.versions[0] = AppleVersion(
        platform="IOS", version="2.0", artifact="binary.ipa", build_number="42"
    )
    (tmp_path / "binary.ipa").write_bytes(b"binary")
    assert engine.release(apply=True, provider="apple") == ["Apple IOS: upload binary.ipa"]
    assert apple.calls[-1] == ("upload", "2.0")
    assert engine.status(provider="all") == {
        "apple": [{"platform": "IOS", "version": "2.0", "state": "PREPARE_FOR_SUBMISSION"}],
        "google": {"tracks": []},
    }
    assert len(google.calls) >= 2


def test_engine_respects_disabled_providers(project, tmp_path, monkeypatch):
    project.apple = None
    project.firebase = None
    engine = PublicationEngine(project, tmp_path / "config.yaml")
    google = FakeGoogle(project)
    monkeypatch.setattr(engine, "google", lambda: google)
    assert engine.synchronize(apply=False, provider="apple") == []
    assert engine.release(apply=False, provider="apple") == []
    assert engine.status(provider="apple") == {}
    assert engine.synchronize(apply=False, provider="google") == ["google"]
    assert engine.release(apply=False, provider="google") == ["google release"]
    assert engine.status(provider="google") == {"google": {"tracks": []}}


def test_engine_requires_configured_provider(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "project.yaml")
    project.apple = None
    with pytest.raises(ConfigurationError, match="Apple"):
        engine.apple()
    project.google = None
    with pytest.raises(ConfigurationError, match="Google"):
        engine.google()
    project.google = GoogleConfig(package_name="com.demo")
    project.firebase = None
    with pytest.raises(ConfigurationError, match="Firebase"):
        engine.firebase()
