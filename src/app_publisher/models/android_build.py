from pathlib import Path

from pydantic import Field

from app_publisher.models.build_command import BuildCommand
from app_publisher.models.strict_model import StrictModel


class AndroidBuild(StrictModel):
    gradle_wrapper: Path = Path("gradlew")
    task: str = "bundleRelease"
    artifact: Path
    prepare_commands: list[BuildCommand] = Field(default_factory=list)
    finish_commands: list[BuildCommand] = Field(default_factory=list)
