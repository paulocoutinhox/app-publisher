import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.workflow_journal import WorkflowJournal
from app_publisher.core.workflow_runner import WorkflowRunner
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.workflow_config import WorkflowConfig
from app_publisher.models.workflow_state import WorkflowState
from app_publisher.models.workflow_step import WorkflowStep


@pytest.fixture
def workflow_engine(project, tmp_path):
    file = tmp_path / "app.yaml"
    file.write_text("fixture config")
    project.publication.workflow = WorkflowConfig(
        journal="private/workflow-journal.json",
        source_inputs=["source/*.txt"],
        steps=[{"id": "verify", "action": "validate"}, {"id": "metadata", "action": "sync"}],
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.txt").write_text("fixture source")
    calls = []
    engine = SimpleNamespace(project=project, directory=tmp_path, file=file, calls=calls)

    def validated(**kwargs):
        calls.append(("validate", kwargs))

    engine.validate = validated

    def synchronized(**kwargs):
        calls.append(("sync", kwargs))
        return ["metadata updated"]

    engine.synchronize = synchronized
    return engine


def test_workflow_preview_resume_and_file_permissions(workflow_engine, tmp_path):
    runner = WorkflowRunner(workflow_engine)
    preview = runner.run(apply=False)
    assert len(preview) == 2
    assert not (tmp_path / "private").exists()
    assert runner.run(apply=True) == ["Configuration validated", "metadata updated"]
    assert len(workflow_engine.calls) == 2
    journal = tmp_path / "private/workflow-journal.json"
    if os.name == "posix":
        assert journal.stat().st_mode & 0o777 == 0o600
    assert not journal.with_suffix(".lock").exists()
    assert len(runner.run(apply=True, resume=True)) == 2
    assert len(workflow_engine.calls) == 2
    with pytest.raises(UnsafeOperationError, match="already exists"):
        runner.run(apply=True)


@pytest.mark.parametrize("changed", ["yaml", "source", "artifact"])
def test_workflow_rejects_changed_inputs(workflow_engine, tmp_path, changed):
    workflow_engine.project.apple.versions[0].build_number = "7"
    workflow_engine.project.apple.versions[0].artifact = Path("app.ipa")
    (tmp_path / "app.ipa").write_bytes(b"fixture artifact")
    runner = WorkflowRunner(workflow_engine)
    runner.run(apply=True)
    target = {
        "yaml": tmp_path / "app.yaml",
        "source": tmp_path / "source/app.txt",
        "artifact": tmp_path / "app.ipa",
    }[changed]
    target.write_text("changed")
    with pytest.raises(UnsafeOperationError, match="changed"):
        runner.run(apply=True, resume=True)


def test_workflow_partial_stage_records_and_explicit_retry(workflow_engine, tmp_path):
    def failed(**kwargs):
        raise UnsafeOperationError("secret=hidden-token")

    workflow_engine.synchronize = failed
    runner = WorkflowRunner(workflow_engine)
    with pytest.raises(UnsafeOperationError):
        runner.run(apply=True)
    journal = tmp_path / "private/workflow-journal.json"
    state = json.loads(journal.read_text())
    assert state["active_step"] == "metadata"
    assert state["failure_type"] == "UnsafeOperationError"
    assert "hidden-token" not in journal.read_text()
    with pytest.raises(UnsafeOperationError, match="partially"):
        runner.run(apply=True, resume=True)
    workflow_engine.synchronize = lambda **kwargs: ["done"]
    assert runner.run(apply=True, resume=True, retry_failed=True) == [
        "Workflow verify: already completed",
        "done",
    ]
    assert json.loads(journal.read_text())["active_step"] is None


def test_workflow_unknown_stage_and_missing_configuration(workflow_engine, tmp_path):
    runner = WorkflowRunner(workflow_engine)
    runner.run(apply=True)
    journal = tmp_path / "private/workflow-journal.json"
    state = json.loads(journal.read_text())
    state["completed"]["unknown"] = []
    journal.write_text(json.dumps(state))
    with pytest.raises(UnsafeOperationError, match="unknown"):
        runner.run(apply=True, resume=True)
    state["completed"].pop("unknown")
    state["active_step"] = "unknown"
    journal.write_text(json.dumps(state))
    with pytest.raises(UnsafeOperationError, match="unknown"):
        runner.run(apply=True, resume=True, retry_failed=True)
    workflow_engine.project.publication.workflow = None
    with pytest.raises(ConfigurationError, match="No publishing"):
        runner.run(apply=False)


def test_workflow_source_and_artifact_boundaries(workflow_engine, tmp_path):
    runner = WorkflowRunner(workflow_engine)
    workflow_engine.project.publication.workflow.source_inputs = ["absent/*.txt"]
    with pytest.raises(ConfigurationError, match="no files"):
        runner.run(apply=True)
    assert not (tmp_path / "private/workflow-journal.lock").exists()
    google = workflow_engine.project.google
    workflow_engine.project.apple = None
    workflow_engine.project.google = None
    workflow_engine.project.publication.screenshot_plans = [
        {
            "platform": "ios",
            "device": "id",
            "scenes": [{"name": "home", "url": "app://home", "output": "shots/home.png"}],
        }
    ]
    workflow_engine.project.publication.screenshot_designs = [
        {
            "source": "shots/home.png",
            "output": "shots/art.png",
            "font": "font.ttf",
            "title": "Demo",
            "width": 1200,
            "height": 1600,
        }
    ]
    assert runner.artifacts() == {}
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots/home.png").write_bytes(b"fixture")
    assert "shots/home.png" in runner.artifacts()
    workflow_engine.project.google = google
    google.release.artifact = Path("android.aab")
    (tmp_path / "android.aab").write_bytes(b"fixture")
    assert "android.aab" in runner.artifacts()


def test_journal_lock_symlink_size_and_invalid_data(tmp_path):
    journal = WorkflowJournal(tmp_path, Path("state/run-journal.json"))
    journal.acquire()
    with pytest.raises(UnsafeOperationError, match="locked"):
        journal.acquire()
    journal.release()
    with pytest.raises(ConfigurationError, match="missing"):
        journal.load()
    journal.path.write_text("invalid JSON")
    with pytest.raises(ConfigurationError, match="invalid"):
        journal.load()
    journal.path.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ConfigurationError, match="size"):
        journal.load()
    journal.save(WorkflowState(config_sha256="hash", source_hashes={}))
    assert journal.load().config_sha256 == "hash"
    link = tmp_path / "linked-journal.json"
    link.symlink_to(journal.path)
    with pytest.raises(UnsafeOperationError, match="symbolic"):
        WorkflowJournal(tmp_path, link.relative_to(tmp_path))


def test_workflow_models_require_unique_steps_and_valid_providers():
    with pytest.raises(ValidationError, match="unique"):
        WorkflowConfig(
            journal="journal.json",
            steps=[{"id": "same", "action": "build"}, {"id": "same", "action": "sync"}],
        )
    with pytest.raises(ValidationError, match="Apple provider"):
        WorkflowStep(id="wait", action="wait", provider="google")
    with pytest.raises(ValidationError, match="only for sync"):
        WorkflowStep(id="build", action="build", provider="firebase")
    assert WorkflowStep(id="firebase", action="SYNC", provider="FIREBASE").provider == "firebase"


def test_explicit_action_dispatch_and_cli(workflow_engine, monkeypatch, tmp_path):
    runner = WorkflowRunner(workflow_engine)
    actions = {
        "build": "build",
        "symbols": "symbols",
        "capture": "screenshots",
        "render": "render_screenshots",
        "release": "release",
        "wait": "wait",
        "beta": "beta",
        "review": "review",
        "launch": "launch",
        "inspect": "inspect",
        "privacy": "privacy",
        "signing": "signing",
    }
    for action, method in actions.items():

        def perform(*args, **kwargs):
            return ["done"]

        setattr(workflow_engine, method, perform)
        step = WorkflowStep(id=action, action=action, provider="apple")
        expected = ["Remote state inspected"] if action == "inspect" else ["done"]
        assert runner.execute(step, apply=True) == expected
    with pytest.raises(ConfigurationError, match="Unknown"):
        runner.execute(
            WorkflowStep.model_construct(id="invalid", action="invalid", provider="all"), apply=False
        )
    config = tmp_path / "cli.yaml"
    config.write_text(yaml.safe_dump(workflow_engine.project.model_dump(mode="json")))
    monkeypatch.setattr(WorkflowRunner, "run", lambda self, **kwargs: ["done"])
    assert CliRunner().invoke(app, ["workflow", str(config)]).exit_code == 0
