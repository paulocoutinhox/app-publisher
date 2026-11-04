# Production release checklist

1. Create and verify the existing App Store Connect and Google Play applications manually. Confirm both Bundle ID and package name.
2. Ensure the Apple API key and Google service account have the least privileges necessary for the intended release.
3. Run `app-publisher validate` on the YAML and verify every localization and screenshot path.
4. Run `app-publisher doctor` on the machine that will build or capture screenshots.
5. Run `app-publisher screenshots batch ... --apply` if using deep-link navigation. Visually inspect captures on each relevant simulator or device.
6. Run `app-publisher screenshots render ... --apply` if composing marketing screenshots. Confirm store image requirements.
7. Run `app-publisher build ... --apply` if native builds are required. Verify actual IPA, PKG or AAB files and signing outside this CLI.
8. Run `app-publisher diff` and review the intended operations for every selected provider.
9. Test `sync --apply` and `release --apply` using dedicated internal test applications before any production credentials.
10. Confirm Google Play edits and review flags, Firebase app IDs and Apple build processing through the respective consoles.
11. Run `app-publisher beta ... --apply` for processed builds when needed.
12. Complete the remaining Apple privacy, legal and regional availability forms, and Google content declarations in the consoles.
13. Run `app-publisher review ... --apply` after metadata, screenshots, legal information and processed Apple build are all ready.
14. Verify status in both stores and archive the CLI output along with the exact versioned YAML used for the release.

A mocked test suite cannot replace a real store submission. Before external release, execute authenticated smoke tests against the current publisher API versions.
