import json
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.android_crashlytics_symbols import AndroidCrashlyticsSymbols
from app_publisher.models.crashlytics_config import CrashlyticsConfig
from app_publisher.models.firebase_config import FirebaseConfig
from app_publisher.providers.crashlytics_publisher import CrashlyticsPublisher
from app_publisher.toolchain.android_artifact_helper import AndroidArtifactHelper
from app_publisher.toolchain.apple_symbol_helper import AppleSymbolHelper
from app_publisher.toolchain.configuration_file_helper import ConfigurationFileHelper
from app_publisher.toolchain.environment_doctor import EnvironmentDoctor
from app_publisher.toolchain.process_helper import ProcessHelper

UUID = "12345678-1234-1234-1234-123456789ABC"
OTHER_UUID = "87654321-4321-4321-4321-CBA987654321"


@pytest.fixture
def symbol_project(tmp_path, monkeypatch):
    archive = tmp_path / "app.xcarchive"
    app = archive / "Products/Applications/Demo.app"
    app.mkdir(parents=True)
    (app / "Demo").write_bytes(b"Mach-O fixture")
    info = {
        "CFBundleIdentifier": "com.demo",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "7",
        "CFBundleExecutable": "Demo",
    }
    (app / "Info.plist").write_bytes(plistlib.dumps(info))
    symbols = archive / "dSYMs/Demo.app.dSYM"
    symbols.mkdir(parents=True)
    firebase = {"GOOGLE_APP_ID": "1:123:ios:abc", "BUNDLE_ID": "com.demo", "PROJECT_ID": "demo-123456"}
    (tmp_path / "Google.plist").write_bytes(plistlib.dumps(firebase))
    tool = tmp_path / "upload-symbols"
    tool.write_bytes(b"tool fixture")
    tool.chmod(0o755)
    monkeypatch.setenv("FIREBASE_UPLOAD_SYMBOLS_PATH", str(tool))
    bundletool = tmp_path / "bundletool.jar"
    bundletool.write_bytes(b"jar fixture")
    monkeypatch.setenv("BUNDLETOOL_PATH", str(bundletool))
    wrapper = tmp_path / "gradlew"
    wrapper.write_bytes(b"wrapper fixture")
    wrapper.chmod(0o755)
    (tmp_path / "demo.aab").write_bytes(b"bundle fixture")
    google = {
        "project_info": {"project_id": "demo-123456"},
        "client": [
            {
                "client_info": {
                    "mobilesdk_app_id": "1:123:android:abc",
                    "android_client_info": {"package_name": "com.demo"},
                }
            }
        ],
    }
    (tmp_path / "google.json").write_text(json.dumps(google))
    return FirebaseConfig(
        project_id="demo-123456",
        crashlytics={
            "apple": [
                {
                    "app_id": "1:123:ios:abc",
                    "bundle_id": "com.demo",
                    "version": "1.0.0",
                    "build_number": "7",
                    "configuration": "Google.plist",
                    "archive": "app.xcarchive",
                }
            ],
            "android": [
                {
                    "app_id": "1:123:android:abc",
                    "package_name": "com.demo",
                    "version_code": 7,
                    "configuration": "google.json",
                    "artifact": "demo.aab",
                    "gradle_wrapper": "gradlew",
                    "variant": "release",
                }
            ],
        },
    )


def process_output(command, **options):
    if command[0] == "xcrun":
        return SimpleNamespace(stdout=f"UUID: {UUID} (arm64) fixture")
    if command[0] == "java":
        return SimpleNamespace(
            stdout='<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.demo" android:versionCode="7"/>'
        )
    return SimpleNamespace(stdout="uploaded")


def test_symbols_preview_and_upload_validate_before_writes(symbol_project, tmp_path):
    calls = []

    def runner(command, **options):
        calls.append(command)
        return process_output(command, **options)

    publisher = CrashlyticsPublisher(ProcessHelper(runner))
    assert len(publisher.upload(symbol_project, tmp_path, apply=False)) == 2
    assert all(command[0] in {"xcrun", "java"} for command in calls)
    calls.clear()
    assert len(publisher.upload(symbol_project, tmp_path, apply=True)) == 2
    assert any(Path(command[0]).name == "upload-symbols" for command in calls)
    assert any("uploadCrashlyticsMappingFileRelease" in command for command in calls)
    symbol_project.crashlytics.android[0].upload_native = True
    assert publisher.upload(symbol_project, tmp_path, apply=True, provider="google")
    assert "uploadCrashlyticsSymbolFileRelease" in calls[-1]
    symbol_project.crashlytics.android[0].upload_mapping = False
    publisher.upload(symbol_project, tmp_path, apply=True, provider="google")
    assert "uploadCrashlyticsMappingFileRelease" not in calls[-1]
    assert len(publisher.upload(symbol_project, tmp_path, apply=False, provider="apple")) == 1
    symbol_project.crashlytics.apple.clear()
    symbol_project.crashlytics.android.clear()
    assert publisher.upload(symbol_project, tmp_path, apply=True) == []


def test_symbols_configuration_errors(symbol_project, tmp_path, monkeypatch):
    publisher = CrashlyticsPublisher(ProcessHelper(process_output))
    empty = FirebaseConfig(project_id="demo-123456")
    with pytest.raises(ConfigurationError, match="not configured"):
        publisher.upload(empty, tmp_path, apply=False)
    for key in ("GOOGLE_APP_ID", "BUNDLE_ID", "PROJECT_ID"):
        path = tmp_path / "Google.plist"
        original = path.read_bytes()
        info = plistlib.loads(original)
        info[key] = "wrong"
        path.write_bytes(plistlib.dumps(info))
        with pytest.raises(UnsafeOperationError, match="Apple Firebase"):
            publisher.upload(symbol_project, tmp_path, apply=True)
        path.write_bytes(original)
    monkeypatch.delenv("FIREBASE_UPLOAD_SYMBOLS_PATH")
    with pytest.raises(ConfigurationError, match="upload-symbols"):
        publisher.upload(symbol_project, tmp_path, apply=False, provider="apple")
    monkeypatch.setenv("FIREBASE_UPLOAD_SYMBOLS_PATH", str(tmp_path / "missing"))
    with pytest.raises(ConfigurationError):
        publisher.upload(symbol_project, tmp_path, apply=False, provider="apple")
    monkeypatch.setenv("FIREBASE_UPLOAD_SYMBOLS_PATH", str(tmp_path / "upload-symbols"))
    with monkeypatch.context() as context:
        context.setattr("app_publisher.providers.crashlytics_publisher.os.access", lambda *args: False)
        with pytest.raises(ConfigurationError):
            publisher.upload(symbol_project, tmp_path, apply=False, provider="apple")
    path = tmp_path / "google.json"
    original = path.read_text()
    for modifier in (
        lambda doc: doc.update(client=[]),
        lambda doc: doc["project_info"].update(project_id="wrong"),
        lambda doc: doc["client"][0]["client_info"]["android_client_info"].update(package_name="wrong"),
    ):
        doc = json.loads(original)
        modifier(doc)
        path.write_text(json.dumps(doc))
        with pytest.raises(UnsafeOperationError, match="Android Firebase"):
            publisher.upload(symbol_project, tmp_path, apply=True, provider="google")
    path.write_text(original)
    (tmp_path / "gradlew").unlink()
    with pytest.raises(ConfigurationError, match="Wrapper"):
        publisher.upload(symbol_project, tmp_path, apply=False, provider="google")
    (tmp_path / "gradlew").write_bytes(b"fixture")
    with monkeypatch.context() as context:
        context.setattr("app_publisher.providers.crashlytics_publisher.os.access", lambda *args: False)
        with pytest.raises(ConfigurationError):
            publisher.upload(symbol_project, tmp_path, apply=False, provider="google")


def test_symbol_models_reject_empty_duplicate_and_disabled(symbol_project):
    with pytest.raises(ValidationError, match="unique application"):
        CrashlyticsConfig()
    apple = symbol_project.crashlytics.apple[0]
    with pytest.raises(ValidationError, match="unique application"):
        CrashlyticsConfig(apple=[apple, apple])
    item = symbol_project.crashlytics.android[0].model_dump()
    item.update(upload_mapping=False, upload_native=False)
    with pytest.raises(ValidationError, match="at least one"):
        AndroidCrashlyticsSymbols(**item)
    assert AndroidCrashlyticsSymbols(**symbol_project.crashlytics.android[0].model_dump())


def test_configuration_reader_bounds_and_decoding(tmp_path):
    path = tmp_path / "config"
    with pytest.raises(ConfigurationError, match="missing"):
        ConfigurationFileHelper.read(path, apple=True)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ConfigurationError, match="size"):
        ConfigurationFileHelper.read(path, apple=False)
    for raw, apple in ((b"invalid", True), (b"invalid", False), (b"[]", False), (plistlib.dumps([]), True)):
        path.write_bytes(raw)
        with pytest.raises(ConfigurationError):
            ConfigurationFileHelper.read(path, apple=apple)


def test_process_failures_are_redacted(tmp_path):
    for error, expected in (
        (FileNotFoundError(), ConfigurationError),
        (subprocess.TimeoutExpired("tool", 1), UnsafeOperationError),
        (subprocess.CalledProcessError(1, "tool", stderr="SECRET"), UnsafeOperationError),
    ):

        def runner(*args, **kwargs):
            raise error

        with pytest.raises(expected) as caught:
            ProcessHelper(runner).run(["tool"], tmp_path)
        assert "SECRET" not in str(caught.value)


def test_android_artifact_identity_and_tool_errors(symbol_project, tmp_path, monkeypatch):
    helper = AndroidArtifactHelper(ProcessHelper(process_output))
    helper.verify_bundle(tmp_path, Path("demo.aab"), "com.demo", 7, "BUNDLETOOL_PATH")
    with pytest.raises(UnsafeOperationError, match="version code"):
        helper.verify_bundle(tmp_path, Path("demo.aab"), "com.demo", 8, "BUNDLETOOL_PATH")
    with pytest.raises(ConfigurationError, match="existing AAB"):
        helper.verify_bundle(tmp_path, Path("missing.aab"), "com.demo", 7, "BUNDLETOOL_PATH")
    with pytest.raises(ConfigurationError, match="existing AAB"):
        helper.verify_bundle(tmp_path, Path("demo.apk"), "com.demo", 7, "BUNDLETOOL_PATH")
    invalid = AndroidArtifactHelper(
        ProcessHelper(lambda *args, **kwargs: SimpleNamespace(stdout="invalid XML"))
    )
    with pytest.raises(ConfigurationError, match="manifest"):
        invalid.verify_bundle(tmp_path, Path("demo.aab"), "com.demo", 7, "BUNDLETOOL_PATH")
    monkeypatch.delenv("BUNDLETOOL_PATH")
    with pytest.raises(ConfigurationError, match="Bundletool"):
        helper.verify_bundle(tmp_path, Path("demo.aab"), "com.demo", 7, "BUNDLETOOL_PATH")
    monkeypatch.setenv("BUNDLETOOL_PATH", str(tmp_path / "missing.jar"))
    with pytest.raises(ConfigurationError):
        helper.verify_bundle(tmp_path, Path("demo.aab"), "com.demo", 7, "BUNDLETOOL_PATH")


def test_apple_uuid_and_archive_validation(symbol_project, tmp_path):
    item = symbol_project.crashlytics.apple[0]
    helper = AppleSymbolHelper(ProcessHelper(process_output))
    assert helper.verify(item, tmp_path).name == "dSYMs"
    framework = tmp_path / "app.xcarchive/Products/Applications/Demo.app/Frameworks/SDK.framework"
    framework.mkdir(parents=True)
    (framework / "SDK").write_bytes(b"framework fixture")
    (framework / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "SDK"}))
    assert helper.verify(item, tmp_path)
    missing = item.model_copy(update={"archive": Path("missing.xcarchive")})
    with pytest.raises(ConfigurationError, match="dSYMs"):
        helper.verify(missing, tmp_path)
    mismatch = item.model_copy(update={"build_number": "8"})
    with pytest.raises(UnsafeOperationError, match="identity"):
        helper.verify(mismatch, tmp_path)
    invalid = AppleSymbolHelper(ProcessHelper(lambda *args, **kwargs: SimpleNamespace(stdout="no UUID")))
    with pytest.raises(ConfigurationError, match="UUIDs"):
        invalid.verify(item, tmp_path)

    def wrong(command, **kwargs):
        value = OTHER_UUID if command[-1].endswith(".dSYM") else UUID
        return SimpleNamespace(stdout=f"UUID: {value} (arm64) fixture")

    with pytest.raises(UnsafeOperationError, match="does not belong"):
        AppleSymbolHelper(ProcessHelper(wrong)).verify(item, tmp_path)

    def incomplete(command, **kwargs):
        output = f"UUID: {UUID} (arm64) fixture"
        if not command[-1].endswith(".dSYM"):
            output += f"\nUUID: {OTHER_UUID} (arm64e) fixture"
        return SimpleNamespace(stdout=output)

    with pytest.raises(UnsafeOperationError, match="missing a required"):
        AppleSymbolHelper(ProcessHelper(incomplete)).verify(item, tmp_path)


def test_doctor_includes_symbol_tooling(project, symbol_project, tmp_path, monkeypatch):
    project.firebase = symbol_project
    environment = {
        "FIREBASE_UPLOAD_SYMBOLS_PATH": str(tmp_path / "upload-symbols"),
        "BUNDLETOOL_PATH": str(tmp_path / "bundletool.jar"),
    }
    doctor = EnvironmentDoctor(
        finder=lambda name: f"/tools/{name}", operating_system="Darwin", environment=environment
    )
    checks = {item.name: item for item in doctor.inspect(project, tmp_path)}
    assert checks["FIREBASE_UPLOAD_SYMBOLS_PATH"].status == "OK"
    assert checks["BUNDLETOOL_PATH"].status == "OK"
    assert checks["Crashlytics Gradle wrapper"].status == "OK"
    (tmp_path / "gradlew").unlink()
    checks = {item.name: item for item in doctor.inspect(project, tmp_path)}
    assert checks["Crashlytics Gradle wrapper"].status == "MISSING"
