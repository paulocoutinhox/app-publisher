from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class ScreenshotActionKind(CaseInsensitiveEnum):
    TAP = "tap"
    SWIPE = "swipe"
    TEXT = "text"
    LAUNCH = "launch"
    TERMINATE = "terminate"
    OPEN_URL = "open_url"
    WAIT = "wait"
    TAP_ELEMENT = "tap_element"
    WAIT_ELEMENT = "wait_element"
    HINGE = "hinge"
    REMOTE = "remote"
    ROTATE = "rotate"
    SHAKE = "shake"
    PINCH = "pinch"
