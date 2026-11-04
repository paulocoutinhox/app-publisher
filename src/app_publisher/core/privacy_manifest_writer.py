import os
import plistlib
import tempfile
from pathlib import Path

from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_privacy_manifest import ApplePrivacyManifest


class PrivacyManifestWriter:
    @staticmethod
    def document(config: ApplePrivacyManifest) -> dict[str, object]:
        return {
            "NSPrivacyTracking": config.tracking,
            "NSPrivacyTrackingDomains": config.tracking_domains,
            "NSPrivacyCollectedDataTypes": [
                {
                    "NSPrivacyCollectedDataType": item.data_type,
                    "NSPrivacyCollectedDataTypeLinked": item.linked,
                    "NSPrivacyCollectedDataTypeTracking": item.tracking,
                    "NSPrivacyCollectedDataTypePurposes": item.purposes,
                }
                for item in config.collected_data
            ],
            "NSPrivacyAccessedAPITypes": [
                {"NSPrivacyAccessedAPIType": item.category, "NSPrivacyAccessedAPITypeReasons": item.reasons}
                for item in config.accessed_apis
            ],
        }

    @staticmethod
    def destination(config: ApplePrivacyManifest, directory: Path) -> Path:
        root = directory.resolve()
        target = (root / config.output).resolve()
        if target == root or root not in target.parents or target.suffix != ".xcprivacy":
            raise UnsafeOperationError(
                "PrivacyInfo.xcprivacy output must be an .xcprivacy file inside the project directory"
            )
        if target.is_dir():
            raise UnsafeOperationError("Privacy manifest output cannot be a directory")
        return target

    def synchronize(self, config: ApplePrivacyManifest, directory: Path, *, apply: bool) -> list[str]:
        target = self.destination(config, directory)
        rendered = plistlib.dumps(self.document(config), fmt=plistlib.FMT_XML, sort_keys=True)
        if target.is_file() and target.read_bytes() == rendered:
            return []
        changes = [f"Apple privacy manifest: update {config.output.as_posix()}"]
        if not apply:
            return changes
        target.parent.mkdir(parents=True, exist_ok=True)
        staging_file = tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".app-publisher-", delete=False
        )
        staged = Path(staging_file.name)
        try:
            with staging_file as output:
                output.write(rendered)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(staged, 0o644)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        return changes
