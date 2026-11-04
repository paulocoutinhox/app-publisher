from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app_publisher import cli
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_purchase_option_deletion import GooglePurchaseOptionDeletion
from app_publisher.models.google_purchase_option_state import GooglePurchaseOptionState
from app_publisher.models.screenshot_action import ScreenshotAction
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.providers.google_purchase_options import GooglePurchaseOptions
from app_publisher.screenshots.screenshot_navigator import ScreenshotNavigator
from app_publisher.screenshots.screenshot_planner import ScreenshotPlanner
from app_publisher.toolchain.environment_doctor import EnvironmentDoctor


class PurchaseAPI:
    def __init__(self, options=None, package="com.example.app", product="item"):
        self.options = options if options is not None else [{"purchaseOptionId": "buy", "state": "INACTIVE"}]
        self.package = package
        self.product = product
        self.calls = []

    def request(self, method, path, *, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            return {"packageName": self.package, "productId": self.product, "purchaseOptions": self.options}
        return {}


def test_purchase_option_state_sync_and_missing_entries():
    api = PurchaseAPI()
    provider = GooglePurchaseOptions(api, "com.example.app")
    states = [GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="ACTIVE")]
    assert provider.synchronize(states, apply=False) == ["Google purchase option: active item/buy"]
    assert api.calls[-1][0] == "GET"
    assert provider.synchronize(states, apply=True) == ["Google purchase option: active item/buy"]
    _, endpoint, payload = api.calls[-1]
    assert endpoint.endswith("/purchaseOptions:batchUpdateStates")
    assert payload == {
        "requests": [
            {
                "activatePurchaseOptionRequest": {
                    "packageName": "com.example.app",
                    "productId": "item",
                    "purchaseOptionId": "buy",
                }
            }
        ]
    }
    assert (
        provider.synchronize(
            [GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="INACTIVE")],
            apply=True,
        )
        == []
    )
    with pytest.raises(UnsafeOperationError, match="Unknown purchase option"):
        provider.synchronize(
            [GooglePurchaseOptionState(product_id="item", purchase_option_id="absent", state="ACTIVE")],
            apply=True,
        )
    api.options = [{"purchaseOptionId": "buy", "state": "ACTIVE"}]
    assert provider.synchronize(
        [GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="INACTIVE")], apply=True
    ) == ["Google purchase option: inactive item/buy"]
    assert "deactivatePurchaseOptionRequest" in api.calls[-1][2]["requests"][0]


def test_purchase_option_state_identity_and_batch():
    api = PurchaseAPI(package="other")
    provider = GooglePurchaseOptions(api, "com.example.app")
    with pytest.raises(UnsafeOperationError, match="identity differs"):
        provider.synchronize(
            [GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="ACTIVE")],
            apply=False,
        )
    api = PurchaseAPI(options=[{"purchaseOptionId": f"option-{i}", "state": "INACTIVE"} for i in range(102)])
    provider = GooglePurchaseOptions(api, "com.example.app")
    states = [
        GooglePurchaseOptionState(product_id="item", purchase_option_id=f"option-{i}", state="ACTIVE")
        for i in range(102)
    ]
    assert len(provider.synchronize(states, apply=True)) == 102
    assert [len(call[2]["requests"]) for call in api.calls if call[0] == "POST"] == [100, 2]


def test_explicit_purchase_option_deletion():
    api = PurchaseAPI()
    provider = GooglePurchaseOptions(api, "com.example.app")
    pending = [GooglePurchaseOptionDeletion(product_id="item", purchase_option_id="buy")]
    with pytest.raises(UnsafeOperationError, match="confirm_deletion"):
        provider.delete(pending, apply=False)
    entries = [
        GooglePurchaseOptionDeletion(
            product_id="item", purchase_option_id="buy", confirm_deletion=True, force=True
        )
    ]
    assert provider.delete(entries, apply=False) == ["Google purchase option: delete item/buy"]
    assert len(api.calls) == 1
    assert provider.delete(entries, apply=True) == ["Google purchase option: delete item/buy"]
    assert api.calls[-1][2]["requests"][0]["force"] is True
    api.options = []
    assert provider.delete(entries, apply=True) == []
    api.options = [{"purchaseOptionId": "buy"}, {"purchaseOptionId": "buy"}]
    with pytest.raises(UnsafeOperationError, match="duplicate"):
        provider.delete(entries, apply=True)
    api.package = "wrong"
    with pytest.raises(UnsafeOperationError, match="identity mismatch"):
        provider.delete(entries, apply=True)


def test_purchase_option_configurations(project):
    project.google.purchase_option_states = [
        GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="ACTIVE")
    ]
    with pytest.raises(ValidationError, match="one configuration"):
        project.google.purchase_option_deletions = [
            GooglePurchaseOptionDeletion(product_id="item", purchase_option_id="buy")
        ]
    project.google.purchase_option_deletions = []
    with pytest.raises(ValidationError, match="unique identifiers"):
        project.google.purchase_option_states = [
            project.google.purchase_option_states[0],
            project.google.purchase_option_states[0],
        ]
    project.google.purchase_option_states = []
    with pytest.raises(ValidationError, match="unique identifiers"):
        project.google.purchase_option_deletions = [
            GooglePurchaseOptionDeletion(product_id="item", purchase_option_id="buy"),
            GooglePurchaseOptionDeletion(product_id="item", purchase_option_id="buy"),
        ]


def test_engine_purchase_option_route(project, tmp_path, monkeypatch):
    project.google.purchase_option_states = [
        GooglePurchaseOptionState(product_id="item", purchase_option_id="buy", state="ACTIVE")
    ]
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    api = PurchaseAPI(package="com.demo")
    google = SimpleNamespace(api=api, synchronize=lambda *_args, **_kwargs: [], config=project.google)
    api.close = lambda: None
    monkeypatch.setattr(engine, "google", lambda: google)
    assert engine.synchronize(apply=False, provider="google") == ["Google purchase option: active item/buy"]
    assert engine.delete_purchase_options(apply=False) == []
    project.google.purchase_option_states = []
    project.google.purchase_option_deletions = [
        GooglePurchaseOptionDeletion(product_id="item", purchase_option_id="buy", confirm_deletion=True)
    ]
    assert engine.delete_purchase_options(apply=False) == ["Google purchase option: delete item/buy"]
    project.google = None
    with pytest.raises(ConfigurationError, match="Google Play"):
        engine.delete_purchase_options(apply=False)


def test_purchase_options_cli(monkeypatch):
    monkeypatch.setattr(
        cli,
        "open_engine",
        lambda _: SimpleNamespace(delete_purchase_options=lambda **kwargs: [str(kwargs["apply"])]),
    )
    values = []
    monkeypatch.setattr(cli, "show_changes", values.extend)
    cli.delete_purchase_options(Path("example.yaml"), apply=True)
    assert values == ["True"]


def test_idb_schema_and_commands():
    kinds = [
        {"kind": "tap", "x": 1, "y": 2},
        {"kind": "swipe", "x": 1, "y": 2, "end_x": 3, "end_y": 4, "duration_ms": 1500},
        {"kind": "text", "value": "ola 😀"},
        {"kind": "launch", "value": "com.example.app"},
        {"kind": "terminate", "value": "com.example.app"},
        {"kind": "open_url", "value": "example://home"},
        {"kind": "tap_element", "value": "next"},
        {"kind": "wait_element", "value": "next"},
        {"kind": "hinge", "angle": 130},
        {"kind": "remote", "value": "select"},
        {"kind": "rotate", "value": "LANDSCAPE_LEFT"},
        {"kind": "shake"},
        {"kind": "pinch", "x": 5, "y": 10, "scale": 0.5},
    ]
    commands = [ScreenshotNavigator.idb("target", ScreenshotAction(**item)) for item in kinds]
    assert all(command[-2:] == ["--udid", "target"] for command in commands)
    assert commands[1] == ["idb", "ui", "swipe", "1", "2", "3", "4", "--duration", "1.5", "--udid", "target"]
    assert commands[2][:3] == ["idb", "ui", "text"]
    assert commands[8][:3] == ["idb", "hinge", "130"]
    assert commands[9][1:3] == ["ui", "remote"]
    with pytest.raises(ConfigurationError, match="Unsupported idb"):
        ScreenshotNavigator.idb("target", ScreenshotAction(kind="wait", seconds=0.1))
    for item in [{"kind": "remote", "value": "invalid"}, {"kind": "rotate", "value": "UNKNOWN"}]:
        with pytest.raises(ValidationError):
            ScreenshotAction(**item)
    for platform in ["android", "macos", "watchos", "visionos"]:
        with pytest.raises(ValidationError, match="currently supports"):
            ScreenshotPlan(
                driver="idb",
                platform=platform,
                device="target",
                scenes=[{"name": "a", "url": "example://a", "output": "shot.png"}],
            )
    with pytest.raises(ValidationError, match="not supported"):
        ScreenshotPlan(
            driver="idb",
            platform="tvos",
            device="target",
            scenes=[
                {
                    "name": "a",
                    "url": "example://a",
                    "output": "shot.png",
                    "actions": [{"kind": "tap", "x": 1, "y": 2}],
                }
            ],
        )


def test_idb_screenshot_plan_and_tool_diagnosis(project, tmp_path):
    calls = []

    def runner(command, **_options):
        calls.append(command)
        if "screenshot" in command:
            Path(command[2]).write_bytes(b"fake-png")
        return SimpleNamespace(stdout=b"")

    with pytest.raises(ValidationError, match="not supported"):
        ScreenshotPlan(
            platform="ios",
            driver="idb",
            device="device-1",
            scenes=[
                {
                    "name": "home",
                    "url": "example://home",
                    "output": "screens/home.png",
                    "actions": [{"kind": "remote", "value": "select"}],
                }
            ],
        )
    plan = ScreenshotPlan(
        platform="ios",
        driver="idb",
        device="device-1",
        scenes=[
            {
                "name": "home",
                "url": "example://home",
                "output": "screens/home.png",
                "delay_seconds": 0,
                "actions": [{"kind": "tap", "x": 10, "y": 20}, {"kind": "wait", "seconds": 0.1}],
            }
        ],
    )
    results = ScreenshotPlanner(runner, lambda _: None).run(plan, tmp_path)
    assert results == [tmp_path / "screens/home.png"]
    assert calls[0] == ["idb", "open", "example://home", "--udid", "device-1"]
    assert calls[-1][-2:] == ["--udid", "device-1"]
    project.publication.screenshot_plans = [plan]
    checks = EnvironmentDoctor(finder=lambda name: "/bin/true", operating_system="Darwin").inspect(
        project, tmp_path
    )
    assert any(check.name == "idb" and check.status == "OK" for check in checks)
    with pytest.raises(ConfigurationError, match="PNG"):
        ScreenshotPlanner(runner, lambda _: None).run(
            ScreenshotPlan(
                platform="ios",
                driver="idb",
                device="device-1",
                scenes=[{"name": "x", "url": "example://x", "output": "x.jpg"}],
            ),
            tmp_path,
        )
    with pytest.raises(UnsafeOperationError, match="did not generate"):
        ScreenshotPlanner(lambda *_args, **_kwargs: SimpleNamespace(stdout=b""), lambda _: None).run(
            plan, tmp_path / "nowhere"
        )
    with pytest.raises(ConfigurationError, match="Path escapes"):
        ScreenshotPlanner(runner, lambda _: None).run(
            ScreenshotPlan(
                platform="ios",
                driver="idb",
                device="device-1",
                scenes=[{"name": "x", "url": "example://x", "output": "../outside.png"}],
            ),
            tmp_path,
        )


def test_idb_navigator_execution():
    calls = []
    navigator = ScreenshotNavigator(lambda command, **_options: calls.append(command))
    navigator.execute("ios", "udid", ScreenshotAction(kind="hinge", angle=180), driver="idb")
    assert calls == [["idb", "hinge", "180", "--udid", "udid"]]
