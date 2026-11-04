import re

from pydantic import Field, model_validator

from app_publisher.models.strict_model import StrictModel


class GoogleCountryTargeting(StrictModel):
    countries: list[str] = Field(min_length=1)
    include_rest_of_world: bool = False

    @model_validator(mode="after")
    def validate_codes(self) -> "GoogleCountryTargeting":
        if len(self.countries) != len(set(self.countries)) or any(
            re.fullmatch(r"[A-Z]{2}", country) is None for country in self.countries
        ):
            raise ValueError("Country targeting requires unique uppercase two-letter country codes")
        return self
