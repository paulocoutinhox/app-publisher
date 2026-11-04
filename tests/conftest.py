from pathlib import Path

import httpx
import pytest
from api_fixture_helper import APIFixtureHelper
from PIL import Image

from app_publisher.models.project_config import ProjectConfig


@pytest.fixture
def project() -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "schema_version": 1,
            "app": {"id": "demo", "paid": False},
            "apple": {
                "app_id": "123",
                "bundle_id": "com.demo",
                "versions": [{"platform": "IOS", "version": "2.0"}],
            },
            "google": {
                "package_name": "com.demo",
                "release": {"track": "internal", "status": "draft", "version_codes": ["8"]},
            },
            "firebase": {
                "project_id": "demo-123456",
                "apple_apps": [{"identifier": "com.demo", "output": "out/plist"}],
                "android_apps": [{"identifier": "com.demo", "output": "out/json"}],
            },
            "locales": {
                "en-US": {
                    "common": {"name": "Demo", "description": "A demo app", "release_notes": "Changes"},
                    "apple": {"subtitle": "All apps", "keywords": "demo,app", "screenshots": {}},
                    "google": {"short_description": "Short demo", "images": {}},
                }
            },
        }
    )


@pytest.fixture
def png(tmp_path: Path) -> Path:
    file = tmp_path / "shot.png"
    Image.new("RGB", (1200, 1600), "white").save(file)
    return file


class Recorder:
    def __init__(self, handler):
        self.calls: list[httpx.Request] = []
        self.handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self.handler(request)


@pytest.fixture
def api_fixture() -> type[APIFixtureHelper]:
    return APIFixtureHelper
