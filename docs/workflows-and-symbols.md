# Workflows and Crashlytics

The YAML defines intended work. Every mutating command remains a preview without `--apply`. `apply-plan` also requires this flag. Enum options accept any letter case. Product IDs, account identities, locale keys, file paths and text keep their spelling.

## Declared publishing stages

```yaml
publication:
  workflow:
    journal: artifacts/workflow-journal.json
    source_inputs: [source/**/*.lua, app.json, release.yaml]
    steps:
      - {id: validate, action: validate}
      - {id: build-apple, action: build, provider: apple}
      - {id: symbols-apple, action: symbols, provider: apple}
      - {id: metadata-apple, action: sync, provider: apple}
      - {id: upload-apple, action: release, provider: apple}
      - {id: processing, action: wait, provider: apple, timeout_seconds: 900}
      - {id: testing, action: beta, provider: apple}
```

The same configuration must declare its builds, artifacts, metadata, symbols and TestFlight group IDs. Do not include production review or launch stages in a testing workflow. Supported actions also include `capture`, `render`, `privacy`, `signing`, `review`, `launch` and `inspect`. Stage order is explicit. Unknown actions and duplicate IDs are rejected.

```bash
app-publisher workflow app.yaml
app-publisher workflow app.yaml --apply
app-publisher workflow app.yaml --apply --resume
```

A preview creates no journal and performs no stage commands. Applying creates protected local state with source/configuration hashes, artifact hashes, completed stages and redacted outcomes. A file lock prevents two local runs sharing a journal. A new run refuses an existing journal. Resume skips completed stages, refuses drift and does not rebuild an already completed artifact.

An interrupted or failed stage may have applied remote changes. Inspect the store first. `--resume --retry-failed --apply` explicitly retries that stage after reconciliation by the operator. This flag is not a rollback or a guarantee that arbitrary external commands are idempotent. Keep journals private and use a new path for a new intended release. Remove a stale lock only after verifying no process still owns the workflow.

Declare relevant source inputs so a source edit invalidates resume. Generated files and build artifacts should not be source inputs. Store screenshots are generated only when capture/render stages are declared. Their navigation URLs must be supported by the app.

## Apple Crashlytics dSYMs

```yaml
firebase:
  project_id: your-firebase-project
  crashlytics:
    apple:
      - app_id: 1:123456789:ios:abcdef123456
        bundle_id: com.example.app
        version: 1.0.0
        build_number: '1'
        configuration: private/GoogleService-Info.plist
        archive: artifacts/App.xcarchive
        platform: ios
        upload_tool_env: FIREBASE_UPLOAD_SYMBOLS_PATH
        timeout_seconds: 600
```

Set `FIREBASE_UPLOAD_SYMBOLS_PATH` to the executable `Crashlytics/upload-symbols` from the installed Firebase Apple SDK. The original config and archive are read only. The publisher verifies Firebase project/app/bundle identity, archive version/build and dSYM UUID/architecture association before uploading. Missing or unrelated symbols fail locally.

```bash
app-publisher symbols app.yaml --provider apple
app-publisher symbols app.yaml --provider apple --apply
```

The preview can invoke local `dwarfdump` validation, but performs no network symbol upload. A symbols-only retry does not rebuild or send another store binary. A successful uploader exit proves that operation completed. Verify crash ingestion and symbolication separately on an authorized testing build. See [Firebase's official dSYM instructions](https://firebase.google.com/docs/crashlytics/ios/get-deobfuscated-reports).

## Android Crashlytics symbols

```yaml
firebase:
  project_id: your-firebase-project
  crashlytics:
    android:
      - app_id: 1:123456789:android:abcdef123456
        package_name: com.example.app
        version_code: 1
        configuration: private/google-services.json
        artifact: artifacts/App.aab
        gradle_wrapper: platform/android/gradlew
        variant: release
        bundletool_env: BUNDLETOOL_PATH
        upload_mapping: true
        upload_native: true
```

Set `BUNDLETOOL_PATH` to the official Bundletool JAR. The publisher verifies Firebase identity and actual AAB package/version, then runs the selected variant's `uploadCrashlyticsMappingFile...` and/or `uploadCrashlyticsSymbolFile...` tasks. The native project must configure the relevant Firebase Gradle plugins and symbol paths. Missing tasks fail explicitly. The Firebase plugin owns build-ID generation and its own mapping/native upload protocol.

This is separate from Google Play's `release.deobfuscation_files`. Configure both destinations when needed. Enabling native symbol upload does not install the Crashlytics NDK SDK into an application. See [Firebase's Android NDK integration](https://firebase.google.com/docs/crashlytics/android/get-started-ndk).

## Application commercial configuration

Product prices, periods, territories and offers belong to the application's YAML. The publisher transmits the declared store values and price-point IDs. It does not select a business price, compute a discount or apply an application-specific ceiling. Resolve the intended store price-point identifiers when preparing the application's configuration.

## Processing and editor schema

```bash
app-publisher wait app.yaml --timeout 900
app-publisher schema
```

Processing selection includes the exact app ID, marketing version, platform and counter. The wait is bounded and fails on rejected or unknown states. TestFlight requires VALID, unexpired builds. The schema describes supported configuration, not every endpoint offered by external providers.
