from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.models.build_command import BuildCommand
from app_publisher.models.strict_model import StrictModel


class AppleBuild(StrictModel):
    workspace: Path | None = None
    project: Path | None = None
    scheme: str = Field(min_length=1)
    configuration: str = "Release"
    archive_path: Path
    export_path: Path
    export_options: Path
    destination: str = "generic/platform=iOS"
    prepare_commands: list[BuildCommand] = Field(default_factory=list)
    allow_provisioning_updates: bool = False
    build_settings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_input(self) -> "AppleBuild":
        if (self.workspace is None) == (self.project is None):
            raise ValueError("Exactly one of workspace or project is required")
        return self
