import os
import platform
import shutil
from collections.abc import Callable
from pathlib import Path

from app_publisher.models.project_config import ProjectConfig
from app_publisher.toolchain.tool_check import ToolCheck


class EnvironmentDoctor:
    def __init__(
        self,
        finder: Callable[[str], str | None] = shutil.which,
        operating_system: str | None = None,
        environment: dict[str, str] | None = None,
    ):
        self.finder = finder
        self.operating_system = operating_system if operating_system is not None else platform.system()
        self.environment = environment if environment is not None else dict(os.environ)

    def executable(self, name: str) -> ToolCheck:
        location = self.finder(name)
        return ToolCheck(
            name, "OK" if location else "MISSING", location or f"Install {name} and add it to PATH"
        )

    def environment_file(self, name: str) -> ToolCheck:
        configured = self.environment.get(name)
        if not configured:
            return ToolCheck(name, "MISSING", "Required environment variable is not configured")
        path = Path(configured).expanduser()
        if not path.is_file():
            return ToolCheck(name, "MISSING", f"Configured file does not exist: {path}")
        return ToolCheck(name, "OK", "Credential file is present. Authorization has not been verified")

    def environment_secret(self, name: str) -> ToolCheck:
        return ToolCheck(
            name,
            "OK" if self.environment.get(name) else "MISSING",
            "Secret configured"
            if self.environment.get(name)
            else "Required environment variable is not configured",
        )

    def inspect(self, project: ProjectConfig, directory: Path) -> list[ToolCheck]:
        checks: list[ToolCheck] = []
        symbols = project.firebase.crashlytics if project.firebase else None
        apple_symbols = bool(symbols and symbols.apple)

        if symbols:
            for item in symbols.apple:
                checks.append(self.environment_file(item.upload_tool_env))
                checks.append(self.executable("xcrun"))

            for android in symbols.android:
                checks.append(self.environment_file(android.bundletool_env))
                checks.append(self.executable("java"))
                wrapper = directory / android.gradle_wrapper
                checks.append(
                    ToolCheck(
                        "Crashlytics Gradle wrapper", "OK" if wrapper.is_file() else "MISSING", str(wrapper)
                    )
                )
        native_apple = (
            any(version.build is not None for version in project.apple.versions) if project.apple else False
        )
        apple_simulators = any(
            plan.platform in {"ios", "tvos", "watchos", "visionos"}
            for plan in project.publication.screenshot_plans
        )
        mac_screenshots = any(plan.platform == "macos" for plan in project.publication.screenshot_plans)
        android_screenshots = any(plan.platform == "android" for plan in project.publication.screenshot_plans)
        native_android = bool(project.google and project.google.release and project.google.release.build)
        if project.apple and any(
            locale.apple and locale.apple.app_previews for locale in project.locales.values()
        ):
            checks.append(self.executable("ffprobe"))
        if project.apple:
            for name in [project.apple.key_id_env, project.apple.issuer_id_env]:
                checks.append(self.environment_secret(name))
            checks.append(self.environment_file(project.apple.private_key_path_env))
        if native_apple or apple_simulators or mac_screenshots or apple_symbols:
            checks.append(
                ToolCheck(
                    "macOS",
                    "OK" if self.operating_system == "Darwin" else "MISSING",
                    "Required for Apple native builds and simulator screenshots",
                )
            )
        if native_apple:
            for name in ["xcodebuild", "xcrun", "codesign", "security"]:
                checks.append(self.executable(name))
        if apple_simulators:
            checks.append(self.executable("xcrun"))
        if any(plan.driver == "idb" for plan in project.publication.screenshot_plans):
            checks.append(self.executable("idb"))
        if mac_screenshots:
            for name in ["open", "screencapture"]:
                checks.append(self.executable(name))
        if native_android:
            checks.append(self.executable("java"))
            build = project.google.release.build
            wrapper = directory / build.gradle_wrapper
            checks.append(ToolCheck("Gradle wrapper", "OK" if wrapper.is_file() else "MISSING", str(wrapper)))
            sdk = self.environment.get("ANDROID_HOME") or self.environment.get("ANDROID_SDK_ROOT")
            has_local_sdk = (wrapper.parent / "local.properties").is_file()
            if not sdk and not has_local_sdk:
                checks.append(
                    ToolCheck(
                        "Android SDK",
                        "UNVERIFIED",
                        "Set ANDROID_HOME or ANDROID_SDK_ROOT, or configure local.properties",
                    )
                )
            if sdk:
                checks.append(ToolCheck("Android SDK", "OK" if Path(sdk).is_dir() else "MISSING", sdk))
        if android_screenshots:
            checks.append(self.executable("adb"))
        if project.google or project.firebase:
            google_credentials = self.environment.get("GOOGLE_APPLICATION_CREDENTIALS")
            if google_credentials:
                checks.append(self.environment_file("GOOGLE_APPLICATION_CREDENTIALS"))
            else:
                checks.append(
                    ToolCheck(
                        "Google ADC",
                        "UNVERIFIED",
                        "Workload identity or local Application Default Credentials may be available, but were not verified offline",
                    )
                )
        return list({item.name: item for item in checks}.values())
