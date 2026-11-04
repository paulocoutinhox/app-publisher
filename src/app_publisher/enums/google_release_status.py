from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class GoogleReleaseStatus(CaseInsensitiveEnum):
    DRAFT = "draft"
    INPROGRESS = "inProgress"
    HALTED = "halted"
    COMPLETED = "completed"
