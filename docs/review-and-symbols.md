# Reviews, deletion, APK and symbols

`app-publisher reviews config.yaml` lists customer reviews using only read calls for Apple. Google reviews are also read without a Google Play edit transaction. The output can include personal information authored by reviewers; do not send it to public CI logs.

`app-publisher reply-reviews config.yaml` previews differences. `--apply` publishes only the YAML responses marked `confirm_publication: true`. All declared review IDs are verified as belonging to the configured application. The command does not run from `sync` or `release`, does not generate responses using AI and does not post unsolicited replies.

`app-publisher delete-listings config.yaml` previews Google language deletion. `--apply` requires `confirm_deletion: true`. Missing language resources are ignored. It refuses deletion of a locale also declared for update and the configured default locale. A Google edit is committed only when a deletion is needed. The API cannot make the operation atomic with Apple or Firebase requests.

Google release artifacts may be `.aab` or `.apk`. Deobfuscation files are declared by numeric `version_code` with `file_type: proguard` or `file_type: nativeCode`. They are uploaded inside the Google edit before the release track is updated. The version code must match the release. The local file must be under the YAML project folder and exist when publishing. Keep mapping files securely archived because they are required for later crash analysis.

The review and upload clients are mocked in the test suite. A real store publish requires permissions and may be rejected because of account, app state or changing business rules.
