from pydantic import Field, model_validator

from app_publisher.enums.provider_name import ProviderName
from app_publisher.enums.workflow_action import WorkflowAction
from app_publisher.models.strict_model import StrictModel


class WorkflowStep(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    action: WorkflowAction
    provider: ProviderName = ProviderName.ALL
    timeout_seconds: int = Field(default=900, ge=1, le=7200)

    @model_validator(mode="after")
    def valid_provider(self) -> "WorkflowStep":
        if self.provider == "firebase" and self.action != "sync":
            raise ValueError("The Firebase workflow provider is valid only for sync")

        if (
            self.action in {"wait", "beta", "review", "launch", "privacy", "signing"}
            and self.provider != "apple"
        ):
            raise ValueError("This workflow action requires the Apple provider")

        return self
