from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.models.android_build import AndroidBuild
from app_publisher.models.apple_build import AppleBuild
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.toolchain.environment_doctor import EnvironmentDoctor


def test_doctor_minimal_and_secrets(project, tmp_path):
    secret = tmp_path / "private.p8"
    secret.write_text("demo")

    def finder(name):
        return (
            f"/usr/bin/{name}"
            if name in {"java", "adb", "open", "screencapture", "xcrun", "xcodebuild", "codesign", "security"}
            else None
        )

    environment = {
        "APP_STORE_KEY_ID": "TESTKEY",
        "APP_STORE_ISSUER_ID": "issuer",
        "APP_STORE_KEY_PATH": str(secret),
        "GOOGLE_APPLICATION_CREDENTIALS": str(secret),
    }
    doctor = EnvironmentDoctor(finder, operating_system="Darwin", environment=environment)
    checks = doctor.inspect(project, tmp_path)
    assert [(check.name, check.status) for check in checks] == [
        ("APP_STORE_KEY_ID", "OK"),
        ("APP_STORE_ISSUER_ID", "OK"),
        ("APP_STORE_KEY_PATH", "OK"),
        ("GOOGLE_APPLICATION_CREDENTIALS", "OK"),
    ]
    assert doctor.executable("not-found").status == "MISSING"
    assert doctor.environment_secret("not-found").status == "MISSING"
    assert doctor.environment_file("not-found").status == "MISSING"
    doctor.environment["APP_STORE_KEY_PATH"] = "missing"
    assert doctor.environment_file("APP_STORE_KEY_PATH").status == "MISSING"
    assert doctor.inspect(project, tmp_path)[2].status == "MISSING"


def test_doctor_native_toolchains_and_screenshots(project, tmp_path):
    project.apple.versions[0].build = AppleBuild(
        project="app.xcodeproj",
        scheme="App",
        archive_path="archive",
        export_path="export",
        export_options="export.plist",
    )
    project.google.release.build = AndroidBuild(gradle_wrapper="gradlew", artifact="app.aab")
    project.publication.screenshot_plans = [
        ScreenshotPlan(
            platform=platform,
            device="device",
            scenes=[{"name": "home", "url": "myapp://home", "output": f"{platform}.png"}],
        )
        for platform in ["ios", "android", "macos"]
    ]
    doctor = EnvironmentDoctor(lambda name: f"/bin/{name}", operating_system="Linux", environment={})
    checks = {check.name: check for check in doctor.inspect(project, tmp_path)}
    assert checks["macOS"].status == "MISSING"
    assert checks["xcrun"].status == "OK"
    assert checks["adb"].status == "OK"
    assert checks["Gradle wrapper"].status == "MISSING"
    assert checks["Android SDK"].status == "UNVERIFIED"
    assert checks["Google ADC"].status == "UNVERIFIED"
    assert len(checks) == len(doctor.inspect(project, tmp_path))
    (tmp_path / "gradlew").write_text("gradle")
    (tmp_path / "local.properties").write_text("sdk.dir=/usr/local/android")
    doctor.operating_system = "Darwin"
    assert {check.name: check for check in doctor.inspect(project, tmp_path)}["Gradle wrapper"].status == "OK"
    doctor.environment["ANDROID_HOME"] = str(tmp_path)
    assert {check.name: check for check in doctor.inspect(project, tmp_path)}["Android SDK"].status == "OK"
    doctor.environment["ANDROID_HOME"] = "/path/that/does/not/exist"
    assert {check.name: check for check in doctor.inspect(project, tmp_path)}[
        "Android SDK"
    ].status == "MISSING"
    doctor.operating_system = "Linux"
    assert {check.name: check for check in doctor.inspect(project, tmp_path)}["macOS"].status == "MISSING"


def test_doctor_full_cli(project, tmp_path, monkeypatch):
    config = tmp_path / "app.yaml"
    monkeypatch.setattr(
        "app_publisher.cli.open_engine", lambda config: PublicationEngine(project, tmp_path / "app.yaml")
    )
    monkeypatch.setattr(
        "app_publisher.cli.EnvironmentDoctor",
        lambda: EnvironmentDoctor(lambda name: None, operating_system="Linux", environment={}),
    )
    response = CliRunner().invoke(app, ["doctor-full", str(config)])
    assert response.exit_code == 1
    assert "MISSING" in response.stdout
    monkeypatch.setattr(
        "app_publisher.cli.EnvironmentDoctor",
        lambda: EnvironmentDoctor(
            lambda name: "/usr/bin/" + name,
            operating_system="Darwin",
            environment={
                "APP_STORE_KEY_ID": "key",
                "APP_STORE_ISSUER_ID": "issuer",
                "APP_STORE_KEY_PATH": str(tmp_path / "key.p8"),
            },
        ),
    )
    (tmp_path / "key.p8").write_text("key")
    response = CliRunner().invoke(app, ["doctor-full", str(config)])
    assert response.exit_code == 0
    assert "UNVERIFIED" in response.stdout


def test_doctor_with_no_providers_or_native_tools(project, tmp_path):
    empty = project.model_copy(update={"apple": None, "google": None, "firebase": None})
    assert (
        EnvironmentDoctor(lambda name: None, operating_system="Linux", environment={}).inspect(
            empty, tmp_path
        )
        == []
    )
