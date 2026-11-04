import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import Recorder
from pydantic import ValidationError

from app_publisher.core.api_client import APIClient
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_tester_group import GoogleTesterGroup
from app_publisher.providers.apple_app_previews import AppleAppPreviews
from app_publisher.providers.apple_publisher import ApplePublisher
from app_publisher.providers.google_testers import GoogleTesters


def video_reference():
    return {
        "placementProfileGroups": [{"placementProfileGroupId": "IPHONE_PROFILE", "displayClassId": "IPHONE"}],
        "placementTypes": [
            {
                "placementTypeId": "APP_PREVIEW",
                "specMappings": [{"placementGroupId": "IPHONE_PROFILE", "specs": ["video-spec"]}],
            }
        ],
        "videoSpecs": [
            {
                "specId": "video-spec",
                "dimensions": {"minWidth": 720, "maxWidth": 720, "minHeight": 1280, "maxHeight": 1280},
                "fileExtensions": [".mp4"],
                "maxFileSize": 5000000,
                "audioRequired": True,
                "frameRates": [{"minFps": 24, "maxFps": 30}],
                "duration": {"min": "PT15S", "max": "PT30S"},
            }
        ],
    }


def inspection(width=720, height=1280, fps="30/1", duration="20", audio=True):
    streams = [{"codec_type": "video", "width": width, "height": height, "avg_frame_rate": fps}]
    if audio:
        streams.append({"codec_type": "audio"})
    return {"streams": streams, "format": {"duration": duration}}


def test_preview_video_validation_and_errors(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"valid test fixture")
    AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", video_reference(), inspection())
    with pytest.raises(RemoteAPIError, match="APP_PREVIEW"):
        AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", {"placementTypes": []}, inspection())
    with pytest.raises(ConfigurationError, match="does not accept"):
        AppleAppPreviews.validate_video(path, "INVALID", video_reference(), inspection())
    for meta in [
        inspection(width=500),
        inspection(fps="15/1"),
        inspection(duration="12"),
        inspection(audio=False),
        inspection(fps="0/0"),
        {"streams": []},
    ]:
        with pytest.raises(ConfigurationError):
            AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", video_reference(), meta)
    monkeypatch.setattr("app_publisher.providers.apple_app_previews.shutil.which", lambda name: None)
    with pytest.raises(ConfigurationError, match="ffprobe"):
        AppleAppPreviews.inspect_video(path)


def test_preview_inspection_subprocess(tmp_path, monkeypatch):
    path = tmp_path / "test.mp4"
    path.write_bytes(b"test")
    monkeypatch.setattr(
        "app_publisher.providers.apple_app_previews.shutil.which", lambda name: "/usr/bin/ffprobe"
    )
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        "app_publisher.providers.apple_app_previews.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, json.dumps(inspection()), ""),
    )
    assert AppleAppPreviews.inspect_video(path)["streams"][0]["width"] == 720
    monkeypatch.setattr(
        "app_publisher.providers.apple_app_previews.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "", "invalid"),
    )
    with pytest.raises(ConfigurationError, match="inspection failed"):
        AppleAppPreviews.inspect_video(path)
    monkeypatch.setattr(
        "app_publisher.providers.apple_app_previews.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "not-json", ""),
    )
    with pytest.raises(ConfigurationError, match="invalid JSON"):
        AppleAppPreviews.inspect_video(path)


def preview_recorder(path, old=False, ready=True):
    reference_name = AppleAppPreviews.reference_name(path, None)

    def handler(req):
        name = req.url.path
        if name.endswith("/appAssetLibraryRefData"):
            return httpx.Response(200, json={"data": [{"attributes": video_reference()}]})
        if name.endswith("/assetLibrary"):
            return httpx.Response(200, json={"data": {"id": "lib"}})
        if name.endswith("/placements"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "old-placement",
                            "attributes": {"placementGroup": "IPHONE_PROFILE"},
                            "relationships": {"video": {"data": {"id": "old-video"}}},
                        }
                    ]
                    if old
                    else []
                },
            )
        if name.endswith("/appAssetLibraryVideos/old-video"):
            return httpx.Response(
                200, json={"data": {"attributes": {"referenceName": reference_name if ready else "old"}}}
            )
        if name.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "video", "attributes": {"referenceName": reference_name}}]
                    if ready and old
                    else []
                },
            )
        if name.endswith("/appAssetLibraryVideos") and req.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "video",
                        "attributes": {
                            "uploadOperations": [
                                {
                                    "method": "PUT",
                                    "url": "https://upload.test/video",
                                    "offset": 0,
                                    "length": path.stat().st_size,
                                }
                            ]
                        },
                    }
                },
            )
        if name.endswith("/appAssetLibraryVideos/video"):
            return httpx.Response(200, json={"data": {"attributes": {"state": "PREPARE_FOR_SUBMISSION"}}})
        if name.endswith("/appAssetLibraryPlacements") and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "new-placement"}})
        return httpx.Response(200, json={})

    return Recorder(handler)


def test_preview_upload_reuse_and_placement(tmp_path, monkeypatch):
    path = tmp_path / "demo.mp4"
    path.write_bytes(b"test media")
    monkeypatch.setattr(AppleAppPreviews, "inspect_video", staticmethod(lambda path: inspection()))
    record = preview_recorder(path)
    manager = AppleAppPreviews(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(record)), "123"
    )
    assert manager.synchronize("loc", {"IPHONE": ["demo.mp4"]}, tmp_path) == [
        "Apple IPHONE_PROFILE: synchronized 1 App Previews"
    ]
    assert any(request.url.host == "upload.test" for request in record.calls)
    assert any(
        request.method == "PATCH" and "appAssetLibraryVideos" in request.url.path for request in record.calls
    )
    assert any(
        request.method == "POST" and request.url.path.endswith("/appAssetLibraryPlacementOrderingRequests")
        for request in record.calls
    )
    record = preview_recorder(path, old=True)
    manager = AppleAppPreviews(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(record)), "123"
    )
    assert manager.synchronize("loc", {"IPHONE_PROFILE": ["demo.mp4"]}, tmp_path) == []
    assert not any(request.method in {"POST", "PATCH", "DELETE"} for request in record.calls)
    record = preview_recorder(path, old=True, ready=False)
    manager = AppleAppPreviews(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(record)), "123"
    )
    assert manager.synchronize("loc", {"IPHONE": ["demo.mp4"]}, tmp_path, confirm_replacement=True)
    assert any(request.method == "DELETE" for request in record.calls)


def test_preview_existing_video_and_states(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"test")
    name = AppleAppPreviews.reference_name(path, "00:00:01:00")
    for state in ("AWAITING_UPLOAD", "FAILED", "SURPRISE"):
        rec = Recorder(
            lambda r: httpx.Response(
                200, json={"data": {"attributes": {"state": state, "stateDetails": "bad"}}}
            )
        )
        video = AppleAppPreviews(APIClient("https://api.test", lambda: "t", httpx.MockTransport(rec)), "123")
        if state == "AWAITING_UPLOAD":
            monkeypatch.setattr("app_publisher.providers.apple_app_previews.time.sleep", lambda _: None)
            with pytest.raises(RemoteAPIError, match="timed out"):
                video.wait_video("v")
        else:
            with pytest.raises(RemoteAPIError):
                video.wait_video("v")

    def handler(req):
        if req.url.path.endswith("/videos"):
            return httpx.Response(
                200, json={"data": [{"id": "existing", "attributes": {"referenceName": name}}]}
            )
        return httpx.Response(200, json={"data": {"attributes": {"state": "APPROVED"}}})

    recorder = Recorder(handler)
    manager = AppleAppPreviews(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(recorder)), "123"
    )
    assert manager.ensure_video("lib", path, "00:00:01:00") == "existing"
    assert not any(req.method == "POST" for req in recorder.calls)


def test_scheduled_release_create_and_update(project):
    date = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0).isoformat()
    version = AppleVersion(
        platform="IOS", version="3.0", release_type="SCHEDULED", earliest_release_date=date
    )
    pub = ApplePublisher(
        APIClient(
            "https://api.test",
            lambda: "t",
            httpx.MockTransport(lambda r: httpx.Response(201, json={"data": {"id": "v"}})),
        ),
        project.apple,
    )
    assert pub.ensure_version(version, [], apply=False) is None
    assert pub.ensure_version(version, [], apply=True) == "v"
    current = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "3.0",
            "appVersionState": "PREPARE_FOR_SUBMISSION",
            "releaseType": "MANUAL",
        },
    }
    assert pub.synchronize_version_settings(version, current, apply=False)
    assert pub.synchronize_version_settings(version, current, apply=True)
    current["attributes"].update({"releaseType": "SCHEDULED", "earliestReleaseDate": date})
    assert pub.synchronize_version_settings(version, current, apply=False) == []
    current["attributes"]["appVersionState"] = "IN_REVIEW"
    current["attributes"]["releaseType"] = "MANUAL"
    with pytest.raises(UnsafeOperationError, match="not editable"):
        pub.synchronize_version_settings(version, current, apply=False)
    with pytest.raises(UnsafeOperationError, match="identity"):
        pub.synchronize_version_settings(
            version, {"attributes": {"platform": "TV_OS", "versionString": "3.0"}}, apply=False
        )
    incomplete = AppleVersion(platform="IOS", version="3.0", release_type="SCHEDULED")
    with pytest.raises(ConfigurationError, match="earliest_release_date"):
        pub.ensure_version(incomplete, [], apply=True)
    with pytest.raises(ConfigurationError, match="earliest_release_date"):
        pub.synchronize_version_settings(incomplete, current, apply=False)
    assert (
        pub.synchronize_version_settings(AppleVersion(platform="IOS", version="3.0"), current, apply=False)
        == []
    )
    with pytest.raises(ValidationError):
        AppleVersion(platform="IOS", version="3.0", release_type="SCHEDULED", earliest_release_date="bad")
    with pytest.raises(ValidationError):
        AppleVersion(platform="IOS", version="3.0", release_type="MANUAL", earliest_release_date=date)


def test_google_testers_sync_and_validation(project):
    def handler(req):
        if req.url.path.endswith("/edits"):
            return httpx.Response(201, json={"id": "edit1"})
        if req.url.path.endswith("/testers/closed"):
            return httpx.Response(200, json={"googleGroups": ["old@example.com"]})
        if req.url.path.endswith("/testers/internal"):
            return httpx.Response(200, json={"googleGroups": ["qa@example.com"]})
        return httpx.Response(200, json={})

    recorder = Recorder(handler)
    mgr = GoogleTesters(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(recorder)), "com.demo"
    )
    groups = [
        GoogleTesterGroup(track="closed", google_groups=["new@example.com"]),
        GoogleTesterGroup(track="internal", google_groups=["qa@example.com"]),
    ]
    assert mgr.synchronize(groups, apply=False) == ["Google testers closed: update 1 Google Groups"]
    assert any(req.method == "DELETE" and req.url.path.endswith("/edits/edit1") for req in recorder.calls)
    recorder.calls.clear()
    assert mgr.synchronize(groups, apply=True) == ["Google testers closed: update 1 Google Groups"]
    assert any(req.method == "PUT" for req in recorder.calls)
    assert any(req.url.path.endswith("/edits/edit1:commit") for req in recorder.calls)
    recorder.calls.clear()
    assert (
        mgr.synchronize([GoogleTesterGroup(track="internal", google_groups=["qa@example.com"])], apply=True)
        == []
    )
    assert any(req.method == "DELETE" for req in recorder.calls)
    assert mgr.synchronize([], apply=True) == []
    with pytest.raises(ValidationError):
        GoogleTesterGroup(track="closed", google_groups=["bad-email"])
    with pytest.raises(ValidationError):
        GoogleTesterGroup(track="closed", google_groups=["qa@example.com", "qa@example.com"])
    with pytest.raises(ValidationError):
        project.google.tester_groups = [
            GoogleTesterGroup(track="closed", google_groups=[]),
            GoogleTesterGroup(track="closed", google_groups=[]),
        ]


def test_google_testers_commit_error_aborts():
    def handler(req):
        if req.url.path.endswith("/edits"):
            return httpx.Response(200, json={"id": "edit"})
        if req.method == "GET":
            return httpx.Response(200, json={"googleGroups": []})
        if req.method == "PUT":
            return httpx.Response(403, text="no")
        return httpx.Response(200, json={})

    recorder = Recorder(handler)
    client = APIClient("https://api.test", lambda: "t", httpx.MockTransport(recorder))
    with pytest.raises(RemoteAPIError):
        GoogleTesters(client, "com.demo").synchronize(
            [GoogleTesterGroup(track="closed", google_groups=["x@example.com"])], apply=True
        )
    assert any(req.method == "DELETE" for req in recorder.calls)


def test_preview_local_validation(tmp_path, project):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    project.locales["en-US"].apple.app_previews = {"IPHONE": ["video.mp4"]}
    assert validate_project(project, tmp_path / "app.yaml", local_files="all") == []
    project.locales["en-US"].apple.app_previews = {"bad": ["video.mp4"]}
    assert any("placement group" in issue for issue in validate_project(project, tmp_path / "app.yaml"))
    project.locales["en-US"].apple.app_previews = {"IPHONE": ["missing.mp4"]}
    assert validate_project(project, tmp_path / "app.yaml")


def test_preview_additional_validations(tmp_path, monkeypatch, project):
    path = tmp_path / "preview.mp4"
    path.write_bytes(b"test")
    data = video_reference()
    data["videoSpecs"].insert(0, {"specId": "unrelated"})
    AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", data, inspection())
    data["videoSpecs"][1]["maxFileSize"] = 1
    with pytest.raises(ConfigurationError, match="does not meet"):
        AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", data, inspection())
    data["videoSpecs"][1]["maxFileSize"] = 10000
    data["videoSpecs"][1]["fileExtensions"] = [".mov"]
    with pytest.raises(ConfigurationError, match="does not meet"):
        AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", data, inspection())
    data["videoSpecs"][1]["fileExtensions"] = [".mp4"]
    with pytest.raises(ConfigurationError, match="invalid frame rate"):
        AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", data, inspection(fps="bad"))
    data["videoSpecs"][1].pop("frameRates")
    data["videoSpecs"][1].pop("duration")
    data["videoSpecs"][1].pop("audioRequired")
    assert AppleAppPreviews.validate_video(path, "IPHONE_PROFILE", data, inspection(audio=False)) is None
    for index in range(4):
        (tmp_path / f"clip{index}.mp4").write_bytes(b"test")
    project.locales["en-US"].apple.app_previews = {"IPHONE": [f"clip{index}.mp4" for index in range(4)]}
    assert any("three" in issue for issue in validate_project(project, tmp_path / "app.yaml"))
    project.locales["en-US"].apple.app_previews = {"IPHONE": ["preview.txt"]}
    (tmp_path / "preview.txt").write_text("text")
    assert any("extension" in issue for issue in validate_project(project, tmp_path / "app.yaml"))


def test_preview_timecode_in_upload(tmp_path):
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"abcd")
    records = []

    def handler(req):
        records.append(req)
        if req.url.path.endswith("/videos"):
            return httpx.Response(200, json={"data": []})
        if req.url.path.endswith("/appAssetLibraryVideos") and req.method == "POST":
            assert json.loads(req.content)["data"]["attributes"]["previewFrameTimeCode"] == "00:00:03:00"
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "v",
                        "attributes": {
                            "uploadOperations": [
                                {"method": "PUT", "url": "https://upload.test/put", "offset": 0, "length": 4}
                            ]
                        },
                    }
                },
            )
        return httpx.Response(200, json={"data": {"attributes": {"state": "APPROVED"}}})

    api = APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler))
    assert AppleAppPreviews(api, "123").ensure_video("lib", path, "00:00:03:00") == "v"


def test_scheduled_release_extra_validation(project):
    date = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    old_version = AppleVersion(
        platform="IOS", version="3.0", release_type="SCHEDULED", earliest_release_date=date
    )
    pub = ApplePublisher(
        APIClient(
            "https://api.test",
            lambda: "token",
            httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"id": "v"}})),
        ),
        project.apple,
    )
    with pytest.raises(UnsafeOperationError, match="future"):
        pub.ensure_version(old_version, [], apply=True)
    remote = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "3.0",
            "appVersionState": "PREPARE_FOR_SUBMISSION",
            "releaseType": "MANUAL",
        },
    }
    with pytest.raises(UnsafeOperationError, match="future"):
        pub.synchronize_version_settings(old_version, remote, apply=False)
    remote["attributes"].update({"releaseType": "SCHEDULED", "earliestReleaseDate": date})
    assert pub.synchronize_version_settings(old_version, remote, apply=False) == []
    date = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()
    with pytest.raises(ValidationError, match="timezone"):
        AppleVersion(platform="IOS", version="3.0", release_type="SCHEDULED", earliest_release_date=date)
    project.google.release.testers = ["existing@example.com"]
    with pytest.raises(ValidationError, match="track"):
        project.google.tester_groups = [GoogleTesterGroup(track="internal", google_groups=["a@example.com"])]


def test_apple_preview_synchronization_routes(project, tmp_path, monkeypatch):
    project.locales["en-US"].apple.app_previews = {"IPHONE_PROFILE": ["preview.mp4"]}
    events = []
    monkeypatch.setattr(
        AppleAppPreviews,
        "synchronize",
        lambda self, local, groups, directory, timecode=None, confirm_replacement=False: events.append(
            (local, groups)
        ),
    )
    state = {"exists": False, "locale": False}

    def handler(req):
        path = req.url.path
        if path == "/apps/123":
            return httpx.Response(200, json={"data": {"id": "123", "attributes": {"bundleId": "com.demo"}}})
        if path == "/apps/123/appStoreVersions":
            data = (
                [
                    {
                        "id": "version",
                        "attributes": {
                            "platform": "IOS",
                            "versionString": "2.0",
                            "appVersionState": "PREPARE_FOR_SUBMISSION",
                        },
                    }
                ]
                if state["exists"]
                else []
            )
            return httpx.Response(200, json={"data": data})
        if path == "/apps/123/appInfos":
            return httpx.Response(200, json={"data": [{"id": "info"}]})
        if path == "/appInfos/info/appInfoLocalizations":
            return httpx.Response(200, json={"data": []})
        if path == "/appStoreVersions/version/appStoreVersionLocalizations":
            data = [{"id": "localized", "attributes": {"locale": "en-US"}}] if state["locale"] else []
            return httpx.Response(200, json={"data": data})
        if req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "new"}})
        return httpx.Response(200, json={})

    record = Recorder(handler)
    pub = ApplePublisher(
        APIClient("https://api.test", lambda: "t", httpx.MockTransport(record)), project.apple
    )
    assert any("App Preview" in value for value in pub.synchronize(project, tmp_path, apply=False))
    state["exists"] = True
    assert any("App Preview" in value for value in pub.synchronize(project, tmp_path, apply=False))
    assert events == []
    assert any("App Preview" in value for value in pub.synchronize(project, tmp_path, apply=True))
    assert events[0][0] == "new"
    state["locale"] = True
    assert any("App Preview" in value for value in pub.synchronize(project, tmp_path, apply=True))
    assert events[-1][0] == "localized"


def test_additional_branch_coverage(project, tmp_path, monkeypatch):
    import app_publisher.cli as cli
    from app_publisher.cli import testers as command_testers
    from app_publisher.core.publication_engine import PublicationEngine
    from app_publisher.models.apple_version import AppleVersion

    project.google.tester_groups = [GoogleTesterGroup(track="closed", google_groups=["qa@example.com"])]
    engine = PublicationEngine(project, tmp_path / "app.yaml")

    class Handler:
        def __init__(self):
            self.config = project.google
            self.api = APIClient(
                "https://api.test",
                lambda: "token",
                httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={"id": "edit"} if request.url.path.endswith("/edits") else {"googleGroups": []},
                    )
                ),
            )

    handler = Handler()
    monkeypatch.setattr(engine, "google", lambda: handler)
    assert engine.testers(apply=False) == ["Google testers closed: update 1 Google Groups"]
    engine.project.google = None
    with pytest.raises(ConfigurationError, match="not configured"):
        engine.testers(apply=False)
    monkeypatch.setattr(cli, "open_engine", lambda config: engine)
    monkeypatch.setattr(engine, "testers", lambda apply: ["Google: testers"])
    assert command_testers(tmp_path / "app.yaml", apply=False) is None
    project.locales["en-US"].apple.app_previews = {"IPHONE": ["file.mp4"]}
    assert validate_project(project, tmp_path / "app.yaml", local_files="none") == []
    date = (datetime.now(UTC) + timedelta(days=40)).isoformat()
    version = AppleVersion(platform="IOS", version="4.0", release_type="AFTER_APPROVAL")
    publisher = ApplePublisher(
        APIClient(
            "https://api.test", lambda: "t", httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        ),
        project.apple,
    )
    remote = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "4.0",
            "appVersionState": "PREPARE_FOR_SUBMISSION",
            "releaseType": "MANUAL",
        },
    }
    assert publisher.synchronize_version_settings(version, remote, apply=False)
    assert AppleVersion(platform="IOS", version="4.0", release_type="SCHEDULED", earliest_release_date=date)


def test_preview_unmatched_reused_asset_and_duplicate_groups(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"movie")
    name = AppleAppPreviews.reference_name(media, None)

    def handler(req):
        if req.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "wrong", "attributes": {"referenceName": "unrelated"}},
                        {"id": "correct", "attributes": {"referenceName": name}},
                    ]
                },
            )
        return httpx.Response(200, json={"data": {"attributes": {"state": "APPROVED"}}})

    pub = AppleAppPreviews(APIClient("https://api.test", lambda: "t", httpx.MockTransport(handler)), "123")
    assert pub.ensure_video("lib", media, None) == "correct"


def test_video_doctor_checks_ffprobe(project, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import app_publisher.cli as cli
    from app_publisher.cli import app
    from app_publisher.core.publication_engine import PublicationEngine
    from app_publisher.toolchain.environment_doctor import EnvironmentDoctor

    project.locales["en-US"].apple.app_previews = {"IPHONE_PROFILE": ["video.mp4"]}
    checks = EnvironmentDoctor(
        lambda name: "/usr/bin/ffprobe" if name == "ffprobe" else None,
        operating_system="Linux",
        environment={},
    ).inspect(project, tmp_path)
    assert any(check.name == "ffprobe" and check.status == "OK" for check in checks)
    checks = EnvironmentDoctor(lambda name: None, operating_system="Linux", environment={}).inspect(
        project, tmp_path
    )
    assert any(check.name == "ffprobe" and check.status == "MISSING" for check in checks)
    monkeypatch.setattr(cli, "open_engine", lambda path: PublicationEngine(project, tmp_path / "app.yaml"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    result = CliRunner().invoke(app, ["doctor", str(tmp_path / "app.yaml")])
    assert result.exit_code == 1
    assert "ffprobe" in result.stdout
