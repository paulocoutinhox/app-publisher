import httpx
import jwt
import pytest
from conftest import Recorder
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from app_publisher.core.api_client import APIClient
from app_publisher.core.auth import apple_token, required_environment
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError


def test_http_client_methods_and_pagination():
    def handler(req):
        if req.url.path.endswith("/page1"):
            return httpx.Response(
                200, json={"data": [{"id": "a"}], "links": {"next": "https://example.org/page2"}}
            )
        if req.url.path.endswith("/page2"):
            return httpx.Response(200, json={"data": [{"id": "b"}]})
        return httpx.Response(204)

    recorder = Recorder(handler)
    client = APIClient("https://example.org", lambda: "secret", httpx.MockTransport(recorder))
    assert client.paginated("page1") == [{"id": "a"}, {"id": "b"}]
    assert recorder.calls[0].headers["Authorization"] == "Bearer secret"
    assert client.request("DELETE", "any") == {}
    client.close()


def test_http_rejects_invalid_and_network_errors():
    for body in [(400, {"error": "bad"}), (200, [1, 2]), (200, "not-json")]:
        status, payload = body

        def handler(req):
            return (
                httpx.Response(status, json=payload)
                if not isinstance(payload, str)
                else httpx.Response(status, text=payload)
            )

        api = APIClient("https://api.example", lambda: "token", httpx.MockTransport(handler))
        with pytest.raises(RemoteAPIError):
            api.request("GET", "path")
    api = APIClient(
        "https://api.example",
        lambda: "token",
        httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("closed"))),
    )
    with pytest.raises(RemoteAPIError, match="failed"):
        api.request("GET", "broken")
    api = APIClient(
        "https://api.example",
        lambda: "token",
        httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [], "links": {"next": "https://evil.example/page"}})
        ),
    )
    with pytest.raises(RemoteAPIError, match="unexpected server"):
        api.paginated("path")
    api = APIClient(
        "https://api.example", lambda: "token", httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(RemoteAPIError, match="paginated"):
        api.paginated("path")


def test_apple_jwt_and_environment(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    key_path = tmp_path / "token.p8"
    key_path.write_text(pem)
    monkeypatch.setenv("KEY_ID", "KEY123")
    monkeypatch.setenv("ISSUER_ID", "ISSUER")
    monkeypatch.setenv("KEY_FILE", str(key_path))
    encoded = apple_token("KEY_ID", "ISSUER_ID", "KEY_FILE")
    decoded = jwt.decode(encoded, key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1")
    assert decoded["iss"] == "ISSUER"
    assert required_environment("KEY_ID") == "KEY123"
    monkeypatch.delenv("KEY_ID")
    with pytest.raises(ConfigurationError, match="Missing environment"):
        required_environment("KEY_ID")


def test_http_retry_get_and_do_not_retry_post(monkeypatch):
    import httpx

    from app_publisher.core.api_client import APIClient
    from app_publisher.errors.remote_api_error import RemoteAPIError

    count = []
    sleep = []

    def handler(request):
        count.append(request.method)
        if request.method == "GET" and len(count) < 3:
            return httpx.Response(503, headers={"Retry-After": "1"}, json={"error": "Busy"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("app_publisher.core.api_client.time.sleep", sleep.append)
    client = APIClient("https://api.test", lambda: "token", httpx.MockTransport(handler), retries=2)
    assert client.request("GET", "test") == {"ok": True}
    assert sleep == [1.0, 1.0]
    assert count == ["GET", "GET", "GET"]
    client2 = APIClient(
        "https://api.test",
        lambda: "token",
        httpx.MockTransport(lambda r: httpx.Response(503, json={})),
        retries=2,
    )
    with pytest.raises(RemoteAPIError, match="503"):
        client2.request("POST", "some/command", payload={})
    with pytest.raises(RemoteAPIError, match="503"):
        client2.request("GET", "some/list")


def test_http_rejects_negative_retry_count():
    from app_publisher.core.api_client import APIClient

    with pytest.raises(ValueError, match="negative"):
        APIClient("https://api.test", lambda: "token", retries=-1)


def test_http_paginated_v2_endpoints_follow_v2_urls():
    paths = []

    def handler(req):
        paths.append(str(req.url))
        if not req.url.query:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "one"}],
                    "links": {
                        "next": "https://api.appstoreconnect.apple.com/v2/inAppPurchases/iap/versions?page=2"
                    },
                },
            )
        return httpx.Response(200, json={"data": [{"id": "two"}]})

    api = APIClient("https://api.appstoreconnect.apple.com/v1", lambda: "token", httpx.MockTransport(handler))
    assert api.paginated("inAppPurchases/iap/versions", version="v2") == [{"id": "one"}, {"id": "two"}]
    assert all("/v2/" in url for url in paths)
    assert "page=2" in paths[1]
    wrong_server = APIClient("https://api.google.test", lambda: "token")
    with pytest.raises(RemoteAPIError, match="Versioned API pagination requires"):
        wrong_server.paginated("anything", version="v2")
    failed = APIClient(
        "https://api.appstoreconnect.apple.com/v1",
        lambda: "token",
        httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"data": [], "links": {"next": "https://api.appstoreconnect.apple.com/v1/malicious"}},
            )
        ),
    )
    with pytest.raises(RemoteAPIError, match="unexpected server"):
        failed.paginated("one", version="v2")
