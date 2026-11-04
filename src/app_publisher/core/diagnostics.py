import json
import os
from pathlib import Path
from typing import Any

import httpx

from app_publisher.core.credential_helper import CredentialHelper
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError

GUIDANCE = {
    400: "Review the rejected field and the store's current state.",
    401: "Check the API credentials and their expiration.",
    403: "Check the account role, API scopes and app-specific permissions.",
    404: "Verify the app identifier, resource ID and API version.",
    409: "A concurrent update may have changed the resource. Refresh the plan.",
    412: "The remote resource changed or a required precondition failed.",
    429: "The store rate limit was reached. Retry after its indicated delay.",
    500: "The store returned a server error. Verify the remote state before retrying.",
    502: "The store returned a gateway error. Verify the remote state before retrying.",
    503: "The store is temporarily unavailable. Verify the remote state before retrying.",
}


def remote_error_message(response: httpx.Response) -> str:
    try:
        result = response.json()
    except ValueError:
        return "The store returned a non-JSON error response. Raw content is hidden to protect credentials"
    if not isinstance(result, dict):
        return "The store returned an unexpected error structure"
    apple = result.get("errors")
    if isinstance(apple, list):
        messages = []
        for entry in apple[:5]:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            field = source.get("pointer") if isinstance(source, dict) else None
            messages.append(
                " ".join(
                    str(item)
                    for item in [entry.get("code"), entry.get("title"), entry.get("detail"), field]
                    if item
                )[:350]
            )
        if messages:
            return CredentialHelper.redact(" | ".join(messages))
    google = result.get("error")
    if isinstance(google, dict):
        status = google.get("status")
        message = google.get("message")
        return (
            CredentialHelper.redact(" ".join(str(value) for value in [status, message] if value)[:500])
            or "Google returned a structured error without a message"
        )
    return "The store returned an unrecognized error structure. Raw content is hidden to protect credentials"


def diagnose(error: Exception, *, action: str, provider: str) -> dict[str, Any]:
    status = error.status_code if isinstance(error, RemoteAPIError) else None
    recommendation = GUIDANCE.get(
        status, "Review the configuration and the remote resource state before retrying."
    )
    if isinstance(error, UnsafeOperationError):
        recommendation = "The operation was blocked for safety. Review the YAML and generate a new plan."
    return {
        "status": "failed",
        "action": action,
        "provider": provider,
        "error_type": type(error).__name__,
        "http_status": status,
        "message": CredentialHelper.redact(str(error)),
        "cleanup_notes": [CredentialHelper.redact(note) for note in getattr(error, "__notes__", [])],
        "recommendation": recommendation,
        "changes_may_have_been_applied": action not in {"diff", "validate", "inspect", "doctor"},
        "cross_provider_atomic": False,
    }


def save_report(target: Path, report: dict[str, Any]) -> Path:
    if target.is_symlink():
        raise UnsafeOperationError("Refusing to write a report through a symbolic link")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as error:
        raise UnsafeOperationError(f"Refusing to overwrite an existing report: {target}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
