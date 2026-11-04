from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class PrivacyApiCategory(CaseInsensitiveEnum):
    NSPRIVACYACCESSEDAPICATEGORYFILETIMESTAMP = "NSPrivacyAccessedAPICategoryFileTimestamp"
    NSPRIVACYACCESSEDAPICATEGORYSYSTEMBOOTTIME = "NSPrivacyAccessedAPICategorySystemBootTime"
    NSPRIVACYACCESSEDAPICATEGORYDISKSPACE = "NSPrivacyAccessedAPICategoryDiskSpace"
    NSPRIVACYACCESSEDAPICATEGORYACTIVEKEYBOARDS = "NSPrivacyAccessedAPICategoryActiveKeyboards"
    NSPRIVACYACCESSEDAPICATEGORYUSERDEFAULTS = "NSPrivacyAccessedAPICategoryUserDefaults"
