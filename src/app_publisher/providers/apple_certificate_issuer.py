import base64
import binascii
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.apple_certificate_issuance import AppleCertificateIssuance


class AppleCertificateIssuer:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(
        self, certificates: list[AppleCertificateIssuance], directory: Path, *, apply: bool
    ) -> list[str]:
        changes: list[str] = []
        for certificate in certificates:
            private_key, csr, result = self.paths(certificate, directory)
            existing = [path.exists() for path in (private_key, csr, result)]
            if all(existing):
                self.verify_existing(certificate, private_key, csr, result)
                continue
            if any(existing):
                raise UnsafeOperationError(
                    f"Apple certificate issuance has an incomplete local state: {certificate.certificate_output}. Complete the recovery manually before retrying"
                )
            changes.append(
                f"Apple signing: issue {certificate.certificate_type} certificate to {certificate.certificate_output.as_posix()}"
            )
            if not apply:
                continue
            if not certificate.confirm_creation:
                raise UnsafeOperationError("New Apple certificates require confirm_creation: true")
            password = self.passphrase(certificate)
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            encrypted_key = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password),
            )
            request = (
                x509.CertificateSigningRequestBuilder()
                .subject_name(
                    x509.Name(
                        [
                            x509.NameAttribute(NameOID.COMMON_NAME, certificate.common_name),
                            x509.NameAttribute(NameOID.EMAIL_ADDRESS, certificate.email_address),
                        ]
                    )
                )
                .sign(key, hashes.SHA256())
            )
            csr_content = request.public_bytes(serialization.Encoding.PEM)
            self.save_exclusive(private_key, encrypted_key)
            self.save_exclusive(csr, csr_content)
            payload = {
                "data": {
                    "type": "certificates",
                    "attributes": {
                        "certificateType": certificate.certificate_type,
                        "csrContent": csr_content.decode("ascii"),
                    },
                }
            }
            response = self.api.request("POST", "certificates", payload=payload)["data"]
            if response.get("type") != "certificates" or not response.get("id"):
                raise UnsafeOperationError("Apple returned an invalid certificate resource")
            try:
                certificate_content = base64.b64decode(
                    response["attributes"]["certificateContent"], validate=True
                )
            except (KeyError, binascii.Error, ValueError) as error:
                raise UnsafeOperationError("Apple returned invalid certificate content") from error
            issued = self.read_certificate(certificate_content)
            if issued.public_key().public_numbers() != key.public_key().public_numbers():
                raise UnsafeOperationError(
                    "Apple issued a certificate that does not match the generated private key"
                )
            self.save_exclusive(result, certificate_content)
            changes.append(f"Apple signing: created certificate resource {response['id']}")
        return changes

    @staticmethod
    def paths(certificate: AppleCertificateIssuance, directory: Path) -> tuple[Path, Path, Path]:
        base = directory.resolve()
        targets = tuple(
            (base / path).resolve()
            for path in (
                certificate.private_key_output,
                certificate.csr_output,
                certificate.certificate_output,
            )
        )
        if len(set(targets)) != 3 or any(path == base or base not in path.parents for path in targets):
            raise UnsafeOperationError(
                "Certificate issuance paths must be distinct files inside the configuration directory"
            )
        if any(path.is_dir() for path in targets):
            raise UnsafeOperationError("Certificate issuance output cannot be a directory")
        return targets

    @staticmethod
    def passphrase(certificate: AppleCertificateIssuance) -> bytes:
        value = os.environ.get(certificate.password_env)
        if value is None or len(value.encode("utf-8")) < 16:
            raise ConfigurationError(
                f"Environment variable {certificate.password_env} must contain a private key passphrase of at least 16 bytes"
            )
        return value.encode("utf-8")

    @staticmethod
    def save_exclusive(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise UnsafeOperationError(f"Certificate issuance output already exists: {path}") from error
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)

    @staticmethod
    def read_certificate(content: bytes) -> x509.Certificate:
        try:
            return x509.load_der_x509_certificate(content)
        except ValueError as error:
            raise UnsafeOperationError("Apple certificate is not valid DER X.509 data") from error

    def verify_existing(
        self, certificate: AppleCertificateIssuance, private_key: Path, csr: Path, result: Path
    ) -> None:
        try:
            key = serialization.load_pem_private_key(
                private_key.read_bytes(), password=self.passphrase(certificate)
            )
            request = x509.load_pem_x509_csr(csr.read_bytes())
        except (ValueError, TypeError) as error:
            raise UnsafeOperationError(
                "Apple certificate private key or CSR is not readable with the configured password"
            ) from error
        issued = self.read_certificate(result.read_bytes())
        public_key = key.public_key().public_numbers()
        if (
            public_key != request.public_key().public_numbers()
            or public_key != issued.public_key().public_numbers()
        ):
            raise UnsafeOperationError("Apple certificate, CSR and private key do not match")
        if issued.not_valid_after_utc <= datetime.now(UTC):
            raise UnsafeOperationError(
                "Apple signing certificate is expired. Issue a replacement using new output paths"
            )
