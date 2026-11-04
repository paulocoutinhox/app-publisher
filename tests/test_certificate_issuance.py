import base64
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_certificate_issuance import AppleCertificateIssuance
from app_publisher.models.apple_signing_config import AppleSigningConfig
from app_publisher.providers.apple_certificate_issuer import AppleCertificateIssuer


class CertificateAPI:
    def __init__(self, mode="valid"):
        self.mode = mode
        self.calls = []

    def request(self, method, path, *, payload):
        self.calls.append((method, path, payload))
        if self.mode == "network_error":
            raise RuntimeError("transport failed")
        if self.mode == "invalid_resource":
            return {"data": {"type": "other", "id": ""}}
        if self.mode == "missing_resource_id":
            return {"data": {"type": "certificates"}}
        if self.mode == "missing_content":
            return {"data": {"type": "certificates", "id": "cert-id", "attributes": {}}}
        if self.mode == "invalid_base64":
            return {
                "data": {"type": "certificates", "id": "cert-id", "attributes": {"certificateContent": "???"}}
            }
        if self.mode == "invalid_der":
            return {
                "data": {
                    "type": "certificates",
                    "id": "cert-id",
                    "attributes": {"certificateContent": base64.b64encode(b"not a certificate").decode()},
                }
            }
        request = x509.load_pem_x509_csr(payload["data"]["attributes"]["csrContent"].encode())
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = key.public_key() if self.mode == "wrong_key" else request.public_key()
        now = datetime.now(UTC)
        valid_until = now - timedelta(days=1) if self.mode == "expired" else now + timedelta(days=365)
        issued = (
            x509.CertificateBuilder()
            .subject_name(request.subject)
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mock Apple CA")]))
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=365))
            .not_valid_after(valid_until)
            .sign(key, hashes.SHA256())
        )
        return {
            "data": {
                "type": "certificates",
                "id": "cert-id",
                "attributes": {
                    "certificateContent": base64.b64encode(
                        issued.public_bytes(serialization.Encoding.DER)
                    ).decode()
                },
            }
        }


def certificate_config(**kwargs):
    return AppleCertificateIssuance(
        certificate_type="DISTRIBUTION",
        common_name="App Store Distribution",
        email_address="owner@example.com",
        private_key_output="secrets/distribution.key",
        csr_output="secrets/distribution.csr",
        certificate_output="secrets/distribution.cer",
        password_env="APP_PUBLISHER_CERT_PASSWORD",
        **kwargs,
    )


def test_certificate_issuance_dry_run_and_confirmation(tmp_path, monkeypatch):
    config = certificate_config()
    api = CertificateAPI()
    issuer = AppleCertificateIssuer(api)
    assert issuer.synchronize([config], tmp_path, apply=False) == [
        "Apple signing: issue DISTRIBUTION certificate to secrets/distribution.cer"
    ]
    assert issuer.synchronize([], tmp_path, apply=True) == []
    assert api.calls == []
    with pytest.raises(UnsafeOperationError, match="confirm_creation"):
        issuer.synchronize([config], tmp_path, apply=True)
    config.confirm_creation = True
    with pytest.raises(ConfigurationError, match="at least 16 bytes"):
        issuer.synchronize([config], tmp_path, apply=True)
    monkeypatch.setenv(config.password_env, "short")
    with pytest.raises(ConfigurationError, match="at least 16 bytes"):
        issuer.synchronize([config], tmp_path, apply=True)


def test_issued_certificate_is_encrypted_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "secure-passphrase-do-not-reuse")
    config = certificate_config(confirm_creation=True)
    api = CertificateAPI()
    issuer = AppleCertificateIssuer(api)
    actions = issuer.synchronize([config], tmp_path, apply=True)
    assert len(actions) == 2
    assert "cert-id" in actions[-1]
    key, csr, cer = issuer.paths(config, tmp_path)
    assert all(path.is_file() for path in [key, csr, cer])
    assert b"ENCRYPTED PRIVATE KEY" in key.read_bytes()
    if os.name == "posix":
        assert key.stat().st_mode & 0o077 == 0
        assert csr.stat().st_mode & 0o077 == 0
    assert x509.load_der_x509_certificate(cer.read_bytes()).serial_number > 0
    assert issuer.synchronize([config], tmp_path, apply=True) == []
    assert len(api.calls) == 1
    assert api.calls[0][0:2] == ("POST", "certificates")
    assert api.calls[0][2]["data"]["attributes"]["certificateType"] == "DISTRIBUTION"
    with pytest.raises(UnsafeOperationError, match="already exists"):
        issuer.save_exclusive(cer, b"other")


def test_certificate_issuance_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "secure-passphrase-do-not-reuse")
    api = CertificateAPI()
    issuer = AppleCertificateIssuer(api)
    config = certificate_config(confirm_creation=True)
    for edit in [
        {"private_key_output": "../unsafe.pem"},
        {"csr_output": "secrets/distribution.key"},
        {"certificate_output": Path("/tmp/not-safe.cer")},
    ]:
        invalid = config.model_copy(update=edit)
        with pytest.raises(UnsafeOperationError, match="distinct files inside"):
            issuer.synchronize([invalid], tmp_path, apply=False)
    (tmp_path / "secrets").mkdir()
    config = config.model_copy(update={"certificate_output": Path("secrets")})
    with pytest.raises(UnsafeOperationError, match="cannot be a directory"):
        issuer.synchronize([config], tmp_path, apply=False)
    config = certificate_config(confirm_creation=True)
    (tmp_path / "secrets" / "distribution.csr").write_bytes(b"leftover")
    with pytest.raises(UnsafeOperationError, match="incomplete local state"):
        issuer.synchronize([config], tmp_path, apply=True)


def test_certificate_issuance_error_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "secure-passphrase-do-not-reuse")
    config = certificate_config(confirm_creation=True)
    for mode, exception_type, pattern in [
        ("network_error", RuntimeError, "transport failed"),
        ("invalid_resource", UnsafeOperationError, "invalid certificate resource"),
        ("missing_resource_id", UnsafeOperationError, "invalid certificate resource"),
        ("missing_content", UnsafeOperationError, "invalid certificate content"),
        ("invalid_base64", UnsafeOperationError, "invalid certificate content"),
        ("invalid_der", UnsafeOperationError, "valid DER"),
        ("wrong_key", UnsafeOperationError, "does not match"),
    ]:
        directory = tmp_path / mode
        directory.mkdir()
        with pytest.raises(exception_type, match=pattern):
            AppleCertificateIssuer(CertificateAPI(mode)).synchronize([config], directory, apply=True)
        assert (directory / config.private_key_output).is_file()
        assert (directory / config.csr_output).is_file()
        assert not (directory / config.certificate_output).exists()
        with pytest.raises(UnsafeOperationError, match="incomplete local state"):
            AppleCertificateIssuer(CertificateAPI()).synchronize([config], directory, apply=True)


def test_certificate_local_verification_rejects_mismatch_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "secure-passphrase-do-not-reuse")
    config = certificate_config(confirm_creation=True)
    path = tmp_path / "valid"
    path.mkdir()
    issuer = AppleCertificateIssuer(CertificateAPI())
    issuer.synchronize([config], path, apply=True)
    key, csr, _ = issuer.paths(config, path)
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "wrong-but-long-password")
    with pytest.raises(UnsafeOperationError, match="not readable"):
        issuer.synchronize([config], path, apply=False)
    monkeypatch.setenv("APP_PUBLISHER_CERT_PASSWORD", "secure-passphrase-do-not-reuse")
    original_csr = csr.read_bytes()
    csr.write_bytes(b"not a pem CSR")
    with pytest.raises(UnsafeOperationError, match="not readable"):
        issuer.synchronize([config], path, apply=False)
    csr.write_bytes(original_csr)
    for mode, pattern in [("wrong_key", "do not match"), ("expired", "expired")]:
        directory = tmp_path / mode
        directory.mkdir()
        if mode == "expired":
            AppleCertificateIssuer(CertificateAPI(mode)).synchronize([config], directory, apply=True)
        if mode == "wrong_key":
            from shutil import copy2

            (directory / "secrets").mkdir()
            for filename in ["distribution.key", "distribution.csr"]:
                copy2(key.parent / filename, directory / "secrets" / filename)
            different = CertificateAPI("wrong_key")
            request = x509.load_pem_x509_csr((directory / "secrets" / "distribution.csr").read_bytes())
            wrong = different.request(
                "POST",
                "certificates",
                payload={
                    "data": {
                        "attributes": {
                            "csrContent": request.public_bytes(serialization.Encoding.PEM).decode()
                        }
                    }
                },
            )
            (directory / "secrets" / "distribution.cer").write_bytes(
                base64.b64decode(wrong["data"]["attributes"]["certificateContent"])
            )
        with pytest.raises(UnsafeOperationError, match=pattern):
            AppleCertificateIssuer(CertificateAPI()).synchronize([config], directory, apply=False)


def test_issuer_is_wired_into_engine(project, tmp_path, monkeypatch):
    from app_publisher.providers.apple_certificate_issuer import AppleCertificateIssuer
    from app_publisher.providers.apple_signing_manager import AppleSigningManager

    project.apple.signing = AppleSigningConfig(issuance=[certificate_config()])
    calls = []
    fake = SimpleNamespace(
        api=SimpleNamespace(close=lambda: None),
        identify=lambda: calls.append("identify"),
        config=project.apple,
    )
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: fake)
    monkeypatch.setattr(
        AppleCertificateIssuer, "synchronize", lambda self, items, directory, apply: ["issued"]
    )
    monkeypatch.setattr(
        AppleSigningManager, "synchronize", lambda self, config, directory, apply: ["profiles"]
    )
    assert PublicationEngine(project, tmp_path / "app.yaml").signing(apply=True) == ["issued", "profiles"]
    assert calls == ["identify"]
