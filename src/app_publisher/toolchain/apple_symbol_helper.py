import re
from pathlib import Path

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_crashlytics_symbols import AppleCrashlyticsSymbols
from app_publisher.toolchain.configuration_file_helper import ConfigurationFileHelper
from app_publisher.toolchain.process_helper import ProcessHelper


class AppleSymbolHelper:
    def __init__(self, process: ProcessHelper):
        self.process = process

    def uuids(self, path: Path, directory: Path) -> set[tuple[str, str]]:
        output = self.process.run(["xcrun", "dwarfdump", "--uuid", str(path)], directory)
        matches = re.findall(r"UUID: ([A-Fa-f0-9-]{36}) \(([^)]+)\)", output)

        if not matches:
            raise ConfigurationError("No Mach-O UUIDs were found in a required symbol artifact")

        return {(uuid.upper(), architecture) for uuid, architecture in matches}

    def verify(self, item: AppleCrashlyticsSymbols, directory: Path) -> Path:
        archive = project_path(directory, item.archive)
        applications = sorted((archive / "Products/Applications").glob("*.app"))
        symbols = sorted((archive / "dSYMs").glob("*.dSYM"))

        if len(applications) != 1 or not symbols:
            raise ConfigurationError("The archive must contain one application and its dSYMs")

        app = applications[0]
        info = ConfigurationFileHelper.read(app / "Info.plist", apple=True)
        actual = (
            info.get("CFBundleIdentifier"),
            info.get("CFBundleShortVersionString"),
            info.get("CFBundleVersion"),
        )

        if actual != (item.bundle_id, item.version, item.build_number):
            raise UnsafeOperationError("The Apple archive identity, version or build does not match the YAML")

        binary = project_path(directory, (app / info["CFBundleExecutable"]).relative_to(directory))
        required = self.uuids(binary, directory)
        known = set(required)

        for framework in sorted(app.rglob("*.framework")):
            metadata = ConfigurationFileHelper.read(framework / "Info.plist", apple=True)
            executable = project_path(
                directory, (framework / metadata["CFBundleExecutable"]).relative_to(directory)
            )
            known.update(self.uuids(executable, directory))

        available: set[tuple[str, str]] = set()

        for symbol in symbols:
            checked = project_path(directory, symbol.relative_to(directory))
            identities = self.uuids(checked, directory)

            if not identities.issubset(known):
                raise UnsafeOperationError(
                    "A dSYM UUID or architecture does not belong to the archived binaries"
                )

            available.update(identities)

        if not required.issubset(available):
            raise UnsafeOperationError("The application dSYM is missing a required UUID or architecture")

        return archive / "dSYMs"
