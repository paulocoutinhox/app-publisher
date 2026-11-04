from app_publisher.core.api_client import APIClient
from app_publisher.models.android_certificate import AndroidCertificate


class FirebaseCertificates:
    def __init__(self, api: APIClient):
        self.api = api

    def synchronize(self, application_name: str, certificates: list[AndroidCertificate]) -> list[str]:
        if not certificates:
            return []
        current = self.api.request("GET", f"{application_name}/sha").get("certificates", [])
        known = {(item["shaHash"].replace(":", "").upper(), item["certType"]) for item in current}
        changes: list[str] = []
        for certificate in certificates:
            normalized = certificate.sha_hash.replace(":", "").upper()
            identity = (normalized, certificate.certificate_type)
            if identity in known:
                continue
            self.api.request(
                "POST",
                f"{application_name}/sha",
                payload={"shaHash": certificate.sha_hash, "certType": certificate.certificate_type},
            )
            changes.append(f"Firebase: register {certificate.certificate_type} for {application_name}")
            known.add(identity)
        return changes
