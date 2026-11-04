import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.core.assets import resolve_files
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper


class AppleAppPreviews:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.assets = AppleAssetLibrary(api, app_id)

    @staticmethod
    def reference_name(path: Path, timecode: str | None) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update((timecode or "").encode())
        return f"app-publisher-preview-{digest.hexdigest()}"

    @staticmethod
    def inspect_video(path: Path) -> dict[str, Any]:
        if shutil.which("ffprobe") is None:
            raise ConfigurationError("ffprobe is required to validate Apple App Previews")
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ConfigurationError(f"Video inspection failed for {path}: {result.stderr.strip()}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"ffprobe returned invalid JSON for {path}") from error

    @staticmethod
    def validate_video(path: Path, group: str, reference: dict[str, Any], inspection: dict[str, Any]) -> None:
        placement = next(
            (item for item in reference["placementTypes"] if item["placementTypeId"] == "APP_PREVIEW"), None
        )
        if placement is None:
            raise RemoteAPIError("Apple reference data does not describe APP_PREVIEW placements")
        mapping = next(
            (item for item in placement["specMappings"] if item["placementGroupId"] == group), None
        )
        if mapping is None:
            raise ConfigurationError(f"Apple placement group {group} does not accept APP_PREVIEW")
        streams = inspection.get("streams", [])
        videos = [item for item in streams if item.get("codec_type") == "video"]
        if len(videos) != 1:
            raise ConfigurationError(f"App Preview must have exactly one video stream: {path}")
        video = videos[0]
        audio = any(item.get("codec_type") == "audio" for item in streams)
        duration = float(inspection.get("format", {}).get("duration", "0"))
        fraction = video.get("avg_frame_rate", "0/1").split("/")
        if len(fraction) != 2 or float(fraction[1]) == 0:
            raise ConfigurationError(f"App Preview has an invalid frame rate: {path}")
        fps = float(fraction[0]) / float(fraction[1])
        for spec in reference["videoSpecs"]:
            if spec["specId"] not in mapping["specs"]:
                continue
            dimensions = spec["dimensions"]
            if not (
                dimensions["minWidth"] <= video["width"] <= dimensions["maxWidth"]
                and dimensions["minHeight"] <= video["height"] <= dimensions["maxHeight"]
            ):
                continue
            if path.suffix.lower() not in spec["fileExtensions"] or path.stat().st_size > spec["maxFileSize"]:
                continue
            if spec.get("audioRequired", False) and not audio:
                continue
            if spec.get("frameRates") and not any(
                item["minFps"] <= fps <= item["maxFps"] for item in spec["frameRates"]
            ):
                continue
            limits = spec.get("duration", {})
            minimum = float(limits.get("min", "PT0S").removeprefix("PT").removesuffix("S"))
            maximum = float(limits.get("max", "PT99999S").removeprefix("PT").removesuffix("S"))
            if minimum <= duration <= maximum:
                return
        raise ConfigurationError(f"App Preview does not meet the Apple specifications for {group}: {path}")

    def ensure_video(self, library: str, path: Path, timecode: str | None) -> str:
        name = self.reference_name(path, timecode)
        remote = self.api.paginated(
            f"appAssetLibraries/{library}/videos", params={"filter[referenceName]": name, "limit": 200}
        )
        for item in remote:
            if item["attributes"].get("referenceName") == name:
                self.wait_video(item["id"])
                return item["id"]
        attributes = {
            "fileName": path.name,
            "fileSize": path.stat().st_size,
            "category": "APP_SCREENSHOTS_AND_PREVIEWS",
            "referenceName": name,
        }
        if timecode is not None:
            attributes["previewFrameTimeCode"] = timecode
        body = {
            "data": {
                "type": "appAssetLibraryVideos",
                "attributes": attributes,
                "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": library}}},
            }
        }
        record = self.api.request("POST", "appAssetLibraryVideos", payload=body)["data"]
        AppleAssetUploadHelper.upload_parts(self.api, record["attributes"]["uploadOperations"], path)
        self.api.request(
            "PATCH",
            f"appAssetLibraryVideos/{record['id']}",
            payload={
                "data": {
                    "type": "appAssetLibraryVideos",
                    "id": record["id"],
                    "attributes": {"uploaded": True},
                }
            },
        )
        self.wait_video(record["id"])
        return record["id"]

    def wait_video(self, identifier: str) -> None:
        for attempt in range(30):
            resource = self.api.request("GET", f"appAssetLibraryVideos/{identifier}")["data"]
            state = resource["attributes"]["state"]
            if state in {"PREPARE_FOR_SUBMISSION", "APPROVED"}:
                return
            if state == "FAILED":
                raise RemoteAPIError(
                    f"Apple App Preview processing failed: {resource['attributes'].get('stateDetails')}"
                )
            if state not in {"UPLOAD_COMPLETE", "AWAITING_UPLOAD"}:
                raise RemoteAPIError(f"Unexpected Apple App Preview state: {state}")
            if attempt < 29:
                time.sleep(2)
        raise RemoteAPIError("Apple App Preview processing timed out")

    def synchronize(
        self,
        localization_id: str,
        groups: dict[str, list[str]],
        directory: Path,
        timecode: str | None = None,
        confirm_replacement: bool = False,
    ) -> list[str]:
        reference = self.assets.reference_data()
        library = self.assets.library_id()
        existing = self.api.paginated(
            f"appStoreVersionLocalizations/{localization_id}/placements",
            params={"filter[placementType]": "APP_PREVIEW", "include": "video", "limit": 200},
        )
        changes: list[str] = []
        for key, patterns in groups.items():
            group = self.assets.resolve_group(key, reference)
            paths = resolve_files(directory, patterns)
            for path in paths:
                self.validate_video(path, group, reference, self.inspect_video(path))
            desired = [self.reference_name(path, timecode) for path in paths]
            current = [item for item in existing if item["attributes"]["placementGroup"] == group]
            names = [
                self.api.request(
                    "GET", f"appAssetLibraryVideos/{item['relationships']['video']['data']['id']}"
                )["data"]["attributes"].get("referenceName")
                for item in current
            ]
            if names == desired:
                continue
            if current and not confirm_replacement:
                raise UnsafeOperationError(
                    f"Apple {group}: replacing existing previews requires apple.confirm_asset_replacement: true"
                )
            ids = [self.ensure_video(library, path, timecode) for path in paths]
            for placement in current:
                self.api.request("DELETE", f"appAssetLibraryPlacements/{placement['id']}")
            placements = []
            for identifier in ids:
                payload = {
                    "data": {
                        "type": "appAssetLibraryPlacements",
                        "attributes": {"placementType": "APP_PREVIEW", "placementGroup": group},
                        "relationships": {
                            "video": {"data": {"type": "appAssetLibraryVideos", "id": identifier}},
                            "appStoreVersionLocalization": {
                                "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                            },
                        },
                    }
                }
                placements.append(
                    self.api.request("POST", "appAssetLibraryPlacements", payload=payload)["data"]["id"]
                )
            body = {
                "data": {
                    "type": "appAssetLibraryPlacementOrderingRequests",
                    "attributes": {"placementGroup": group},
                    "relationships": {
                        "orderedPlacements": {
                            "data": [{"type": "appAssetLibraryPlacements", "id": item} for item in placements]
                        },
                        "appStoreVersionLocalization": {
                            "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                        },
                    },
                }
            }
            self.api.request("POST", "appAssetLibraryPlacementOrderingRequests", payload=body)
            changes.append(f"Apple {group}: synchronized {len(placements)} App Previews")
        return changes
