# Architecture

The CLI delegates configuration decoding to strict Pydantic schemas and local asset inspection to Pillow. A separate engine constructs remote provider clients and coordinates validation, dry runs, writes and read-only status inspection.

Apple uses signed ES256 JWT requests to the App Store Connect API. Google Play and Firebase use OAuth application-default credentials. HTTP paths, Apple JSON:API envelopes, Google `edits` transactions and Firebase long-running operations are isolated inside provider classes.

External writes require explicit `--apply`. Apple app identifiers are double-checked before writes. Google Play edits are isolated until commit, subject to the provider's limitations. Data Safety is a separate POST and therefore not atomic with an edit transaction. Firebase project and app creation is independently scoped and permissions-controlled.

Screenshot capture is independent of publication. A user may use an existing asset directory without installing Xcode or ADB. Platform capture tools are launched only for the explicitly requested platform.

For production usage add a staged smoke test with real publisher credentials and private test applications. Unit tests intentionally never call the network.

## Reconciliation plans

`core/sync_plan.py` creates a deterministic hash of the YAML and source assets and stores a textual remote diff as an approval plan. `apply-plan` performs the same checks again before writing. The diff is a preflight guard, not a transaction or an atomic provider snapshot. Each platform retains its own server-side semantics.

`core/diagnostics.py` translates structured provider errors to actionable, redacted messages. JSON result files are exclusive-created to avoid accidental replacement. `providers/google_publisher.py` uses official image SHA-256 values to skip uploads and checks existing release tracks before replacing them.
