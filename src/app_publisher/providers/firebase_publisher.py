import base64
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.firebase_config import FirebaseConfig
from app_publisher.providers.firebase_certificates import FirebaseCertificates


class FirebasePublisher:
    def __init__(self, client: APIClient, cloud: APIClient, config: FirebaseConfig):
        self.api = client
        self.cloud = cloud
        self.config = config

    def ensure_project(self) -> None:
        project = self.config.project_id
        try:
            self.api.request("GET", f"projects/{project}")
            return
        except RemoteAPIError as error:
            if "HTTP 404" not in str(error):
                raise
        if not self.config.create_if_missing:
            raise ConfigurationError(f"Firebase project {project} does not exist")
        try:
            self.cloud.request("GET", f"projects/{project}")
        except RemoteAPIError as error:
            if "HTTP 404" not in str(error):
                raise
            operation = self.cloud.request(
                "POST", "projects", payload={"projectId": project, "name": project}
            )
            self.wait_operation(operation, client=self.cloud)
        operation = self.api.request("POST", f"projects/{project}:addFirebase", payload={})
        self.wait_operation(operation, client=self.api)

    def synchronize(self, directory: Path, *, apply: bool) -> list[str]:
        actions: list[str] = []
        if not apply:
            for platform, apps in [
                ("iosApps", self.config.apple_apps),
                ("androidApps", self.config.android_apps),
            ]:
                for app in apps:
                    actions.append(f"Firebase: ensure {platform} {app.identifier} and download configuration")
            return actions
        self.ensure_project()
        for platform, apps, field in [
            ("iosApps", self.config.apple_apps, "bundleId"),
            ("androidApps", self.config.android_apps, "packageName"),
        ]:
            known: list[dict[str, Any]] = []
            token = ""
            visited: set[str] = set()
            while apps:
                if token in visited or len(visited) >= 500:
                    raise RemoteAPIError(f"Firebase {platform} pagination cycle or page limit exceeded")
                visited.add(token)
                response = self.api.request(
                    "GET",
                    f"projects/{self.config.project_id}/{platform}",
                    params={"pageToken": token} if token else None,
                )
                known.extend(response.get("apps", []))
                token = response.get("nextPageToken", "")
                if not token:
                    break
            for app in apps:
                matching = [entry for entry in known if entry.get(field) == app.identifier]
                if matching:
                    resource = matching[0]
                else:
                    body = {field: app.identifier}
                    if app.display_name:
                        body["displayName"] = app.display_name
                    operation = self.api.request(
                        "POST", f"projects/{self.config.project_id}/{platform}", payload=body
                    )
                    resource = self.wait_operation(operation)
                name = resource["name"]
                config = self.api.request("GET", f"{name}/config")
                destination = project_path(directory, app.output)
                self.write_config(destination, base64.b64decode(config["configFileContents"], validate=True))
                actions.append(f"Firebase: configured {app.identifier} -> {app.output.as_posix()}")
                if platform == "androidApps":
                    actions.extend(FirebaseCertificates(self.api).synchronize(name, app.sha_certificates))
        return actions

    @staticmethod
    def write_config(destination: Path, contents: bytes) -> None:
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise UnsafeOperationError(f"Firebase configuration output must be a regular file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=".app-publisher-", dir=destination.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def wait_operation(self, operation: dict[str, Any], client: APIClient | None = None) -> dict[str, Any]:
        if "name" not in operation:
            raise RemoteAPIError("Firebase creation returned no operation name")
        client = client or self.api
        for attempt in range(12):
            current = operation if operation.get("done") else client.request("GET", operation["name"])
            if current.get("done"):
                if "error" in current:
                    raise RemoteAPIError(f"Firebase operation failed: {current['error']}")
                response = current.get("response")
                if not isinstance(response, dict):
                    raise RemoteAPIError("Firebase operation returned no resource")
                return response
            if attempt < 11:
                time.sleep(2)
        raise RemoteAPIError("Firebase operation did not finish within the polling window")
