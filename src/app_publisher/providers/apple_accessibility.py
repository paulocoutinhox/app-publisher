from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_accessibility_declaration import AppleAccessibilityDeclaration


class AppleAccessibility:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def synchronize(self, declarations: list[AppleAccessibilityDeclaration], *, apply: bool) -> list[str]:
        if not declarations:
            return []
        existing = self.api.paginated(f"apps/{self.app_id}/accessibilityDeclarations", params={"limit": 200})
        indexed: dict[str, dict] = {}
        for item in existing:
            family = item["attributes"]["deviceFamily"]
            if family in indexed and item["attributes"]["state"] != "REPLACED":
                raise RemoteAPIError(f"Duplicate Apple accessibility declarations for {family}")
            if item["attributes"]["state"] != "REPLACED":
                indexed[family] = item
        changes: list[str] = []
        for declaration in declarations:
            attributes = declaration.model_dump(exclude={"publish", "device_family"}, exclude_none=True)
            keys = {
                "voiceover": "supportsVoiceover",
                "voice_control": "supportsVoiceControl",
                "larger_text": "supportsLargerText",
                "sufficient_contrast": "supportsSufficientContrast",
                "dark_interface": "supportsDarkInterface",
                "differentiate_without_color_alone": "supportsDifferentiateWithoutColorAlone",
                "reduced_motion": "supportsReducedMotion",
                "captions": "supportsCaptions",
                "audio_descriptions": "supportsAudioDescriptions",
            }
            desired = {keys[key]: value for key, value in attributes.items()}
            resource = indexed.get(declaration.device_family)
            if resource is None:
                changes.append(
                    f"Apple accessibility {declaration.device_family}: create{' and publish' if declaration.publish else ''}"
                )
                if apply:
                    body = {
                        "data": {
                            "type": "accessibilityDeclarations",
                            "attributes": {"deviceFamily": declaration.device_family, **desired},
                            "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}},
                        }
                    }
                    created = self.api.request("POST", "accessibilityDeclarations", payload=body)["data"]
                    if declaration.publish:
                        self.publish(created["id"])
                continue
            changed = {
                key: value for key, value in desired.items() if resource["attributes"].get(key) != value
            }
            published = resource["attributes"]["state"] == "PUBLISHED"
            if published and changed:
                raise UnsafeOperationError(
                    f"Apple accessibility {declaration.device_family} is published and cannot be edited directly"
                )
            if changed:
                changes.append(
                    f"Apple accessibility {declaration.device_family}: update {', '.join(changed)}"
                )
                if apply:
                    self.api.request(
                        "PATCH",
                        f"accessibilityDeclarations/{resource['id']}",
                        payload={
                            "data": {
                                "type": "accessibilityDeclarations",
                                "id": resource["id"],
                                "attributes": changed,
                            }
                        },
                    )
            if declaration.publish and not published:
                changes.append(f"Apple accessibility {declaration.device_family}: publish")
                if apply:
                    self.publish(resource["id"])
        return changes

    def publish(self, identifier: str) -> None:
        self.api.request(
            "PATCH",
            f"accessibilityDeclarations/{identifier}",
            payload={
                "data": {
                    "type": "accessibilityDeclarations",
                    "id": identifier,
                    "attributes": {"publish": True},
                }
            },
        )
