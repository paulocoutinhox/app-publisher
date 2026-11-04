# Declarative reconciliation

The YAML is the intended configuration for **only the resources explicitly declared in the schema**. Fields that are missing from the YAML are preserved when the provider supports partial updates. The tool does not delete undeclared store data.

## Review and execute

1. Run `app-publisher validate app.yaml` to reject unknown keys, invalid texts and malformed local assets.
2. Run `app-publisher plan app.yaml --provider all --output approval.json` to collect the remote diff and the checksums of publication inputs.
3. Review `approval.json`, including its application IDs, resource changes and caveats.
4. Run `app-publisher apply-plan app.yaml --plan approval.json --report result.json` to verify that the same YAML, assets and observed remote differences still apply.
5. If a preflight check fails, inspect the store state, correct the YAML and create a new plan. Do not edit the old plan.

Plan files and reports are written with permissions `0600` on POSIX-compatible filesystems and are never overwritten. They do not contain OAuth credentials. The digest is **not** a MAC or digital signature and does not protect against an attacker with permission to edit the plan.

## Google Play safeguards

- Android Publisher `edits` allows preparing changes and validating them before commit. App Publisher calls `edits.validate` and sets `changesInReviewBehavior=ERROR_IF_IN_REVIEW` on commit.
- Uploaded images expose SHA-256 digests. App Publisher compares the ordered remote image hashes with the ordered local files and skips identical groups.
- Existing mismatched image groups require `google.confirm_image_replacement: true`.
- Replacing an existing track with a new release requires `google.release.confirm_track_replacement: true`.
- The Data Safety update is a separate API operation. If it fails after an edit commits, the previous edit remains committed and the command reports an error. There is no silent rollback.

## Apple safeguards

- The configured Apple App ID must resolve to the configured Bundle ID before publishing.
- Versions under review are blocked from metadata mutations.
- The App Asset Library is used to upload and place screenshots and videos.
- App Review and manual release operations remain separate, explicit commands.

## Errors

If an edit fails and its cleanup also fails, the original API error is preserved and the cleanup failure is attached as a separate diagnostic.

The optional `--report report.json` flag writes a structured, non-overwriting JSON summary with the provider, action, error category, HTTP status when known, a remediation suggestion and a warning about potential partial writes. Secrets in known bearer/token/password patterns are redacted.

| HTTP status | Typical response |
| --- | --- |
| 400 | Verify field values and publication state |
| 401 | Check credential expiration |
| 403 | Verify roles, scopes and account permissions |
| 404 | Verify application and resource IDs |
| 409 or 412 | Refresh the plan and check concurrent updates |
| 429 | Respect rate limits and retry later |
| 5xx | Inspect remote state before attempting the write again |

## Important limits

This is an application publishing reconciler, not a generic orchestrator for every possible Apple, Google and Firebase API resource. The complete vendor APIs also include financial, analytics, reporting, account administration, fraud, orders and numerous other independent product families. Adding arbitrary REST methods from YAML would defeat type validation and the safe, predictable behavior of the application.

Remote resources may change after preflight. APIs from different providers cannot be combined in an atomic transaction. `apply-plan` reduces accidental mistakes, not every concurrency race. Always use scoped credentials and a separate test application for initial deployment.
