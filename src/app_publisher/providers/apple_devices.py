from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_registered_device import AppleRegisteredDevice


class AppleDevices:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(self, devices: list[AppleRegisteredDevice], *, apply: bool) -> list[str]:
        if not devices:
            return []
        existing = self.api.paginated("devices", params={"limit": 200})
        indexed = {device["attributes"]["udid"]: device for device in existing}
        changes: list[str] = []
        for device in devices:
            current = indexed.get(device.udid)
            if current is not None:
                if current["attributes"].get("platform") != device.platform:
                    raise UnsafeOperationError(f"Apple device platform mismatch: {device.udid}")
                if current["attributes"].get("status") == "DISABLED":
                    raise UnsafeOperationError(f"Apple device has been disabled: {device.udid}")
                continue
            changes.append(f"Apple signing: register {device.platform} device {device.name}")
            if apply:
                attrs = {"name": device.name, "udid": device.udid, "platform": device.platform}
                self.api.request(
                    "POST", "devices", payload={"data": {"type": "devices", "attributes": attrs}}
                )
        return changes
