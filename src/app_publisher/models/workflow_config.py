from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.models.strict_model import StrictModel
from app_publisher.models.workflow_step import WorkflowStep


class WorkflowConfig(StrictModel):
    journal: Path
    source_inputs: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_steps(self) -> "WorkflowConfig":
        identities = [step.id for step in self.steps]

        if len(identities) != len(set(identities)):
            raise ValueError("Workflow step IDs must be unique")

        return self
