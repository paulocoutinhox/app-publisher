import json
from pathlib import Path
from typing import Any

import httpx


class APIFixtureHelper:
    directory = Path(__file__).parent / "fixtures/api"

    @classmethod
    def load(cls, name: str) -> dict[str, Any]:
        return json.loads((cls.directory / name).read_text(encoding="utf-8"))

    @classmethod
    def response(cls, name: str) -> httpx.Response:
        fixture = cls.load(name)
        return httpx.Response(fixture["status_code"], json=fixture["body"])
