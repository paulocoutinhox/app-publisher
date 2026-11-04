import time
from collections.abc import Callable
from typing import Any, Literal

import httpx

from app_publisher.core.diagnostics import remote_error_message
from app_publisher.errors.remote_api_error import RemoteAPIError


class APIClient:
    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], str],
        transport: httpx.BaseTransport | None = None,
        retries: int = 3,
    ):
        if retries < 0:
            raise ValueError("HTTP retry count cannot be negative")
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.token_provider = token_provider
        self.client = httpx.Client(transport=transport, timeout=120)

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        version: Literal["v1", "v2"] = "v1",
    ) -> dict[str, Any]:
        base = self.base_url
        if version == "v2":
            if not base.endswith("/v1"):
                raise RemoteAPIError("Versioned API requests require a v1 base URL")
            base = base[:-1] + "2"
        request_headers = {"Authorization": f"Bearer {self.token_provider()}"}
        request_headers.update(headers or {})
        try:
            attempt = 0
            while True:
                response = self.client.request(
                    method,
                    f"{base}/{path.lstrip('/')}",
                    params=params,
                    json=payload,
                    content=content,
                    headers=request_headers,
                )
                if (
                    method.upper() != "GET"
                    or response.status_code not in {429, 500, 502, 503, 504}
                    or attempt == self.retries
                ):
                    response.raise_for_status()
                    break
                seconds = min(float(response.headers.get("Retry-After", "0")) or 2**attempt, 30)
                time.sleep(seconds)
                attempt += 1
        except httpx.HTTPStatusError as error:
            detail = remote_error_message(error.response)
            raise RemoteAPIError(
                f"{method} {path} returned HTTP {error.response.status_code}: {detail}",
                status_code=error.response.status_code,
            ) from error
        except httpx.RequestError as error:
            raise RemoteAPIError(f"{method} {path} failed: {error}") from error
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as error:
            raise RemoteAPIError(f"{method} {path} returned invalid JSON") from error
        if not isinstance(data, dict):
            raise RemoteAPIError(f"{method} {path} returned an unexpected JSON type")
        return data

    def paginated(
        self, path: str, *, params: dict[str, Any] | None = None, version: Literal["v1", "v2"] = "v1"
    ) -> list[dict[str, Any]]:
        base = self.base_url
        if version == "v2":
            if not base.endswith("/v1"):
                raise RemoteAPIError("Versioned API pagination requires a v1 base URL")
            base = base[:-1] + "2"
        items: list[dict[str, Any]] = []
        next_url: str | None = path
        visited: set[str] = set()
        while next_url:
            if next_url in visited:
                raise RemoteAPIError(f"Pagination cycle detected for {path}")
            visited.add(next_url)
            if len(visited) > 500:
                raise RemoteAPIError(f"Pagination exceeded 500 pages for {path}")
            if next_url.startswith("https://"):
                if not next_url.startswith(base + "/"):
                    raise RemoteAPIError("Pagination URL points to an unexpected server")
                next_url = next_url[len(base) + 1 :]
            result = self.request("GET", next_url, params=params, version=version)
            page = result.get("data")
            if not isinstance(page, list):
                raise RemoteAPIError("Expected a paginated resource list")
            items.extend(page)
            next_url = result.get("links", {}).get("next")
            params = None
        return items
