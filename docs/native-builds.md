# Native builds

`build` previews configured commands. Add `--apply` to execute them. Preparation commands are explicit argv arrays and run in the directory containing the YAML, without a shell. Never put passwords in arguments. YAML is executable build configuration and must be reviewed before applying it.

```yaml
build:
  project: platform/apple/App.xcodeproj
  scheme: iOS
  configuration: Release
  archive_path: artifacts/ios/App.xcarchive
  export_path: artifacts/ios/export
  export_options: artifacts/ios/export-options.plist
  allow_provisioning_updates: true
  build_settings:
    DEVELOPMENT_TEAM: YOUR_TEAM_ID
    CODE_SIGN_STYLE: Automatic
  prepare_commands:
    - executable: haylen
      arguments: [platform, xcodegen, ., --platform, ios, --config, Release]
```

Apple builds run `xcodebuild archive` followed by `xcodebuild -exportArchive`. Supply a valid export-options plist, distribution identity and entitlement-compatible profile. The artifact path in the version must name the actual exported IPA. Use an explicit bundle version and wait for store processing after upload.

```yaml
build:
  gradle_wrapper: platform/android/gradlew
  task: bundleRelease
  artifact: artifacts/android/App.aab
  prepare_commands:
    - executable: haylen
      arguments: [prepare, ., --platform, android, --config, Release]
  finish_commands:
    - executable: python3
      arguments: [scripts/stage-android-bundle.py]
```

The Gradle Wrapper runs with its parent directory passed as `--project-dir`. An optional finish command can stage a bundle from a toolchain-managed build directory into the YAML project directory. Missing or non-executable wrappers and missing output artifacts fail explicitly.

Subprocess output is captured and omitted from exceptions because external tools can print credentials. Reproduce a failed command locally when debugging and keep any diagnostic logs outside version control. The publisher does not write native build logs.

Apple build file reservations declare the required `assetType: ASSET`, file name, file size and IPA/PKG UTI. Contract reference: [BuildUploadFileCreateRequest attributes](https://developer.apple.com/documentation/appstoreconnectapi/builduploadfilecreaterequest/data-data.dictionary/attributes-data.dictionary).

Google Play processes the internal track automatically. Internal release commits omit `changesNotSentForReview`, which the API rejects for automatic review. Other tracks defer review when `publication.submit_for_review` is false. All edits are validated before commit, and changes under review remain protected by `ERROR_IF_IN_REVIEW`.
