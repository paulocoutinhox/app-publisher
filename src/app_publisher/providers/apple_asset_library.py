import hashlib
import time
from pathlib import Path
from typing import Any

from PIL import Image

from app_publisher.core.api_client import APIClient
from app_publisher.core.assets import resolve_assets
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper


class AppleAssetLibrary:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def library_id(self) -> str:
        return self.api.request("GET", f"apps/{self.app_id}/assetLibrary")["data"]["id"]

    def reference_data(self) -> dict[str, Any]:
        result = self.api.request(
            "GET", "appAssetLibraryRefData", params={"filter[features]": "APP_STORE_VERSIONS"}
        )
        data = result.get("data", [])
        if len(data) != 1:
            raise RemoteAPIError("Expected exactly one Apple App Asset Library reference record")
        return data[0]["attributes"]

    @staticmethod
    def resolve_group(identifier: str, reference: dict[str, Any]) -> str:
        groups = reference["placementProfileGroups"]
        known = {item["placementProfileGroupId"] for item in groups}
        if identifier in known:
            return identifier
        matching = [
            item["placementProfileGroupId"] for item in groups if item["displayClassId"] == identifier
        ]
        if len(matching) != 1:
            raise ConfigurationError(
                f"Unknown or ambiguous Apple placement group: {identifier}. Use an exact placementProfileGroupId from 'app_publisher devices'."
            )
        return matching[0]

    @staticmethod
    def validate_dimensions(path: Path, group: str, reference: dict[str, Any]) -> None:
        placement = next(
            (item for item in reference["placementTypes"] if item["placementTypeId"] == "APP_SCREENSHOT"),
            None,
        )
        if placement is None:
            raise RemoteAPIError("Apple reference data does not describe APP_SCREENSHOT placements")
        mapping = next(
            (item for item in placement["specMappings"] if item["placementGroupId"] == group), None
        )
        if mapping is None:
            raise ConfigurationError(f"Apple placement group {group} does not accept APP_SCREENSHOT")
        specs = [item for item in reference["imageSpecs"] if item["specId"] in mapping["specs"]]
        with Image.open(path) as opened:
            width, height = opened.size
        compatible = [
            spec
            for spec in specs
            if spec["dimensions"]["minWidth"] <= width <= spec["dimensions"]["maxWidth"]
            and spec["dimensions"]["minHeight"] <= height <= spec["dimensions"]["maxHeight"]
            and path.suffix.lower() in spec["fileExtensions"]
            and path.stat().st_size <= spec["maxFileSize"]
        ]
        if not compatible:
            raise ConfigurationError(
                f"Screenshot {path} does not match Apple reference dimensions and formats for {group}"
            )

    @staticmethod
    def reference_name(path: Path) -> str:
        return f"app-publisher-{hashlib.sha256(path.read_bytes()).hexdigest()}"

    def synchronize(
        self,
        localization_id: str,
        groups: dict[str, list[str]],
        directory: Path,
        confirm_replacement: bool = False,
    ) -> list[str]:
        reference = self.reference_data()
        library = self.library_id()
        existing = self.api.paginated(
            f"appStoreVersionLocalizations/{localization_id}/placements",
            params={"filter[placementType]": "APP_SCREENSHOT", "include": "image", "limit": 200},
        )
        changes: list[str] = []
        for key, patterns in groups.items():
            group = self.resolve_group(key, reference)
            paths = resolve_assets(directory, patterns)
            for path in paths:
                self.validate_dimensions(path, group, reference)
            current = [item for item in existing if item["attributes"]["placementGroup"] == group]
            desired_names = [self.reference_name(path) for path in paths]
            current_names = [
                self.api.request(
                    "GET", f"appAssetLibraryImages/{item['relationships']['image']['data']['id']}"
                )["data"]["attributes"].get("referenceName")
                for item in current
            ]
            if current_names == desired_names:
                continue
            if current and not confirm_replacement:
                raise UnsafeOperationError(
                    f"Apple {group}: replacing existing screenshots requires apple.confirm_asset_replacement: true"
                )
            image_ids = [self.ensure_image(library, path) for path in paths]
            for item in current:
                self.api.request("DELETE", f"appAssetLibraryPlacements/{item['id']}")
            placement_ids = [
                self.create_placement(localization_id, group, image_id) for image_id in image_ids
            ]
            self.order(localization_id, group, placement_ids)
            changes.append(f"Apple {group}: synchronized {len(placement_ids)} screenshots")
        return changes

    def ensure_image(self, library: str, path: Path) -> str:
        name = self.reference_name(path)
        existing = self.api.paginated(
            f"appAssetLibraries/{library}/images", params={"filter[referenceName]": name, "limit": 200}
        )
        for image in existing:
            if image["attributes"].get("referenceName") == name:
                self.wait_image(image["id"])
                return image["id"]
        binary = path.read_bytes()
        payload = {
            "data": {
                "type": "appAssetLibraryImages",
                "attributes": {
                    "fileName": path.name,
                    "fileSize": len(binary),
                    "category": "APP_SCREENSHOTS_AND_PREVIEWS",
                    "referenceName": name,
                },
                "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": library}}},
            }
        }
        created = self.api.request("POST", "appAssetLibraryImages", payload=payload)["data"]
        AppleAssetUploadHelper.upload_parts(self.api, created["attributes"]["uploadOperations"], binary)
        image_id = created["id"]
        self.api.request(
            "PATCH",
            f"appAssetLibraryImages/{image_id}",
            payload={
                "data": {"type": "appAssetLibraryImages", "id": image_id, "attributes": {"uploaded": True}}
            },
        )
        self.wait_image(image_id)
        return image_id

    def wait_image(self, image_id: str) -> None:
        for attempt in range(30):
            result = self.api.request("GET", f"appAssetLibraryImages/{image_id}")["data"]
            state = result["attributes"]["state"]
            if state in {"PREPARE_FOR_SUBMISSION", "APPROVED"}:
                return
            if state == "FAILED":
                raise RemoteAPIError(
                    f"Apple image processing failed: {result['attributes'].get('stateDetails')}"
                )
            if state not in {"UPLOAD_COMPLETE", "AWAITING_UPLOAD"}:
                raise RemoteAPIError(f"Unexpected Apple image state: {state}")
            if attempt < 29:
                time.sleep(2)
        raise RemoteAPIError("Apple image processing timed out")

    def create_placement(self, localization_id: str, group: str, image_id: str) -> str:
        payload = {
            "data": {
                "type": "appAssetLibraryPlacements",
                "attributes": {"placementType": "APP_SCREENSHOT", "placementGroup": group},
                "relationships": {
                    "image": {"data": {"type": "appAssetLibraryImages", "id": image_id}},
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                    },
                },
            }
        }
        return self.api.request("POST", "appAssetLibraryPlacements", payload=payload)["data"]["id"]

    def order(self, localization_id: str, group: str, placement_ids: list[str]) -> None:
        payload = {
            "data": {
                "type": "appAssetLibraryPlacementOrderingRequests",
                "attributes": {"placementGroup": group},
                "relationships": {
                    "orderedPlacements": {
                        "data": [{"type": "appAssetLibraryPlacements", "id": item} for item in placement_ids]
                    },
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                    },
                },
            }
        }
        self.api.request("POST", "appAssetLibraryPlacementOrderingRequests", payload=payload)
