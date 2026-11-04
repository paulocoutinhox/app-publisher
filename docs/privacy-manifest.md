# Generate Apple's privacy manifest from YAML

This feature writes a local Apple `PrivacyInfo.xcprivacy` as a standard XML property list. It does not use a private API and does not submit the App Privacy data-collection questionnaire to App Store Connect.

```yaml
apple:
  privacy_manifest:
    output: Sources/App/PrivacyInfo.xcprivacy
    tracking: false
    tracking_domains: []
    collected_data:
      - data_type: NSPrivacyCollectedDataTypeEmailAddress
        linked: true
        tracking: false
        purposes:
          - NSPrivacyCollectedDataTypePurposeAppFunctionality
    accessed_apis:
      - category: NSPrivacyAccessedAPICategoryUserDefaults
        reasons:
          - CA92.1
```

Run `app-publisher privacy-manifest config.yaml` to see whether the file would change, followed by `app-publisher privacy-manifest config.yaml --apply` to update it atomically. The tool validates the declared structure, supported purpose keys and required-reason identifiers' syntax. It cannot determine whether a reason is permitted for your specific API usage or validate every Apple data type enum against a live Xcode release.

**Important:** adding the manifest to the repository is not enough. Ensure the appropriate Xcode target bundles it and audit privacy manifests contributed by all third-party SDKs. The data collection form in App Store Connect must still be completed and kept consistent with actual user data practices. The Google Play Data Safety CSV uses a separate official API workflow.
