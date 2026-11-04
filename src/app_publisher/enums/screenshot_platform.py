from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class ScreenshotPlatform(CaseInsensitiveEnum):
    IOS = "ios"
    TVOS = "tvos"
    WATCHOS = "watchos"
    VISIONOS = "visionos"
    MACOS = "macos"
    ANDROID = "android"
