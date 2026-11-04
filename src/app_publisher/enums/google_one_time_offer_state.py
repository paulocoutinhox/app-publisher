from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class GoogleOneTimeOfferState(CaseInsensitiveEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CANCELLED = "CANCELLED"
