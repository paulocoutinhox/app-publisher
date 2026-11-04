from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class AppleReleaseType(CaseInsensitiveEnum):
    MANUAL = "MANUAL"
    AFTER_APPROVAL = "AFTER_APPROVAL"
    SCHEDULED = "SCHEDULED"
