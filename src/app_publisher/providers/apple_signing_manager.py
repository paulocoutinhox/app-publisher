import base64
import binascii
from pathlib import Path

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_signing_config import AppleSigningConfig


class AppleSigningManager:
    def __init__(self, api: APIClient, bundle_id: str):
        self.api = api
        self.bundle_id = bundle_id

    def synchronize(self, config: AppleSigningConfig, directory: Path, *, apply: bool) -> list[str]:
        changes: list[str] = []
        for certificate in config.certificates:
            data = self.api.request("GET", f"certificates/{certificate.certificate_id}")["data"]
            if data["id"] != certificate.certificate_id:
                raise UnsafeOperationError(
                    "Apple signing certificate identifier differs from the requested ID"
                )
            content = self._decode(data["attributes"]["certificateContent"])
            changes.extend(self._save(content, directory, certificate.output, apply=apply))
        if not config.profiles:
            return changes
        bundle = self.api.paginated("bundleIds", params={"filter[identifier]": self.bundle_id, "limit": 200})
        matches = [item for item in bundle if item["attributes"].get("identifier") == self.bundle_id]
        if len(matches) != 1:
            raise UnsafeOperationError(
                f"Apple bundle identifier must resolve to exactly one registered bundle: {self.bundle_id}"
            )
        bundle_identifier = matches[0]["id"]
        for profile in config.profiles:
            resources = self.api.paginated("profiles", params={"filter[name]": profile.name, "limit": 200})
            matching = [item for item in resources if item["attributes"].get("name") == profile.name]
            if len(matching) > 1:
                raise UnsafeOperationError(f"Apple signing profile name is ambiguous: {profile.name}")
            if not matching:
                if not profile.create_if_missing:
                    raise UnsafeOperationError(
                        f"Apple signing profile does not exist and create_if_missing is false: {profile.name}"
                    )
                changes.append(f"Apple signing: create profile {profile.name}")
                if not apply:
                    continue
                relationships = {
                    "bundleId": {"data": {"type": "bundleIds", "id": bundle_identifier}},
                    "certificates": {
                        "data": [{"type": "certificates", "id": item} for item in profile.certificate_ids]
                    },
                }
                if profile.device_ids:
                    relationships["devices"] = {
                        "data": [{"type": "devices", "id": item} for item in profile.device_ids]
                    }
                payload = {
                    "data": {
                        "type": "profiles",
                        "attributes": {"name": profile.name, "profileType": profile.profile_type},
                        "relationships": relationships,
                    }
                }
                created = self.api.request("POST", "profiles", payload=payload)["data"]
                current = self.api.request("GET", f"profiles/{created['id']}")["data"]
            else:
                current = self.api.request("GET", f"profiles/{matching[0]['id']}")["data"]
            attributes = current["attributes"]
            if attributes.get("profileType") != profile.profile_type:
                raise UnsafeOperationError(f"Apple signing profile has an incompatible type: {profile.name}")
            relationships = current.get("relationships", {})
            if relationships.get("bundleId", {}).get("data", {}).get("id") != bundle_identifier:
                raise UnsafeOperationError(
                    f"Apple signing profile belongs to a different Bundle ID: {profile.name}"
                )
            certificate_ids = {item["id"] for item in relationships.get("certificates", {}).get("data", [])}
            if certificate_ids != set(profile.certificate_ids):
                raise UnsafeOperationError(
                    f"Apple signing profile certificates do not match the YAML: {profile.name}"
                )
            device_ids = {item["id"] for item in relationships.get("devices", {}).get("data", [])}
            if device_ids != set(profile.device_ids):
                raise UnsafeOperationError(
                    f"Apple signing profile devices do not match the YAML: {profile.name}"
                )
            changes.extend(
                self._save(self._decode(attributes["profileContent"]), directory, profile.output, apply=apply)
            )
        return changes

    @staticmethod
    def _decode(content: str) -> bytes:
        try:
            return base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as error:
            raise UnsafeOperationError("Apple returned malformed signing data") from error

    @staticmethod
    def _save(content: bytes, directory: Path, output: Path, *, apply: bool) -> list[str]:
        base = directory.resolve()
        target = (base / output).resolve()
        if target == base or base not in target.parents:
            raise UnsafeOperationError(
                f"Signing artifact output is outside the configuration directory: {output}"
            )
        if target.is_file():
            if target.read_bytes() != content:
                raise UnsafeOperationError(f"Signing artifact already exists with different bytes: {output}")
            return []
        if not apply:
            return [f"Apple signing: download {output.as_posix()}"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return [f"Apple signing: download {output.as_posix()}"]
