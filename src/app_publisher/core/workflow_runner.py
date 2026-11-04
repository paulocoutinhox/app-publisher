from pathlib import Path
from typing import Any

from app_publisher.core.apple_review_file_helper import AppleReviewFileHelper
from app_publisher.core.credential_helper import CredentialHelper
from app_publisher.core.paths import project_path
from app_publisher.core.sync_plan import sha256_file
from app_publisher.core.workflow_journal import WorkflowJournal
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.workflow_state import WorkflowState
from app_publisher.models.workflow_step import WorkflowStep


class WorkflowRunner:
    def __init__(self, engine: Any):
        self.engine = engine
        self.root = engine.directory.resolve()

    def source_hashes(self) -> dict[str, str]:
        paths: set[Path] = set()

        for pattern in self.engine.project.publication.workflow.source_inputs:
            project_path(self.root, pattern)
            matches = [path for path in self.root.glob(pattern) if path.is_file()]

            if not matches:
                raise ConfigurationError(f"Workflow source pattern has no files: {pattern}")

            paths.update(project_path(self.root, path.relative_to(self.root)) for path in matches)

        return {path.relative_to(self.root).as_posix(): sha256_file(path) for path in sorted(paths)}

    def artifacts(self) -> dict[str, str]:
        project = self.engine.project
        paths = []

        if project.apple:
            paths.extend(AppleReviewFileHelper.paths(project.apple))
            paths.extend(version.artifact for version in project.apple.versions if version.artifact)

        if project.google and project.google.release and project.google.release.artifact:
            paths.append(project.google.release.artifact)

        paths.extend(scene.output for plan in project.publication.screenshot_plans for scene in plan.scenes)
        paths.extend(design.output for design in project.publication.screenshot_designs)
        resolved = [project_path(self.root, path) for path in paths]
        return {
            path.relative_to(self.root).as_posix(): sha256_file(path) for path in resolved if path.is_file()
        }

    def execute(self, step: WorkflowStep, *, apply: bool) -> list[str]:
        engine = self.engine
        action = step.action

        if action == "validate":
            engine.validate(local_files="none")
            return ["Configuration validated"]
        if action == "build":
            return engine.build(apply=apply, provider=step.provider)
        if action == "symbols":
            return engine.symbols(apply=apply, provider=step.provider)
        if action == "capture":
            return engine.screenshots(apply=apply)
        if action == "render":
            return engine.render_screenshots(apply=apply)
        if action == "sync":
            return engine.synchronize(apply=apply, provider=step.provider)
        if action == "release":
            return engine.release(apply=apply, provider=step.provider)
        if action == "wait":
            return engine.wait(timeout=step.timeout_seconds)
        if action == "beta":
            return engine.beta(apply=apply)
        if action == "review":
            return engine.review(apply=apply)
        if action == "launch":
            return engine.launch(apply=apply)
        if action == "inspect":
            engine.inspect(step.provider)
            return ["Remote state inspected"]
        if action == "privacy":
            return engine.privacy(apply=apply)
        if action == "signing":
            return engine.signing(apply=apply)

        raise ConfigurationError("Unknown workflow action")

    def run(self, *, apply: bool, resume: bool = False, retry_failed: bool = False) -> list[str]:
        config = self.engine.project.publication.workflow

        if config is None:
            raise ConfigurationError("No publishing workflow is declared in YAML")

        if not apply:
            return [f"Workflow {step.id}: {step.action} ({step.provider})" for step in config.steps]

        journal = WorkflowJournal(self.root, config.journal)
        journal.acquire()

        try:
            fingerprint = sha256_file(self.engine.file)
            sources = self.source_hashes()

            if resume:
                state = journal.load()

                if state.config_sha256 != fingerprint or state.source_hashes != sources:
                    raise UnsafeOperationError("Workflow YAML or source inputs changed. Use a new journal")

                if state.artifact_hashes != self.artifacts():
                    raise UnsafeOperationError("Workflow artifacts changed after the recorded operation")

                if state.active_step is not None and not retry_failed:
                    raise UnsafeOperationError(
                        "A stage may have partially completed. Inspect remote state before --retry-failed"
                    )
            else:
                if journal.path.exists():
                    raise UnsafeOperationError(
                        "A workflow journal already exists. Use --resume or a new journal path"
                    )

                state = WorkflowState(config_sha256=fingerprint, source_hashes=sources)
                journal.save(state)

            known_steps = {step.id for step in config.steps}

            if not set(state.completed).issubset(known_steps) or (
                state.active_step is not None and state.active_step not in known_steps
            ):
                raise UnsafeOperationError("The journal contains an unknown workflow stage")

            results = []

            for step in config.steps:
                if step.id in state.completed:
                    results.append(f"Workflow {step.id}: already completed")
                    continue

                state.active_step = step.id
                state.failure_type = None
                journal.save(state)

                try:
                    changes = self.execute(step, apply=True)
                except BaseException as error:
                    state.failure_type = type(error).__name__
                    journal.save(state)
                    raise

                state.completed[step.id] = [CredentialHelper.redact(change) for change in changes]
                state.active_step = None
                state.artifact_hashes = self.artifacts()
                journal.save(state)
                results.extend(state.completed[step.id])

            return results
        finally:
            journal.release()
