import os
import xml.etree.ElementTree as ET
from pathlib import Path

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.toolchain.process_helper import ProcessHelper


class AndroidArtifactHelper:
    def __init__(self, process: ProcessHelper):
        self.process = process

    def verify_bundle(
        self, directory: Path, artifact: Path, package: str, version: int, bundletool_env: str
    ) -> None:
        path = project_path(directory, artifact)
        tool = os.environ.get(bundletool_env)

        if not tool or not Path(tool).is_file():
            raise ConfigurationError(f"Configure {bundletool_env} with the official Bundletool JAR")

        if path.suffix != ".aab" or not path.is_file():
            raise ConfigurationError("Android symbol verification requires an existing AAB")

        manifest = self.process.run(["java", "-jar", tool, "dump", "manifest", f"--bundle={path}"], directory)

        try:
            document = ET.fromstring(manifest)
        except ET.ParseError:
            raise ConfigurationError("Bundletool returned an invalid Android manifest") from None

        actual = (
            document.get("package"),
            document.get("{http://schemas.android.com/apk/res/android}versionCode"),
        )

        if actual != (package, str(version)):
            raise UnsafeOperationError("Android artifact package or version code does not match the YAML")
