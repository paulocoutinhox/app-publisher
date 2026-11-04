from pydantic import Field

from app_publisher.enums.google_product_state import GoogleProductState
from app_publisher.models.strict_model import StrictModel


class GoogleBasePlanState(StrictModel):
    product_id: str = Field(min_length=1)
    base_plan_id: str = Field(min_length=1)
    state: GoogleProductState
