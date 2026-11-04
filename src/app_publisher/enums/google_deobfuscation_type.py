from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class GoogleDeobfuscationType(CaseInsensitiveEnum):
    PROGUARD = "proguard"
    NATIVECODE = "nativeCode"
