# Issuing Apple signing certificates

The App Store Connect public API supports issuing certificates from CSRs. App Publisher can generate a 3072-bit RSA private key, encrypt its PKCS#8 PEM representation using a passphrase provided through an environment variable, generate a matching CSR and request an Apple certificate.

```yaml
apple:
  signing:
    issuance:
      - certificate_type: DISTRIBUTION
        common_name: Example App Distribution
        email_address: owner@example.com
        private_key_output: signing/distribution.key
        csr_output: signing/distribution.csr
        certificate_output: signing/distribution.cer
        password_env: APP_PUBLISHER_CERT_PASSWORD
        confirm_creation: false
```

Set a strong passphrase in `APP_PUBLISHER_CERT_PASSWORD`, store it in a secret manager and change `confirm_creation` to `true` only after confirming that you intend to create a new certificate. Run `app-publisher signing config.yaml` for a dry run and `app-publisher signing config.yaml --apply` to issue.

**Safety boundaries:** local output paths must be distinct, inside the project and absent before first issuance. Private keys and CSRs are created with owner-only file permissions. On success the certificate must match the generated public key. Subsequent runs verify that the key, CSR and certificate agree and that the certificate is not expired. An interrupted or ambiguous remote creation leaves an incomplete local state and **does not retry** automatically, since doing so could create another Apple certificate. Inspect the account and recover intentionally.

The tool does not install certificates in the macOS Keychain, manage private keys in cloud HSMs, revoke older certificates, regenerate provisioning profiles that reference a newly issued certificate, or automatically renew certificates without user approval. Apple may reject types that are not allowed for the authenticated team. Developer ID certificates require separate Apple workflows.
