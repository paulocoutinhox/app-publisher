import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.android_build import AndroidBuild
from app_publisher.models.apple_build import AppleBuild


class BuildRunner:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run):
        self.runner = runner

    def execute(self, command: list[str], directory: Path) -> None:
        try:
            self.runner(command, cwd=directory, check=True, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise ConfigurationError(f"Required build tool is missing: {command[0]}") from error
        except subprocess.CalledProcessError as error:
            raise UnsafeOperationError(
                f"Build command failed: {Path(command[0]).name} (exit {error.returncode}). Output is hidden to protect credentials"
            ) from None

    def apple(self, build: AppleBuild, directory: Path) -> Path:
        for command in build.prepare_commands:
            self.execute([command.executable, *command.arguments], directory)

        container = (
            ["-workspace", str(build.workspace)] if build.workspace else ["-project", str(build.project)]
        )
        archive = project_path(directory, build.archive_path)
        export = project_path(directory, build.export_path)
        options = project_path(directory, build.export_options)
        if not options.is_file():
            raise ConfigurationError(f"Missing export options: {build.export_options}")
        provisioning = ["-allowProvisioningUpdates"] if build.allow_provisioning_updates else []
        settings = [f"{name}={value}" for name, value in sorted(build.build_settings.items())]

        self.execute(
            [
                "xcodebuild",
                *container,
                *provisioning,
                *settings,
                "-scheme",
                build.scheme,
                "-configuration",
                build.configuration,
                "-destination",
                build.destination,
                "-archivePath",
                str(archive),
                "archive",
            ],
            directory,
        )
        self.execute(
            [
                "xcodebuild",
                "-exportArchive",
                *provisioning,
                "-archivePath",
                str(archive),
                "-exportPath",
                str(export),
                "-exportOptionsPlist",
                str(options),
            ],
            directory,
        )
        return export

    def android(self, build: AndroidBuild, directory: Path) -> Path:
        for command in build.prepare_commands:
            self.execute([command.executable, *command.arguments], directory)

        wrapper = project_path(directory, build.gradle_wrapper)
        if not wrapper.is_file():
            raise ConfigurationError(f"Gradle wrapper is missing: {build.gradle_wrapper}")
        if not os.access(wrapper, os.X_OK):
            raise ConfigurationError(f"Gradle wrapper is not executable: {build.gradle_wrapper}")
        self.execute(
            [
                str(wrapper.resolve()),
                "--project-dir",
                str(wrapper.parent.resolve()),
                build.task,
                "--no-daemon",
            ],
            directory,
        )
        for command in build.finish_commands:
            self.execute([command.executable, *command.arguments], directory)

        artifact = project_path(directory, build.artifact)
        if not artifact.is_file():
            raise ConfigurationError(f"Android build did not produce the expected artifact: {build.artifact}")
        return artifact
