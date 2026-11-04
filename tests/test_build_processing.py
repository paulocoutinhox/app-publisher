from types import SimpleNamespace

import httpx
import pytest
import yaml
from test_reconciliation import PlannedEngine
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.api_client import APIClient
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.core.sync_plan import apply_plan, generate_plan
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_version import AppleVersion
from app_publisher.providers.apple_build_manager import AppleBuildManager


def manager_for(states, *, duplicate=False, wrong_identity=False):
    sequence = iter(states)

    def handler(request):
        if request.url.path.endswith("/preReleaseVersion"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "attributes": {"version": "wrong" if wrong_identity else "1.0.0", "platform": "IOS"}
                    }
                },
            )
        state = next(sequence)
        data = (
            []
            if state is None
            else [{"id": "build", "attributes": {"version": "7", "processingState": state}}]
        )
        if duplicate:
            data *= 2
        return httpx.Response(200, json={"data": data})

    client = APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler))
    clock = [0.0]
    return AppleBuildManager(
        client, "123", clock=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)
    )


def test_wait_transitions_and_failures():
    version = AppleVersion(platform="IOS", version="1.0.0", build_number="7")
    assert manager_for([None, "PROCESSING", "VALID"]).wait(version)["id"] == "build"
    for state, message in (("FAILED", "FAILED"), ("INVALID", "INVALID")):
        with pytest.raises(UnsafeOperationError, match=message):
            manager_for([state]).wait(version)
    with pytest.raises(RemoteAPIError, match="unknown"):
        manager_for(["UNKNOWN"]).wait(version)
    with pytest.raises(UnsafeOperationError, match="timeout"):
        manager_for([None, None]).wait(version, timeout=1)
    for timeout, interval in ((0, 1), (1, 0), (1, 31)):
        with pytest.raises(ConfigurationError):
            manager_for([]).wait(version, timeout=timeout, interval=interval)
    with pytest.raises(UnsafeOperationError, match="multiple"):
        manager_for(["VALID"], duplicate=True).find(version)
    with pytest.raises(UnsafeOperationError, match="marketing version"):
        manager_for(["VALID"], wrong_identity=True).find(version)
    with pytest.raises(ConfigurationError, match="explicit"):
        manager_for([]).find(AppleVersion(platform="IOS", version="1.0.0"))
    with pytest.raises(UnsafeOperationError, match="VALID"):
        AppleBuildManager.require_valid({"attributes": {"processingState": "PROCESSING"}})
    with pytest.raises(UnsafeOperationError, match="expired"):
        AppleBuildManager.require_valid({"attributes": {"processingState": "VALID", "expired": True}})


def test_plan_preview_never_applies(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("fixture")
    engine = PlannedEngine(project, file)
    saved = generate_plan(engine)
    engine.calls.clear()
    assert apply_plan(engine, saved) == engine.changes
    assert engine.calls == [("synchronize", False, "all")]


def test_new_engine_commands(project, tmp_path, monkeypatch):
    engine = PublicationEngine(project, tmp_path / "app.yaml")
    project.apple.versions[0].build_number = "7"
    api = manager_for(["VALID"]).api
    monkeypatch.setattr(engine, "apple", lambda: SimpleNamespace(api=api, identify=lambda: None))
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.AppleBuildManager.wait",
        lambda *args, **kwargs: {"id": "build"},
    )
    assert "VALID" in engine.wait()[0]
    monkeypatch.setattr(
        "app_publisher.core.publication_engine.CrashlyticsPublisher.upload",
        lambda *args, **kwargs: ["symbols"],
    )
    assert engine.symbols(apply=False) == ["symbols"]
    project.apple = None
    with pytest.raises(ConfigurationError, match="Apple"):
        engine.wait()
    project.firebase = None
    with pytest.raises(ConfigurationError, match="Firebase"):
        engine.symbols(apply=False)


def test_new_cli_commands(project, tmp_path, monkeypatch):
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(project.model_dump(mode="json")))
    monkeypatch.setattr(PublicationEngine, "wait", lambda *args, **kwargs: ["ready"])
    monkeypatch.setattr(PublicationEngine, "symbols", lambda *args, **kwargs: ["symbols"])
    runner = CliRunner()
    assert runner.invoke(app, ["wait", str(path)]).exit_code == 0
    assert runner.invoke(app, ["symbols", str(path)]).exit_code == 0
    assert runner.invoke(app, ["schema"]).exit_code == 0
