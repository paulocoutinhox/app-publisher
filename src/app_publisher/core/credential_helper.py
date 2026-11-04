import os
import re


class CredentialHelper:
    @staticmethod
    def redact(message: str) -> str:
        message = re.sub(
            r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
            "[REDACTED PRIVATE KEY]",
            message,
            flags=re.DOTALL,
        )
        message = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", message)
        message = re.sub(
            r"(?i)([\"']?(?:password|secret|token|api[_-]?key|authorization|private_key)[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)",
            r"\1[REDACTED]",
            message,
        )
        message = re.sub(r"(?i)(https://[^\s?]+)\?[^\s]+", r"\1?[REDACTED QUERY]", message)

        for name, value in os.environ.items():
            if len(value) >= 4 and re.search(
                r"PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY", name, re.IGNORECASE
            ):
                message = message.replace(value, "[REDACTED]")

        return message
