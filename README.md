<p align="center">
  <a href="https://github.com/paulocoutinhox/app-publisher">
    <img src="extras/images/logo.svg" width="500" alt="App Publisher">
  </a>
</p>

<p align="center">
  <a href="https://github.com/paulocoutinhox/app-publisher/actions/workflows/test.yml"><img src="https://github.com/paulocoutinhox/app-publisher/actions/workflows/test.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/paulocoutinhox/app-publisher/blob/main/LICENSE.md"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-0.0.1-6854ed" alt="Version 0.0.1">
</p>

# App Publisher

Spend less time publishing. Keep application listings consistent, validate each release and deliver updates through one workflow. The Python package and command are named **`app-publisher`**.

## ✨ Features

The initial release focuses on making Apple and Google publishing reliable. Provider-specific configuration, validation and API operations live in focused modules. Build commands remain independent of the framework or engine. Additional distribution platforms can extend this structure without changing application code. Other integrations are not advertised as implemented until they are built and tested.

- Strict YAML configuration with explicit application identities, localized metadata and case-insensitive option values.
- App Store Connect metadata, screenshots, App Previews, build uploads and TestFlight distribution.
- Google Play listings, signed AAB/APK uploads, testing tracks, rollout settings and release notes.
- Native Xcode archive/export and Gradle builds with explicit preparation commands.
- Independent Crashlytics symbol uploads with archive UUID and application identity checks.
- Declared publishing workflows with protected journals and completed-stage resume.
- Product, subscription, pricing, signing, review and Firebase operations described in the [capability matrix](docs/compatibility.md).
- Screenshot capture, navigation plans and store artwork rendering with a supplied font.
- Dry runs, asset checksums, reviewable plans and redacted diagnostic reports.

Remote writes require `--apply`. Google dry runs can create and discard an edit without committing it. Changes across providers are not atomic. Read the [publication contract](docs/reconciliation.md) before automating a production workflow.

## 📦 Install

Install [UV](https://docs.astral.sh/uv/) and Python 3.11 or newer:

```bash
uv tool install git+https://github.com/paulocoutinhox/app-publisher.git
app-publisher --help
```

For development:

```bash
git clone https://github.com/paulocoutinhox/app-publisher.git
cd app-publisher
uv sync --extra dev
uv run app-publisher --help
```

Native Apple builds require macOS and Xcode. Android builds require the Android SDK, Java and the project's executable Gradle Wrapper. Uploading existing binaries does not invoke the build tools.

## 💡 Configure a release

Keep credentials outside your source repository. YAML refers to environment variable names for Apple authentication. Google uses Application Default Credentials.

```bash
export APP_STORE_KEY_ID="YOUR_KEY_ID"
export APP_STORE_ISSUER_ID="YOUR_ISSUER_ID"
export APP_STORE_KEY_PATH="/absolute/path/outside/repository/AuthKey_YOUR_KEY_ID.p8"
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/outside/repository/service-account.json"
```

Create the store application records first. Use their actual numeric Apple app ID and Android package name. This example targets only Google Play internal testing:

```yaml
schema_version: 1
app:
  id: example
  default_locale: en-US
publication:
  submit_for_review: false
google:
  package_name: com.example.app
  release:
    track: internal
    status: completed
    artifact: artifacts/app-release.aab
    version_codes: ["1"]
    confirm_track_replacement: false
locales:
  en-US:
    google:
      release_notes: First internal testing build.
```

Google Play may require initial setup, declarations, agreements or the first release to be completed in the Console before API releases are accepted. `completed` on the internal track makes a release available to its testers, subject to Google's processing and account requirements. It does not publish to production. Use `draft` to keep the release unpublished.

See [examples/app.yaml](examples/app.yaml), [examples/full.example.yaml](examples/full.example.yaml) and the [configuration guide](docs/configuration.md) for Apple, localization and optional features.

## 🛠️ Publish

```bash
app-publisher doctor-full app.yaml
app-publisher validate app.yaml

# Build commands are previews until --apply is supplied.
app-publisher build app.yaml --provider google
app-publisher build app.yaml --provider google --apply

# Upload a configured binary and update its testing track.
app-publisher release app.yaml --provider google
app-publisher release app.yaml --provider google --apply

# Inspect live state without publishing a release.
app-publisher inspect app.yaml
```

Build numbers are explicit release identifiers. Start at `1` and increment by one. Keep them separate from the displayed version, such as `1.0.0`. Google artifact releases require an expected version code before any store request.

Apple `release` uploads a build using the `buildUploads` and `buildUploadFiles` APIs. Processing happens asynchronously. Configure the exact TestFlight group IDs and build number, then run `app-publisher beta app.yaml --apply` after processing completes. App Review submission and production launch are separate, explicit commands.

Enum values such as `manual`, `Manual` and `MANUAL` are equivalent. The publisher sends canonical API values while preserving product IDs, paths, locales and text. Export the strict editor schema with `app-publisher schema`.

For metadata and assets, generate and review a checksum-bound plan:

```bash
app-publisher plan app.yaml --provider google --output private/release-plan.json
app-publisher apply-plan app.yaml --plan private/release-plan.json
app-publisher apply-plan app.yaml --plan private/release-plan.json --apply
```

The `private/` directory must already exist. Reports and plans refuse to overwrite existing files and are created with restrictive permissions. A plan verifies local inputs and the current diff. It cannot lock a remote store against concurrent changes.

## 🔐 Credentials

Follow the [credential setup guide](docs/credentials.md) to create an App Store Connect team API key, authorize a Google service account and configure an Android upload keystore. The original credential files are read only. Do not put passwords, private keys or service-account contents in YAML, arguments, screenshots or issues.

Native build output is captured and excluded from error messages. The CLI redacts provider diagnostics and omits invalid YAML values from validation errors. The ignore rules protect common local files, but inspect the exact Git index before making a repository public.

## 🧪 Development

```bash
make install
make lint
make coverage
make build
make check
```

Ruff checks imports, lint and formatting. Tests use mocked HTTP boundaries, temporary files, controlled build commands and a bundled OFL-licensed font. The coverage gate requires 100% statement and branch coverage. This verifies implemented paths and does not establish live acceptance of every external API operation.

## 📚 Documentation

- [Architecture](docs/architecture.md) and [agent contract](AGENTS.md).
- [Configuration](docs/configuration.md) and [credential setup](docs/credentials.md).
- [Capability matrix and limitations](docs/compatibility.md).
- [Native builds](docs/native-builds.md), [TestFlight and symbols](docs/review-and-symbols.md).
- [Declared workflows and Crashlytics](docs/workflows-and-symbols.md).
- [Plans and reconciliation](docs/reconciliation.md), [security](docs/security.md).
- [Testing](docs/testing.md), [release checklist](docs/release-checklist.md).

## 🤝 Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Keep operations explicit, add failure-path coverage and document which capabilities were tested with mocks or accepted by a live store.

## ☕ Buy me a coffee

<a href="https://ko-fi.com/A0A412XEV"><img src="https://storage.ko-fi.com/cdn/kofi2.png?v=6" height="36" alt="Buy me a coffee"></a>

## 📄 License

[MIT](LICENSE.md). Copyright © 2026 Paulo Coutinho.
