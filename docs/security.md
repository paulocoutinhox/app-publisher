# Security

- Never commit `.p8` private keys, Google service-account JSON, Android signing keys or generated Firebase configuration files.
- Use narrow roles and dedicated publishing service accounts, and rotate their credentials.
- Restrict provider access to the known Apple App ID/Bundle ID or Google package name.
- Use a dry run and a reviewed YAML change before `--apply` in CI.
- Redact OAuth tokens, JWTs and signing material from logs and error reports.
- The current version does not provide encrypted local state or enterprise-grade audit storage.
- A store's response is never trusted as an instruction. Unknown operation states must fail with an actionable error.
- Remote screenshot upload URLs are returned by Apple and executed with provider-prescribed methods and headers. They can carry temporary upload credentials. Avoid logging these URLs.
- Google Play edit commits and Firebase provisioning are irreversible external changes. Test in sandbox applications.

## Reviewed publication

- Create a plan with `app-publisher plan app.yaml --output plan.json` before modifying a live app.
- Approve the plan and run `app-publisher apply-plan app.yaml --plan plan.json --report report.json`.
- Plans and reports use restrictive file permissions. They never overwrite an existing path or follow a final symbolic link.
- The plan digest is not a digital signature. Restrict filesystem access to reviewed plans and credentials.
- A plan expires logically when the YAML, declared upload assets, application identity or observed remote changes differ.
- Google image and release replacement require separate explicit flags, even if the general `--apply` flag is present.
- No automatic global rollback is possible after a provider has accepted changes. Reported failures include this limitation.

On POSIX, sensitive generated files use owner-only permissions. Windows uses its filesystem ACLs, so choose a directory restricted to the publishing account. POSIX mode-bit assertions do not establish a Windows ACL.
