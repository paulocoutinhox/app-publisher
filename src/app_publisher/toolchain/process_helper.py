import subprocess
from collections.abc import Callable
from pathlib import Path

from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError


class ProcessHelper:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run):
        self.runner = runner

    def run(self, command: list[str], directory: Path, *, timeout: int = 300) -> str:
        try:
            result = self.runner(
                command, cwd=directory, check=True, capture_output=True, text=True, timeout=timeout
            )
        except FileNotFoundError:
            raise ConfigurationError(f"Required tool is missing: {Path(command[0]).name}") from None
        except subprocess.TimeoutExpired:
            raise UnsafeOperationError(
                f"{Path(command[0]).name} exceeded its configured timeout. Verify remote state before retrying"
            ) from None
        except subprocess.CalledProcessError as error:
            raise UnsafeOperationError(
                f"{Path(command[0]).name} failed with exit {error.returncode}. Output is hidden to protect credentials"
            ) from None

        return result.stdout
