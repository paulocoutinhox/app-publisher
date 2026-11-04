from pydantic import Field, model_validator

from app_publisher.models.strict_model import StrictModel


class GoogleCountryExpectation(StrictModel):
    track: str = Field(min_length=1)
    countries: list[str] = Field(default_factory=list)
    sync_with_production: bool | None = None
    rest_of_world: bool | None = None

    @model_validator(mode="after")
    def validate_countries(self) -> "GoogleCountryExpectation":
        if any(len(code) != 2 or not code.isalpha() or not code.isupper() for code in self.countries):
            raise ValueError("Google country codes must be uppercase two-letter CLDR codes")
        if len(self.countries) != len(set(self.countries)):
            raise ValueError("Google country expectation cannot contain duplicate codes")
        return self
