from pydantic import Field

from app_publisher.models.strict_model import StrictModel


class GoogleMonetizationProduct(StrictModel):
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.]{0,39}$")
    update_mask: list[str] = Field(min_length=1)
    regions_version: str = Field(min_length=1)
    data: dict[str, object] = Field(min_length=1)
