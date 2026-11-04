from app_publisher.enums.case_insensitive_enum import CaseInsensitiveEnum


class WorkflowAction(CaseInsensitiveEnum):
    VALIDATE = "validate"
    BUILD = "build"
    SYMBOLS = "symbols"
    CAPTURE = "capture"
    RENDER = "render"
    SYNC = "sync"
    RELEASE = "release"
    WAIT = "wait"
    BETA = "beta"
    REVIEW = "review"
    LAUNCH = "launch"
    INSPECT = "inspect"
    PRIVACY = "privacy"
    SIGNING = "signing"
