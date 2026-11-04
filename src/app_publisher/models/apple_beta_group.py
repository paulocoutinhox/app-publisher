from pydantic import Field, model_validator

from app_publisher.models.apple_beta_tester import AppleBetaTester
from app_publisher.models.strict_model import StrictModel


class AppleBetaGroup(StrictModel):
    name: str = Field(min_length=1)
    internal: bool = False
    public_link_enabled: bool = False
    public_link_limit: int | None = Field(default=None, ge=1, le=10000)
    feedback_enabled: bool | None = None
    testers: list[AppleBetaTester] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_group(self) -> "AppleBetaGroup":
        if self.internal and (self.public_link_enabled or self.public_link_limit is not None):
            raise ValueError("Internal TestFlight groups cannot use public links")
        if len({tester.email.casefold() for tester in self.testers}) != len(self.testers):
            raise ValueError("TestFlight group tester emails must be unique")
        return self
