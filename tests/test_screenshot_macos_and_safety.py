import httpx
import pytest

from app_publisher.core.api_client import APIClient
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.models.screenshot_scene import ScreenshotScene
from app_publisher.providers.google_publisher import GooglePublisher
from app_publisher.screenshots.screenshot_planner import ScreenshotPlanner


def test_macos_capture_plan(tmp_path):
    events = []

    class Result:
        stdout = b""

    def runner(command, *, check, capture_output):
        events.append(command)
        if command[0] == "screencapture":
            (tmp_path / "store.png").write_bytes(b"fake-png")
        return Result()

    plan = ScreenshotPlan(
        platform="macos",
        device="desktop",
        scenes=[ScreenshotScene(name="home", url="exampleapp://home", output="store.png", delay_seconds=0)],
    )
    assert ScreenshotPlanner(runner=runner, sleeper=lambda _: None).run(plan, tmp_path) == [
        tmp_path / "store.png"
    ]
    assert events[0] == ["open", "exampleapp://home"]
    assert events[1] == ["screencapture", "-x", str(tmp_path / "store.png")]


def test_google_does_not_upload_images_without_listing(project, tmp_path):
    project.locales["en-US"].common.name = None
    project.locales["en-US"].common.description = None
    project.locales["en-US"].google = GoogleMetadata(images={"phoneScreenshots": ["shot.png"]})

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "edit"})
        return httpx.Response(200, json={"listings": []})

    api = APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler))
    with pytest.raises(UnsafeOperationError, match="require an existing listing"):
        GooglePublisher(api, project.google).synchronize(project, tmp_path, apply=True)
