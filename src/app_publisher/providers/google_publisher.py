import hashlib
import sys
from pathlib import Path
from typing import Any

import httpx

from app_publisher.core.api_client import APIClient
from app_publisher.core.assets import resolve_assets
from app_publisher.core.diagnostics import remote_error_message
from app_publisher.core.paths import project_path
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.google_listing_deletion import GoogleListingDeletion
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.google_store_details import GoogleStoreDetails
from app_publisher.models.project_config import ProjectConfig


class GooglePublisher:
    def __init__(self, client: APIClient, config: GoogleConfig):
        self.api = client
        self.config = config

    def edit_path(self, edit_id: str) -> str:
        return f"applications/{self.config.package_name}/edits/{edit_id}"

    def start_edit(self) -> str:
        return str(
            self.api.request("POST", f"applications/{self.config.package_name}/edits", payload={})["id"]
        )

    def listing(self, edit_id: str, locale: str) -> dict[str, Any] | None:
        result = self.api.request("GET", f"{self.edit_path(edit_id)}/listings")
        for item in result.get("listings", []):
            if item["language"] == locale:
                return item
        return None

    @staticmethod
    def fields(
        localized: GoogleMetadata, common_name: str | None, common_description: str | None
    ) -> dict[str, str]:
        attributes = {
            "title": localized.title if localized.title is not None else common_name,
            "shortDescription": localized.short_description,
            "fullDescription": localized.full_description
            if localized.full_description is not None
            else common_description,
            "video": str(localized.video) if localized.video else None,
        }
        return {key: value for key, value in attributes.items() if value is not None}

    def synchronize_details(self, edit_id: str, details: GoogleStoreDetails, *, apply: bool) -> list[str]:
        values = {
            "defaultLanguage": details.default_language,
            "contactWebsite": str(details.contact_website) if details.contact_website is not None else None,
            "contactEmail": details.contact_email,
            "contactPhone": details.contact_phone,
        }
        desired = {key: value for key, value in values.items() if value is not None}
        if not desired:
            return []
        base = self.edit_path(edit_id)
        remote = self.api.request("GET", f"{base}/details")
        modified = {key: value for key, value in desired.items() if remote.get(key) != value}
        if not modified:
            return []
        if apply:
            self.api.request("PATCH", f"{base}/details", payload=modified)
        return [f"Google store details: update {', '.join(modified)}"]

    def synchronize(self, project: ProjectConfig, directory: Path, *, apply: bool) -> list[str]:
        edit_id = self.start_edit()
        base = self.edit_path(edit_id)
        changes: list[str] = []
        committed = False
        try:
            if self.config.store_details is not None:
                changes.extend(self.synchronize_details(edit_id, self.config.store_details, apply=apply))
            remote = self.api.request("GET", f"{base}/listings").get("listings", [])
            listings = {entry["language"]: entry for entry in remote}
            for locale, localized in project.locales.items():
                if localized.google is None:
                    continue
                fields = self.fields(localized.google, localized.common.name, localized.common.description)
                current = listings.get(locale, {})
                updates = {key: value for key, value in fields.items() if current.get(key) != value}
                if updates:
                    changes.append(f"Google {locale}: update {', '.join(updates)}")
                    if apply:
                        self.api.request(
                            "PATCH" if locale in listings else "PUT",
                            f"{base}/listings/{locale}",
                            payload={
                                "language": locale,
                                **({**current, **updates} if locale in listings else fields),
                            },
                        )
                if localized.google.images and locale not in listings and not fields:
                    raise UnsafeOperationError(
                        f"Google {locale}: screenshots require an existing listing or declared localized metadata"
                    )
                for image_type, patterns in localized.google.images.items():
                    paths = resolve_assets(directory, patterns)
                    endpoint = f"{base}/listings/{locale}/{image_type}"
                    remote_images = (
                        self.api.request("GET", endpoint).get("images", []) if locale in listings else []
                    )
                    desired_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
                    if not isinstance(remote_images, list) or any(
                        not isinstance(item, dict) for item in remote_images
                    ):
                        raise RemoteAPIError(f"Google {locale} {image_type}: invalid image listing response")
                    if [item.get("sha256") for item in remote_images] == desired_hashes:
                        continue
                    changes.append(f"Google {locale} {image_type}: replace {len(paths)} images")
                    if apply:
                        if remote_images and not self.config.confirm_image_replacement:
                            raise UnsafeOperationError(
                                f"Google {locale} {image_type}: replacing existing images requires confirm_image_replacement: true"
                            )
                        if remote_images:
                            self.api.request("DELETE", endpoint)
                        for path in paths:
                            self.upload_image(edit_id, locale, image_type, path)
            if apply and changes:
                self.commit(edit_id, submit_for_review=project.publication.submit_for_review)
                committed = True
            if self.config.data_safety_csv is not None:
                changes.append("Google: update Data Safety declaration")
                if apply:
                    content = project_path(directory, self.config.data_safety_csv).read_text(encoding="utf-8")
                    self.api.request(
                        "POST",
                        f"applications/{self.config.package_name}/dataSafety",
                        payload={"safetyLabels": content},
                    )
        finally:
            if not committed:
                self.discard_edit(edit_id)
        return changes

    def upload_image(self, edit_id: str, locale: str, image_type: str, path: Path) -> dict[str, Any]:
        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        url = f"https://androidpublisher.googleapis.com/upload/androidpublisher/v3/{self.edit_path(edit_id)}/listings/{locale}/{image_type}"
        with path.open("rb") as stream:
            response = self.api.client.post(
                url,
                params={"uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {self.api.token_provider()}",
                    "Content-Type": content_type,
                },
                content=stream,
                timeout=120,
            )
        try:
            response.raise_for_status()
        except Exception as error:
            raise RemoteAPIError(f"Google image upload failed with HTTP {response.status_code}") from error
        return response.json()

    def delete_listings(self, deletions: list[GoogleListingDeletion], *, apply: bool) -> list[str]:
        if not deletions:
            return []
        if apply and any(not item.confirm_deletion for item in deletions):
            raise UnsafeOperationError("Google listing deletion requires confirm_deletion: true")
        edit_id = self.start_edit()
        base = self.edit_path(edit_id)
        committed = False
        try:
            remote = self.api.request("GET", f"{base}/listings")
            known = {item["language"] for item in remote.get("listings", [])}
            changes = [f"Google listing {item.locale}: delete" for item in deletions if item.locale in known]
            if apply and changes:
                for item in deletions:
                    if item.locale in known:
                        self.api.request("DELETE", f"{base}/listings/{item.locale}")
                self.commit(edit_id, submit_for_review=False)
                committed = True
            return changes
        finally:
            if not committed:
                self.discard_edit(edit_id)

    def upload_media(self, edit_id: str, path: Path, resource: str) -> dict[str, Any]:
        url = f"https://androidpublisher.googleapis.com/upload/androidpublisher/v3/{self.edit_path(edit_id)}/{resource}"
        with path.open("rb") as stream:
            response = self.api.client.post(
                url,
                params={"uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {self.api.token_provider()}",
                    "Content-Type": "application/octet-stream",
                },
                content=stream,
                timeout=300,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RemoteAPIError(
                f"Google {'bundle' if resource == 'bundles' else resource} upload failed with HTTP {response.status_code}: {remote_error_message(response)}",
                status_code=response.status_code,
            ) from error
        try:
            data = response.json()
        except ValueError as error:
            raise RemoteAPIError(f"Google {resource} upload returned invalid JSON") from error
        if not isinstance(data, dict):
            raise RemoteAPIError(f"Google {resource} upload returned an unexpected response")
        return data

    def upload_bundle(self, edit_id: str, directory: Path) -> str:
        release = self.config.release
        if release is None or release.artifact is None:
            raise UnsafeOperationError("Google bundle upload requires a configured artifact")
        artifact = project_path(directory, release.artifact)
        if artifact.suffix.lower() not in {".aab", ".apk"}:
            raise UnsafeOperationError("Google release artifact must be an AAB or APK")
        resource = "apks" if artifact.suffix.lower() == ".apk" else "bundles"
        data = self.upload_media(edit_id, artifact, resource)
        uploaded_version = str(data["versionCode"])
        if release.version_codes and uploaded_version not in release.version_codes:
            raise UnsafeOperationError(
                "Uploaded Google artifact version does not match configured version_codes"
            )

        return uploaded_version

    def publish_release(
        self, directory: Path, locales: dict[str, str], *, apply: bool, submit_for_review: bool = False
    ) -> list[str]:
        release = self.config.release
        if release is None:
            raise UnsafeOperationError("Google release is not configured")

        if release.artifact is not None and len(release.version_codes) != 1:
            raise UnsafeOperationError(
                "Google artifact releases require exactly one explicit expected version code"
            )

        changes = [f"Google: update track {release.track} ({release.status})"]
        if not apply:
            return changes
        edit_id = self.start_edit()
        base = self.edit_path(edit_id)
        try:
            track_path = f"{base}/tracks/{release.track}"
            try:
                remote_track = self.api.request("GET", track_path)
            except RemoteAPIError as error:
                if error.status_code != 404:
                    raise
                remote_track = {}
            if remote_track.get("releases") and not release.confirm_track_replacement:
                raise UnsafeOperationError(
                    f"Google track {release.track} has existing releases. Set confirm_track_replacement: true to replace them"
                )
            versions = [self.upload_bundle(edit_id, directory)] if release.artifact else release.version_codes
            if not versions:
                raise UnsafeOperationError("Google release needs an AAB, APK or version codes")
            for symbols in release.deobfuscation_files:
                if str(symbols.version_code) not in versions:
                    raise UnsafeOperationError(
                        f"Symbols version {symbols.version_code} is not part of this release"
                    )
                path = project_path(directory, symbols.path)
                self.upload_media(
                    edit_id, path, f"apks/{symbols.version_code}/deobfuscationFiles/{symbols.file_type}"
                )
            payload: dict[str, Any] = {"status": release.status, "versionCodes": versions}
            if release.rollout_fraction is not None:
                payload["userFraction"] = release.rollout_fraction
            if release.name is not None:
                payload["name"] = release.name
            if release.in_app_update_priority is not None:
                payload["inAppUpdatePriority"] = release.in_app_update_priority
            if release.country_targeting is not None:
                payload["countryTargeting"] = {
                    "countries": release.country_targeting.countries,
                    "includeRestOfWorld": release.country_targeting.include_rest_of_world,
                }
            if locales:
                payload["releaseNotes"] = [
                    {"language": locale, "text": text} for locale, text in locales.items()
                ]
            self.api.request(
                "PUT",
                f"{base}/tracks/{release.track}",
                payload={"track": release.track, "releases": [payload]},
            )
            if release.testers:
                self.api.request(
                    "PUT", f"{base}/testers/{release.track}", payload={"googleGroups": release.testers}
                )
            review_is_automatic = release.track == "internal"
            self.commit(edit_id, submit_for_review=submit_for_review or review_is_automatic)
        except Exception:
            self.discard_edit(edit_id)
            raise
        return changes

    def discard_edit(self, edit_id: str) -> None:
        original = sys.exception()
        try:
            self.api.request("DELETE", self.edit_path(edit_id))
        except RemoteAPIError as error:
            if original is None:
                raise
            original.add_note(f"Google edit cleanup also failed: {error}")

    def commit(self, edit_id: str, *, submit_for_review: bool) -> None:
        path = self.edit_path(edit_id)
        self.api.request("POST", f"{path}:validate", payload={})
        params = {"changesInReviewBehavior": "ERROR_IF_IN_REVIEW"}

        if not submit_for_review:
            params["changesNotSentForReview"] = "true"

        self.api.request("POST", f"{path}:commit", params=params, payload={})
