import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app_publisher.core.paths import project_path
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.workflow_state import WorkflowState


class WorkflowJournal:
    def __init__(self, directory: Path, configured: Path):
        if (directory / configured).is_symlink():
            raise UnsafeOperationError("The workflow journal cannot be a symbolic link")

        self.path = project_path(directory, configured)
        self.lock = self.path.with_suffix(".lock")

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise UnsafeOperationError("The workflow journal is already locked by another run") from None

        os.close(descriptor)

    def release(self) -> None:
        self.lock.unlink()

    def load(self) -> WorkflowState:
        if not self.path.is_file() or self.path.stat().st_size > 5 * 1024 * 1024:
            raise ConfigurationError("The workflow journal is missing or exceeds its size limit")

        try:
            return WorkflowState.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, UnicodeError, ValidationError):
            raise ConfigurationError("The workflow journal is invalid. Its contents are hidden") from None

    def save(self, state: WorkflowState) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".app-publisher-", dir=self.path.parent)
        temporary = Path(name)

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(state.model_dump_json(indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())

            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
