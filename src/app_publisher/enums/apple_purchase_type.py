from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class ApplePurchaseType(CaseInsensitiveEnum):
    CONSUMABLE = "CONSUMABLE"
    NON_CONSUMABLE = "NON_CONSUMABLE"
    NON_RENEWING_SUBSCRIPTION = "NON_RENEWING_SUBSCRIPTION"
