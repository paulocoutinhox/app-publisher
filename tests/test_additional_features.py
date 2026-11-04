import httpx
import pytest
from conftest import Recorder
from pydantic import ValidationError

from app_publisher.core.api_client import APIClient
from app_publisher.core.assets import resolve_assets
from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_accessibility_declaration import AppleAccessibilityDeclaration
from app_publisher.models.apple_config import AppleConfig
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_country_targeting import GoogleCountryTargeting
from app_publisher.models.google_release import GoogleRelease
from app_publisher.providers.apple_accessibility import AppleAccessibility
from app_publisher.providers.apple_launch import AppleLaunch
from app_publisher.providers.google_publisher import GooglePublisher


def test_accessibility_create_publish_and_noop():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [], "links": {}})
        return httpx.Response(201, json={"data": {"id": "new"}})

    manager = AppleAccessibility(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler)), "app-id"
    )
    declared = [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=True, publish=True)]
    assert manager.synchronize(declared, apply=False) == ["Apple accessibility IPHONE: create and publish"]
    assert len(requests) == 1
    assert manager.synchronize(declared, apply=True) == ["Apple accessibility IPHONE: create and publish"]
    assert requests[-2].method == "POST"
    assert requests[-1].method == "PATCH"
    assert manager.synchronize([], apply=True) == []


def test_accessibility_update_and_published_rejection():
    state = {"state": "DRAFT"}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "decl",
                            "attributes": {
                                "deviceFamily": "MAC",
                                "state": state["state"],
                                "supportsVoiceover": False,
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    manager = AppleAccessibility(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler)), "app"
    )
    declared = [AppleAccessibilityDeclaration(device_family="MAC", voiceover=True, publish=True)]
    result = manager.synchronize(declared, apply=True)
    assert len(result) == 2
    state["state"] = "PUBLISHED"
    with pytest.raises(UnsafeOperationError, match="published"):
        manager.synchronize(declared, apply=False)
    unchanged = [AppleAccessibilityDeclaration(device_family="MAC", voiceover=False, publish=True)]
    assert manager.synchronize(unchanged, apply=True) == []


def test_accessibility_duplicate_and_invalid_input():
    manager = AppleAccessibility(
        APIClient(
            "https://api.test",
            lambda: "token",
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "1", "attributes": {"deviceFamily": "IPAD", "state": "DRAFT"}},
                            {"id": "2", "attributes": {"deviceFamily": "IPAD", "state": "DRAFT"}},
                        ]
                    },
                )
            ),
        ),
        "app",
    )
    with pytest.raises(RemoteAPIError, match="Duplicate"):
        manager.synchronize([AppleAccessibilityDeclaration(device_family="IPAD", captions=True)], apply=False)
    with pytest.raises(ValidationError, match="explicit support values"):
        AppleAccessibilityDeclaration(device_family="IPAD")


def test_accessibility_replaced_record_is_ignored():
    manager = AppleAccessibility(
        APIClient(
            "https://api.test",
            lambda: "token",
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "old", "attributes": {"deviceFamily": "IPAD", "state": "REPLACED"}},
                            {
                                "id": "new",
                                "attributes": {
                                    "deviceFamily": "IPAD",
                                    "state": "PUBLISHED",
                                    "supportsCaptions": True,
                                },
                            },
                        ]
                    },
                )
            ),
        ),
        "app",
    )
    assert (
        manager.synchronize([AppleAccessibilityDeclaration(device_family="IPAD", captions=True)], apply=False)
        == []
    )


def test_apple_launch_phased_and_manual():
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(201, json={"data": {"id": "new"}})

    manager = AppleLaunch(APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler)))
    version = AppleVersion(platform="IOS", version="2.0", phased_release=True, manual_release=True)
    remote = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "2.0",
            "appVersionState": "PENDING_DEVELOPER_RELEASE",
        },
    }
    assert len(manager.launch(version, remote, apply=False)) == 2
    assert len(manager.launch(version, remote, apply=True)) == 2
    assert any(request.url.path.endswith("appStoreVersionPhasedReleases") for request in calls)
    assert any(request.url.path.endswith("appStoreVersionReleaseRequests") for request in calls)


def test_apple_launch_guards_and_existing_phased():
    manager = AppleLaunch(
        APIClient(
            "https://api.test",
            lambda: "token",
            httpx.MockTransport(lambda request: httpx.Response(200, json={"data": {"id": "phase"}})),
        )
    )
    version = AppleVersion(platform="IOS", version="1", phased_release=True)
    remote = {
        "id": "v",
        "attributes": {"platform": "IOS", "versionString": "1", "appVersionState": "READY_FOR_DISTRIBUTION"},
    }
    assert manager.launch(version, remote, apply=True) == []
    with pytest.raises(UnsafeOperationError, match="identity"):
        manager.launch(
            version, {**remote, "attributes": {**remote["attributes"], "platform": "MAC_OS"}}, apply=False
        )
    version.manual_release = True
    version.release_type = "SCHEDULED"
    with pytest.raises(UnsafeOperationError, match="MANUAL"):
        manager.launch(version, remote, apply=False)
    version.release_type = "MANUAL"
    with pytest.raises(UnsafeOperationError, match="PENDING_DEVELOPER_RELEASE"):
        manager.launch(version, remote, apply=False)
    version.manual_release = False
    with pytest.raises(UnsafeOperationError, match="phased release"):
        AppleLaunch(
            APIClient("https://api.test", lambda: "t", httpx.MockTransport(lambda req: httpx.Response(404)))
        ).launch(version, remote, apply=False)
    with pytest.raises(RemoteAPIError):
        AppleLaunch(
            APIClient(
                "https://api.test",
                lambda: "t",
                httpx.MockTransport(lambda req: httpx.Response(503)),
                retries=0,
            )
        ).read_phased_release("v")


def test_google_country_targeting_and_release_options(project, tmp_path):
    project.google.release = GoogleRelease(
        track="production",
        status="inProgress",
        rollout_fraction=0.25,
        version_codes=["111"],
        name="App update",
        in_app_update_priority=3,
        country_targeting=GoogleCountryTargeting(countries=["BR", "US"], include_rest_of_world=False),
    )
    recorder = Recorder(
        lambda request: httpx.Response(
            200, json={"id": "e"} if request.method == "POST" and request.url.path.endswith("/edits") else {}
        )
    )
    manager = GooglePublisher(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(recorder)), project.google
    )
    manager.publish_release(tmp_path, {}, apply=True)
    update = next(request for request in recorder.calls if request.method == "PUT")
    body = __import__("json").loads(update.content)
    assert body["releases"][0]["countryTargeting"]["countries"] == ["BR", "US"]
    assert body["releases"][0]["inAppUpdatePriority"] == 3
    assert body["releases"][0]["name"] == "App update"
    with pytest.raises(ValidationError, match="Country targeting requires"):
        GoogleRelease(
            track="internal",
            status="inProgress",
            rollout_fraction=0.2,
            country_targeting=GoogleCountryTargeting(countries=["US"]),
        )
    with pytest.raises(ValidationError, match="unique uppercase"):
        GoogleCountryTargeting(countries=["br", "US"])
    with pytest.raises(ValidationError, match="unique uppercase"):
        GoogleCountryTargeting(countries=["US", "US"])


def test_project_paths_reject_escape_and_symlink(tmp_path):
    assert project_path(tmp_path, "sub/example.png") == tmp_path / "sub/example.png"
    for path in ["../other", tmp_path / "absolute.txt", "./"]:
        with pytest.raises(ConfigurationError):
            project_path(tmp_path, path)
    (tmp_path / "link").symlink_to(tmp_path.parent)
    with pytest.raises(ConfigurationError):
        project_path(tmp_path, "link/secret.png")
    with pytest.raises(ConfigurationError):
        resolve_assets(tmp_path, ["../*.png"])


def test_accessibility_branch_paths():
    state = {"items": []}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": state["items"]})
        return httpx.Response(200, json={"data": {"id": "new"}})

    manager = AppleAccessibility(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler)), "app"
    )
    assert manager.synchronize(
        [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=False)], apply=True
    ) == ["Apple accessibility IPHONE: create"]
    state["items"] = [
        {"id": "d", "attributes": {"deviceFamily": "IPHONE", "state": "DRAFT", "supportsVoiceover": True}}
    ]
    desired = [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=False, publish=True)]
    assert len(manager.synchronize(desired, apply=False)) == 2
    assert (
        manager.synchronize(
            [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=True, publish=False)], apply=True
        )
        == []
    )
    assert manager.synchronize(
        [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=True, publish=True)], apply=False
    ) == ["Apple accessibility IPHONE: publish"]


def test_apple_launch_without_phased_and_empty():
    manager = AppleLaunch(
        APIClient(
            "https://api.test", lambda: "token", httpx.MockTransport(lambda req: httpx.Response(200, json={}))
        )
    )
    version = AppleVersion(platform="IOS", version="1", manual_release=True)
    remote = {
        "id": "v",
        "attributes": {
            "platform": "IOS",
            "versionString": "1",
            "appVersionState": "PENDING_DEVELOPER_RELEASE",
        },
    }
    assert manager.launch(version, remote, apply=False) == ["Apple IOS 1: release approved version"]
    version.manual_release = False
    assert manager.launch(version, remote, apply=False) == []


def test_engine_new_capabilities(project, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app_publisher.core.publication_engine import PublicationEngine

    engine = PublicationEngine(project, tmp_path / "app.yaml")
    project.apple.accessibility = [AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=True)]
    store = SimpleNamespace(
        api=SimpleNamespace(close=lambda: None),
        identify=lambda: None,
        versions=lambda: [{"id": "v", "attributes": {"platform": "IOS", "versionString": "2.0"}}],
        synchronize=lambda *args, **kwargs: ["metadata"],
    )
    monkeypatch.setattr(engine, "apple", lambda: store)
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleAccessibility.synchronize",
        lambda *args, **kwargs: ["accessibility"],
    )
    assert "accessibility" in engine.synchronize(apply=False, provider="apple")
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleLaunch.launch", lambda *args, **kwargs: ["released"]
    )
    assert engine.launch(apply=False) == []
    project.apple.versions[0].manual_release = True
    assert engine.launch(apply=False) == ["released"]
    store.versions = lambda: []
    with pytest.raises(UnsafeOperationError, match="exactly one"):
        engine.launch(apply=False)
    project.apple = None
    with pytest.raises(ConfigurationError, match="launch requires"):
        engine.launch(apply=False)


def test_apple_duplicate_accessibility_validation(project):
    a = AppleAccessibilityDeclaration(device_family="IPHONE", voiceover=True)
    with pytest.raises(ValidationError, match="must be unique"):
        AppleConfig.model_validate(
            {**project.apple.model_dump(), "accessibility": [a.model_dump(), a.model_dump()]}
        )


def test_cli_launch_entry(monkeypatch):
    from types import SimpleNamespace

    from app_publisher import cli

    actions = []
    monkeypatch.setattr(cli, "open_engine", lambda _: SimpleNamespace(launch=lambda **kwargs: ["ok"]))
    monkeypatch.setattr(cli, "show_changes", lambda data: actions.extend(data))
    cli.launch(__import__("pathlib").Path("app.yaml"), apply=False)
    assert actions == ["ok"]


def test_apple_territory_uses_v2_api():
    from app_publisher.providers.apple_commercial import AppleCommercial
    from app_publisher.providers.store_availability import StoreAvailability

    def handler(req):
        if req.url.path == "/v1/apps/123/appAvailabilityV2":
            return httpx.Response(200, json={"data": {"id": "availability"}})
        if req.url.path == "/v2/appAvailabilities/availability/territoryAvailabilities":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "r",
                            "attributes": {"available": False, "preOrderEnabled": True},
                            "relationships": {"territory": {"data": {"id": "BRA"}}},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    client = APIClient("https://api.test/v1", lambda: "t", httpx.MockTransport(handler))
    assert StoreAvailability(client).apple("123", {"BRA": False}) == [
        "Apple availability: verified 1 declared territories"
    ]
    assert AppleCommercial(client, "123").synchronize_territories({"BRA": True}, apply=False) == [
        "Apple availability: set BRA to True"
    ]


def test_google_rollout_fraction_rejects_full_release():
    with pytest.raises(ValidationError):
        GoogleRelease(track="production", status="inProgress", rollout_fraction=1, version_codes=["1"])
