from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class GoogleImageType(CaseInsensitiveEnum):
    PHONESCREENSHOTS = "phoneScreenshots"
    SEVENINCHSCREENSHOTS = "sevenInchScreenshots"
    TENINCHSCREENSHOTS = "tenInchScreenshots"
    TVSCREENSHOTS = "tvScreenshots"
    WEARSCREENSHOTS = "wearScreenshots"
    ICON = "icon"
    FEATUREGRAPHIC = "featureGraphic"
    TVBANNER = "tvBanner"
