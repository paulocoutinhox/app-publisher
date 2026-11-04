import os
from pathlib import Path

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.firebase_config import FirebaseConfig
from app_publisher.toolchain.android_artifact_helper import AndroidArtifactHelper
from app_publisher.toolchain.apple_symbol_helper import AppleSymbolHelper
from app_publisher.toolchain.configuration_file_helper import ConfigurationFileHelper
from app_publisher.toolchain.process_helper import ProcessHelper


class CrashlyticsPublisher:
    def __init__(self, process: ProcessHelper | None = None):
        self.process = process if process is not None else ProcessHelper()

    def upload(
        self, config: FirebaseConfig, directory: Path, *, apply: bool, provider: str = "all"
    ) -> list[str]:
        if config.crashlytics is None:
            raise ConfigurationError("Firebase Crashlytics symbols are not configured")

        operations: list[tuple[list[str], int]] = []
        changes: list[str] = []

        if provider in {"all", "apple"}:
            for item in config.crashlytics.apple:
                settings = project_path(directory, item.configuration)
                info = ConfigurationFileHelper.read(settings, apple=True)

                if (info.get("GOOGLE_APP_ID"), info.get("BUNDLE_ID"), info.get("PROJECT_ID")) != (
                    item.app_id,
                    item.bundle_id,
                    config.project_id,
                ):
                    raise UnsafeOperationError("The Apple Firebase configuration does not match the YAML")

                tool = os.environ.get(item.upload_tool_env)

                if not tool or not Path(tool).is_file() or not os.access(tool, os.X_OK):
                    raise ConfigurationError(
                        f"Configure {item.upload_tool_env} with Firebase's upload-symbols tool"
                    )

                symbols = AppleSymbolHelper(self.process).verify(item, directory)
                operations.append(
                    ([tool, "-gsp", str(settings), "-p", item.platform, str(symbols)], item.timeout_seconds)
                )
                changes.append(
                    f"Crashlytics Apple: upload verified dSYMs for {item.bundle_id} ({item.build_number})"
                )

        if provider in {"all", "google"}:
            for android in config.crashlytics.android:
                configuration = project_path(directory, android.configuration)
                google = ConfigurationFileHelper.read(configuration, apple=False)
                clients = [
                    client
                    for client in google.get("client", [])
                    if client.get("client_info", {}).get("mobilesdk_app_id") == android.app_id
                ]

                if len(clients) != 1 or google.get("project_info", {}).get("project_id") != config.project_id:
                    raise UnsafeOperationError("The Android Firebase app or project does not match the YAML")

                actual_package = clients[0]["client_info"].get("android_client_info", {}).get("package_name")

                if actual_package != android.package_name:
                    raise UnsafeOperationError("The Android Firebase package does not match the YAML")

                AndroidArtifactHelper(self.process).verify_bundle(
                    directory,
                    android.artifact,
                    android.package_name,
                    android.version_code,
                    android.bundletool_env,
                )
                wrapper = project_path(directory, android.gradle_wrapper)

                if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
                    raise ConfigurationError("Crashlytics requires an executable Gradle Wrapper")

                variant = android.variant[0].upper() + android.variant[1:]
                tasks = []

                if android.upload_mapping:
                    tasks.append(f"uploadCrashlyticsMappingFile{variant}")

                if android.upload_native:
                    tasks.append(f"uploadCrashlyticsSymbolFile{variant}")

                command = [str(wrapper), "--project-dir", str(wrapper.parent), *tasks, "--no-daemon"]
                operations.append((command, android.timeout_seconds))
                changes.append(
                    f"Crashlytics Android: upload symbols for {android.package_name} ({android.version_code})"
                )

        if apply:
            for command, timeout in operations:
                self.process.run(command, directory, timeout=timeout)

        return changes
