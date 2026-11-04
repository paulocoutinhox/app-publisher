from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, validate_default=True, use_enum_values=True
    )
