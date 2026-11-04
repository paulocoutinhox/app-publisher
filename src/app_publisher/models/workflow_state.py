from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class WorkflowState(StrictModel):
    config_sha256: str
    source_hashes: dict[str, str]
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    completed: dict[str, list[str]] = Field(default_factory=dict)
    active_step: str | None = None
    failure_type: str | None = None
