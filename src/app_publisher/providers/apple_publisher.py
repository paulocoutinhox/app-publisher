from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_config import AppleConfig
from app_publisher.models.apple_metadata import AppleMetadata
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.project_config import ProjectConfig
from app_publisher.providers.apple_app_previews import AppleAppPreviews
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper


class ApplePublisher:
    def __init__(self, client: APIClient, config: AppleConfig):
        self.api = client
        self.config = config

    def identify(self) -> dict[str, Any]:
        app = self.api.request("GET", f"apps/{self.config.app_id}")["data"]
        if app["attributes"]["bundleId"] != self.config.bundle_id:
            raise UnsafeOperationError("The Apple app ID does not match the configured bundle identifier")
        return app

    def versions(self) -> list[dict[str, Any]]:
        return self.api.paginated(
            f"apps/{self.config.app_id}/appStoreVersions",
            params={
                "limit": 200,
                "fields[appStoreVersions]": "platform,versionString,appVersionState,releaseType,earliestReleaseDate",
            },
        )

    def ensure_version(
        self, version: AppleVersion, existing: list[dict[str, Any]], *, apply: bool
    ) -> str | None:
        matching = [
            resource
            for resource in existing
            if resource["attributes"]["platform"] == version.platform
            and resource["attributes"]["versionString"] == version.version
        ]
        if matching:
            state = matching[0]["attributes"].get("appVersionState", "")
            if state not in {
                "PREPARE_FOR_SUBMISSION",
                "DEVELOPER_REJECTED",
                "REJECTED",
                "METADATA_REJECTED",
                "WAITING_FOR_REVIEW",
                "IN_REVIEW",
            }:
                raise UnsafeOperationError(f"Apple version {version.version} is not editable: {state}")
            if state in {"WAITING_FOR_REVIEW", "IN_REVIEW"}:
                raise UnsafeOperationError("Apple version is under review. Changes are intentionally blocked")
            return matching[0]["id"]
        if not apply:
            return None
        if version.release_type == "SCHEDULED" and version.earliest_release_date is None:
            raise ConfigurationError("Scheduled Apple releases require earliest_release_date")
        self.validate_future_release(version)
        body = {
            "data": {
                "type": "appStoreVersions",
                "attributes": {
                    "platform": version.platform,
                    "versionString": version.version,
                    "releaseType": version.release_type,
                    **(
                        {"earliestReleaseDate": version.earliest_release_date}
                        if version.earliest_release_date is not None
                        else {}
                    ),
                },
                "relationships": {"app": {"data": {"type": "apps", "id": self.config.app_id}}},
            }
        }
        return self.api.request("POST", "appStoreVersions", payload=body)["data"]["id"]

    def synchronize(self, project: ProjectConfig, directory: Path, *, apply: bool) -> list[str]:
        self.identify()
        existing = self.versions()
        changes: list[str] = []
        changes.extend(self.sync_app_information(project, apply=apply))
        for version in self.config.versions:
            matching = next(
                (
                    item
                    for item in existing
                    if item["attributes"]["platform"] == version.platform
                    and item["attributes"]["versionString"] == version.version
                ),
                None,
            )
            if matching is not None:
                changes.extend(self.synchronize_version_settings(version, matching, apply=apply))
            identifier = self.ensure_version(version, existing, apply=apply)
            changes.append(
                f"Apple {version.platform} {version.version}: {'ready' if identifier else 'create version'}"
            )
            if identifier is None:
                for locale, localized in project.locales.items():
                    if localized.apple is None:
                        continue
                    if self.version_fields(
                        localized.common.description, localized.common.release_notes, localized.apple
                    ):
                        changes.append(f"Apple {version.platform} {locale}: create localization")
                    if localized.apple.screenshots:
                        changes.append(
                            f"Apple {version.platform} {locale}: synchronize {len(localized.apple.screenshots)} screenshot groups"
                        )
                    if localized.apple.app_previews:
                        changes.append(
                            f"Apple {version.platform} {locale}: synchronize {len(localized.apple.app_previews)} App Preview groups"
                        )
                continue
            remote = self.api.paginated(
                f"appStoreVersions/{identifier}/appStoreVersionLocalizations", params={"limit": 200}
            )
            mapped = {item["attributes"]["locale"]: item for item in remote}
            for locale, localized in project.locales.items():
                if localized.apple is None:
                    continue
                attributes = self.version_fields(
                    localized.common.description, localized.common.release_notes, localized.apple
                )
                if not attributes and not localized.apple.screenshots and not localized.apple.app_previews:
                    continue
                current = mapped.get(locale)
                if current is not None:
                    modified = {
                        key: value
                        for key, value in attributes.items()
                        if current["attributes"].get(key) != value
                    }
                    if modified:
                        changes.append(f"Apple {version.platform} {locale}: update {', '.join(modified)}")
                        if apply:
                            self.api.request(
                                "PATCH",
                                f"appStoreVersionLocalizations/{current['id']}",
                                payload={
                                    "data": {
                                        "type": "appStoreVersionLocalizations",
                                        "id": current["id"],
                                        "attributes": modified,
                                    }
                                },
                            )
                    localization_id = current["id"]
                else:
                    changes.append(f"Apple {version.platform} {locale}: create localization")
                    localization_id = None
                    if apply:
                        body = {
                            "data": {
                                "type": "appStoreVersionLocalizations",
                                "attributes": {"locale": locale, **attributes},
                                "relationships": {
                                    "appStoreVersion": {
                                        "data": {"type": "appStoreVersions", "id": identifier}
                                    }
                                },
                            }
                        }
                        localization_id = self.api.request(
                            "POST", "appStoreVersionLocalizations", payload=body
                        )["data"]["id"]
                if localized.apple.screenshots:
                    changes.append(
                        f"Apple {version.platform} {locale}: synchronize {len(localized.apple.screenshots)} screenshot groups"
                    )
                    if apply and localization_id is not None:
                        AppleAssetLibrary(self.api, self.config.app_id).synchronize(
                            localization_id,
                            localized.apple.screenshots,
                            directory,
                            self.config.confirm_asset_replacement,
                        )
                if localized.apple.app_previews:
                    changes.append(
                        f"Apple {version.platform} {locale}: synchronize {len(localized.apple.app_previews)} App Preview groups"
                    )
                    if apply and localization_id is not None:
                        AppleAppPreviews(self.api, self.config.app_id).synchronize(
                            localization_id,
                            localized.apple.app_previews,
                            directory,
                            localized.apple.preview_frame_timecode,
                            self.config.confirm_asset_replacement,
                        )
        return changes

    def synchronize_version_settings(
        self, version: AppleVersion, remote: dict[str, Any], *, apply: bool
    ) -> list[str]:
        if (
            remote["attributes"]["platform"] != version.platform
            or remote["attributes"]["versionString"] != version.version
        ):
            raise UnsafeOperationError("Apple version identity mismatch")
        if version.release_type == "SCHEDULED" and version.earliest_release_date is None:
            raise ConfigurationError("Scheduled Apple releases require earliest_release_date")
        desired = {"releaseType": version.release_type}
        if version.earliest_release_date is not None:
            desired["earliestReleaseDate"] = version.earliest_release_date
        modified = {key: value for key, value in desired.items() if remote["attributes"].get(key) != value}
        if not modified:
            return []
        state = remote["attributes"].get("appVersionState")
        if state not in {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED"}:
            raise UnsafeOperationError(f"Apple version release settings are not editable in state {state}")
        self.validate_future_release(version)
        if apply:
            payload = {"data": {"type": "appStoreVersions", "id": remote["id"], "attributes": modified}}
            self.api.request("PATCH", f"appStoreVersions/{remote['id']}", payload=payload)
        return [f"Apple {version.platform} {version.version}: update {', '.join(modified)}"]

    @staticmethod
    def validate_future_release(version: AppleVersion) -> None:
        if version.earliest_release_date is None:
            return
        date = datetime.fromisoformat(version.earliest_release_date.replace("Z", "+00:00"))
        if date <= datetime.now(UTC):
            raise UnsafeOperationError("A new or modified scheduled Apple release date must be in the future")

    def sync_app_information(self, project: ProjectConfig, *, apply: bool) -> list[str]:
        infos = self.api.paginated(f"apps/{self.config.app_id}/appInfos", params={"limit": 200})
        if not infos:
            raise RemoteAPIError("The Apple application has no appInfos resource")
        info_id = infos[0]["id"]
        remote = self.api.paginated(f"appInfos/{info_id}/appInfoLocalizations", params={"limit": 200})
        indexed = {item["attributes"]["locale"]: item for item in remote}
        changes: list[str] = []
        for locale, localized in project.locales.items():
            if localized.apple is None:
                continue
            values = {
                "name": localized.apple.name if localized.apple.name is not None else localized.common.name,
                "subtitle": localized.apple.subtitle,
                "privacyPolicyUrl": str(localized.apple.privacy_policy_url)
                if localized.apple.privacy_policy_url
                else None,
            }
            attributes = {key: value for key, value in values.items() if value is not None}
            if not attributes:
                continue
            previous = indexed.get(locale)
            if previous is not None:
                modified = {
                    key: value
                    for key, value in attributes.items()
                    if previous["attributes"].get(key) != value
                }
                if modified:
                    changes.append(f"Apple {locale}: update app info {', '.join(modified)}")
                    if apply:
                        payload = {
                            "data": {
                                "type": "appInfoLocalizations",
                                "id": previous["id"],
                                "attributes": modified,
                            }
                        }
                        self.api.request("PATCH", f"appInfoLocalizations/{previous['id']}", payload=payload)
            else:
                changes.append(f"Apple {locale}: create app info localization")
                if apply:
                    payload = {
                        "data": {
                            "type": "appInfoLocalizations",
                            "attributes": {"locale": locale, **attributes},
                            "relationships": {"appInfo": {"data": {"type": "appInfos", "id": info_id}}},
                        }
                    }
                    self.api.request("POST", "appInfoLocalizations", payload=payload)
        return changes

    @staticmethod
    def version_fields(
        description: str | None, release_notes: str | None, localized: AppleMetadata
    ) -> dict[str, str]:
        values = {
            "description": localized.description if localized.description is not None else description,
            "keywords": localized.keywords,
            "promotionalText": localized.promotional_text,
            "whatsNew": localized.whats_new if localized.whats_new is not None else release_notes,
            "supportUrl": str(localized.support_url) if localized.support_url else None,
            "marketingUrl": str(localized.marketing_url) if localized.marketing_url else None,
        }
        return {key: value for key, value in values.items() if value is not None}

    def upload_build(self, version: AppleVersion, directory: Path) -> str:
        if version.artifact is None:
            raise ConfigurationError("Apple release requires an artifact")
        path = project_path(directory, version.artifact)
        size = path.stat().st_size
        body = {
            "data": {
                "type": "buildUploads",
                "attributes": {
                    "cfBundleShortVersionString": version.version,
                    "cfBundleVersion": version.build_number,
                    "platform": version.platform,
                },
                "relationships": {"app": {"data": {"type": "apps", "id": self.config.app_id}}},
            }
        }
        reservation = self.api.request("POST", "buildUploads", payload=body)["data"]
        upload_id = reservation["id"]
        files_body = {
            "data": {
                "type": "buildUploadFiles",
                "attributes": {
                    "assetType": "ASSET",
                    "fileName": path.name,
                    "fileSize": size,
                    "uti": "com.apple.pkg" if path.suffix == ".pkg" else "com.apple.ipa",
                },
                "relationships": {"buildUpload": {"data": {"type": "buildUploads", "id": upload_id}}},
            }
        }
        file_record = self.api.request("POST", "buildUploadFiles", payload=files_body)["data"]
        AppleAssetUploadHelper.upload_parts(self.api, file_record["attributes"]["uploadOperations"], path)
        self.api.request(
            "PATCH",
            f"buildUploadFiles/{file_record['id']}",
            payload={
                "data": {
                    "type": "buildUploadFiles",
                    "id": file_record["id"],
                    "attributes": {"uploaded": True},
                }
            },
        )
        return upload_id
