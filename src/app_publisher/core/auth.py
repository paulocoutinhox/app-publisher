import os
import time
from pathlib import Path

import jwt

from app_publisher.errors.configuration_error import ConfigurationError


def apple_token(key_id_env: str, issuer_id_env: str, path_env: str) -> str:
    key_id = required_environment(key_id_env)
    issuer_id = required_environment(issuer_id_env)
    private_key = Path(required_environment(path_env)).read_text(encoding="utf-8")
    timestamp = int(time.time())
    return jwt.encode(
        {"iss": issuer_id, "iat": timestamp, "exp": timestamp + 900, "aud": "appstoreconnect-v1"},
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


def google_token(scopes: list[str]) -> str:
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(scopes=scopes)
    credentials.refresh(google.auth.transport.requests.Request())
    if not credentials.token:
        raise ConfigurationError("Google credentials returned an empty access token")
    return credentials.token


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"Missing environment variable: {name}")
    return value
