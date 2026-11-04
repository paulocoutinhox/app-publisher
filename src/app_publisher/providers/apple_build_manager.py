import time
from collections.abc import Callable
from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion


class AppleBuildManager:
    def __init__(
        self,
        api: APIClient,
        app_id: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api = api
        self.app_id = app_id
        self.clock = clock
        self.sleep = sleep

    def find(self, version: AppleVersion) -> dict[str, Any] | None:
        if version.build_number is None:
            raise ConfigurationError("Apple build selection requires an explicit build number")

        builds = self.api.paginated(
            "builds",
            params={
                "filter[app]": self.app_id,
                "filter[version]": version.build_number,
                "filter[preReleaseVersion.version]": version.version,
                "filter[preReleaseVersion.platform]": version.platform,
                "limit": 200,
            },
        )
        matches = [build for build in builds if build["attributes"].get("version") == version.build_number]

        if len(matches) > 1:
            raise UnsafeOperationError("Apple returned multiple builds for the exact declared identity")

        if not matches:
            return None

        build = matches[0]
        prerelease = self.api.request("GET", f"builds/{build['id']}/preReleaseVersion")["data"]["attributes"]

        if (prerelease.get("version"), prerelease.get("platform")) != (version.version, version.platform):
            raise UnsafeOperationError(
                "The Apple build marketing version or platform does not match the YAML"
            )

        return build

    @staticmethod
    def require_valid(build: dict[str, Any] | None) -> dict[str, Any]:
        if build is None:
            raise UnsafeOperationError("Expected one processed Apple build for the declared identity")

        if build["attributes"].get("processingState") != "VALID" or build["attributes"].get("expired"):
            raise UnsafeOperationError("The selected Apple build must be VALID and not expired")

        return build

    def wait(self, version: AppleVersion, *, timeout: int = 900, interval: int = 10) -> dict[str, Any]:
        if timeout < 1 or not 1 <= interval <= 30:
            raise ConfigurationError("Build polling requires a positive timeout and a 1-30 second interval")

        deadline = self.clock() + timeout

        while True:
            build = self.find(version)

            if build is not None:
                state = build["attributes"].get("processingState")

                if state == "VALID":
                    return self.require_valid(build)

                if state in {"FAILED", "INVALID"}:
                    raise UnsafeOperationError(
                        f"Apple processing ended with {state}. Inspect the build diagnostics"
                    )

                if state != "PROCESSING":
                    raise RemoteAPIError("Apple returned an unknown build processing state")

            remaining = deadline - self.clock()

            if remaining <= 0:
                raise UnsafeOperationError("Apple build processing exceeded the configured timeout")

            self.sleep(min(interval, remaining))
