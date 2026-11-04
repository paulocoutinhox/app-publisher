from pydantic import Field

from app_publisher.models.screenshot_design import ScreenshotDesign
from app_publisher.models.screenshot_plan import ScreenshotPlan
from app_publisher.models.strict_model import StrictModel
from app_publisher.models.workflow_config import WorkflowConfig


class PublicationConfig(StrictModel):
    submit_for_review: bool = False
    workflow: WorkflowConfig | None = None
    screenshot_plans: list[ScreenshotPlan] = Field(default_factory=list)
    screenshot_designs: list[ScreenshotDesign] = Field(default_factory=list)
