from app_publisher.errors.app_publisher_error import AppPublisherError


class RemoteAPIError(AppPublisherError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
