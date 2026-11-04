from pydantic import HttpUrl

from app_publisher.models.strict_model import StrictModel


class GoogleStoreDetails(StrictModel):
    default_language: str | None = None
    contact_website: HttpUrl | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
