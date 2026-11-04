from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class PrivacyDataPurpose(CaseInsensitiveEnum):
    NSPRIVACYCOLLECTEDDATATYPEPURPOSETHIRDPARTYADVERTISING = (
        "NSPrivacyCollectedDataTypePurposeThirdPartyAdvertising"
    )
    NSPRIVACYCOLLECTEDDATATYPEPURPOSEDEVELOPERADVERTISING = (
        "NSPrivacyCollectedDataTypePurposeDeveloperAdvertising"
    )
    NSPRIVACYCOLLECTEDDATATYPEPURPOSEANALYTICS = "NSPrivacyCollectedDataTypePurposeAnalytics"
    NSPRIVACYCOLLECTEDDATATYPEPURPOSEPRODUCTPERSONALIZATION = (
        "NSPrivacyCollectedDataTypePurposeProductPersonalization"
    )
    NSPRIVACYCOLLECTEDDATATYPEPURPOSEAPPFUNCTIONALITY = "NSPrivacyCollectedDataTypePurposeAppFunctionality"
    NSPRIVACYCOLLECTEDDATATYPEPURPOSEOTHER = "NSPrivacyCollectedDataTypePurposeOther"
