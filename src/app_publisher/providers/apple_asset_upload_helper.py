from pathlib import Path
from typing import Any

import httpx

from app_publisher.core.api_client import APIClient
from app_publisher.errors.remote_api_error import RemoteAPIError


class AppleAssetUploadHelper:
    @staticmethod
    def upload_parts(api: APIClient, operations: list[dict[str, Any]], source: bytes | Path) -> None:
        for operation in operations:
            offset = operation["offset"]
            length = operation["length"]
            headers = {entry["name"]: entry["value"] for entry in operation.get("requestHeaders", [])}
            try:
                if isinstance(source, Path):
                    with source.open("rb") as stream:
                        stream.seek(offset)
                        chunk = stream.read(length)
                else:
                    chunk = source[offset : offset + length]
                if len(chunk) != length:
                    raise RemoteAPIError("Apple transfer operation exceeds the source file size")
                response = api.client.request(
                    operation["method"], operation["url"], headers=headers, content=chunk, timeout=120
                )
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise RemoteAPIError("Apple asset transfer failed") from error
