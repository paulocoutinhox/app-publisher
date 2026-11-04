# App Publisher engineering contract

App Publisher is version 0.0.1. Its repository is `paulocoutinhox/app-publisher`. The Python distribution and command are `app-publisher`. The Python import package is `app_publisher`. The CLI publishes declared application releases through official APIs.

## Project map

```text
pyproject.toml, uv.lock              Package metadata, single version source and dependency lock
src/app_publisher/cli.py               Typer entry point and explicit write flags
src/app_publisher/config.py            Safe YAML decoding and strict validation diagnostics
src/app_publisher/models/              One strict Pydantic model per module
src/app_publisher/enums/               One case-insensitive domain enum per module
src/app_publisher/errors/              One exception class per module
src/app_publisher/core/                Authentication, APIClient, PublicationEngine, assets, plans and reports
src/app_publisher/providers/           One provider responsibility per class/module
src/app_publisher/toolchain/           BuildRunner, EnvironmentDoctor and ToolCheck
src/app_publisher/screenshots/         Capture, navigation, planning and artwork classes
examples/                           Sanitized declarative configuration examples
tests/                              Unit, CLI and HTTP-mocked integration tests
tests/fixtures/                     Portable Poppins font, its OFL license and anonymized API fixtures
docs/                               Configuration, supported operations and operational limits
extras/images/                      SVG and PNG identity artwork
.github/workflows/                  Cross-platform tests and package validation
```

## Architecture

The CLI loads a `ProjectConfig`. `PublicationEngine` validates declared inputs and delegates to provider classes. `APIClient` owns authenticated JSON requests, safe read retries and pagination. Apple uses short-lived ES256 tokens. Google Play and Firebase use Application Default Credentials. Binary uploads use provider-specific streaming or multipart operations. `BuildRunner` invokes explicit argv arrays without a shell. Project artifacts stay inside the YAML project directory.

YAML models reject unknown fields. Each provider uses its official API schema and validates application identity before writes. Google edits are validated before commit and discarded when no changes are committed. Data Safety, Firebase mutations and operations across stores are independent transactions. An error must preserve the original failure if edit cleanup also fails.

`plan` and `apply-plan` bind metadata synchronization to the YAML, assets and the current diff using SHA-256. They are preflight review aids, not distributed transactions or remote locks. The `release`, `beta`, `review` and `launch` commands have distinct purposes. `apply-plan` previews unless `--apply` is present. `workflow` runs explicitly declared stages with a protected execution journal, source/artifact hashes and completed-stage resume. A partial stage requires remote inspection before an explicit retry. Uploading a build is not a production launch.

## Mandatory standards

- Use Python 3.11+, UV and Ruff. Keep all `__init__.py` files completely empty.
- Use one class or enum per module. Module names match the class using Python-required snake_case. Other filenames use dashes.
- Keep code, comments and documentation in English. Comments explain only non-obvious intent using complete sentences.
- Use descriptive names, explicit state transitions, early returns and blank lines between responsibilities.
- Format with Ruff at 110 columns. Allow multiline signatures and calls for readable code.
- Do not use `TYPE_CHECKING`, compatibility facades, speculative defaults, broad exception suppression or runtime reflection to conceal control flow.
- No semicolon-separated statements. Do not duplicate business logic or extract artificial abstractions.
- Credentials come from environment variables or ADC. Never persist private key contents or passwords in YAML, reports or logs.
- Preserve original credential files. Avoid logging subprocess output, authentication payloads and invalid YAML input values.
- `CredentialHelper` owns diagnostic redaction. JSON reports use exclusive creation and restrictive file permissions.
- Every remote write requires explicit `--apply`. Dry-run Google edits may be created and discarded but never committed.
- Existing image groups and release tracks require explicit YAML replacement authorization.
- Never infer unknown app IDs, package names, versions, signing identities or API resource types.
- Use official public APIs. Document console-only settings and asynchronous processing limitations.
- Tests never call real stores. pytest-socket disables network sockets by default. Keep the complete HTTP boundary mocked and add negative cases for publication safeguards.
- Keep AGENTS.md current. Do not record implementation history or put private app credentials in this public project.

## Quality gates

Run `make lint`, `make coverage`, `make build` and `make check`. Lint includes `ruff check` and `ruff format --check`. Coverage requires 100% statements and branches. Continuous CI exercises Linux and Windows on Python 3.11, 3.13 and 3.14. The manual workflow input include-macos adds macOS 15 Intel to the same complete matrix. Local macOS ARM64 runs use the same tests. A passing mock suite does not establish acceptance of every live API operation. Record real store validation separately and do not claim unsupported capabilities.

Before a public push inspect the exact staged files and scan for secrets. Exclude logs, reports, plans, local YAML, credentials, keys, signing files, app binaries, caches, distributions and editor state. Keep `uv.lock`, examples, source artwork, the licensed test font and its license tracked. The GitHub workflow validates tests and packages.

## Git conventions

Keep branch names and commit messages short and lowercase. Commits use a conventional type followed by `: ` and a concise message, such as `feat: add publishing` or `fix: validate upload`. Appropriate types include `feat`, `fix`, `build`, `docs`, `style`, `test`, `refactor` and `chore`. Feature branches use the same type with dashes, such as `feat-app-publishing` or `fix-upload-validation`. Keep main as the repository's trunk branch.

Never add co-author trailers for Codex, Copilot, Claude Code or another tool. Keep commits objective and free from tool attribution. Before every commit and push, inspect the exact Git index and confirm that temporary files, builds, logs, runtime output, credentials and signing material are excluded. Logs can contain secrets.

## Distribution scope

Product language covers application publishing and distribution without presenting iOS and Android as permanent limits. The current validation scope is reliable Apple and Google publishing. Keep provider configuration, validation and API operations separate from engine-specific build commands. Additional providers require an explicit capability contract and HTTP-mocked tests. Do not claim Playgama or other integrations before they are implemented and validated. Store build numbers come explicitly from YAML. Normally they start at 1 and increment by 1. An explicitly requested cross-store alignment may skip values to the next common accepted build. Never calculate a build from a display version.

## Declarative workflows, symbols and options

YAML enum values are case-insensitive through explicit `CaseInsensitiveEnum` subclasses. Models emit the canonical value required by each API. Field names, identifiers, product IDs, locale keys, paths and free text retain their case. Reject unknown options and duplicate Google image groups after normalization. Do not lowercase all YAML strings. `StrictModel` validates defaults and assignments and stores canonical enum values. Extend the domain enum when adding a new supported API option.

`CrashlyticsPublisher` is independent of store upload. Apple symbol delivery checks the Firebase configuration, archive identity and dSYM/Mach-O UUIDs before invoking the official Firebase uploader. Android checks the Firebase app/package and AAB version before invoking the selected Gradle variant's Crashlytics tasks. Firebase symbols and Play deobfuscation files are separate operations. Upload success does not prove crash ingestion or symbolication.

`AppleBuildManager` selects the exact app, marketing version, platform and counter through the documented global builds filters. Bounded processing waits fail on unknown or unsuccessful states. TestFlight distribution requires VALID, unexpired builds.

The workflow journal is local protected state, not a distributed transaction. It records only redacted results and error types. Do not resume with changed YAML, declared source inputs or recorded artifacts. Use a separate journal for a new intended execution. Do not infer full API coverage from the existence of a workflow action.

## Commercial API shapes

Google update masks are lists of field paths in YAML and models. Join them with commas only at the API transport boundary. Do not accept scalar masks as a compatibility format. Apple subscription availability uses current subscriptionPlanAvailabilities resources and explicit UPFRONT/MONTHLY payment-plan types. Keep these distinct from subscription billing periods. Existing territory changes require explicit confirmation, and price idempotence must include the payment-plan identity. Application prices and discounts belong only in that application's configuration.

Product review images are distinct from public screenshots. `AppleReviewScreenshotPublisher` owns their reservation, upload, commit, processing checks and guarded replacement. `AppleAssetUploadHelper` handles signed media transfer without sending the API bearer token. `AppleReviewFileHelper` enumerates declared review files for validation and plan/workflow hashes. `AppleReviewAssetHelper` owns the shared checksum, transfer, guarded replacement and processing protocol. `AppleReviewAttachmentPublisher` synchronizes version-level App Review attachments while preserving unconfigured files and reviewer fields.
