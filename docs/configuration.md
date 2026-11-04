# Declarative YAML configuration

Use [`examples/app.yaml`](../examples/app.yaml) as the minimal starting point and [`examples/full.example.yaml`](../examples/full.example.yaml) for optional fields. The top-level schema is `schema_version: 1`. Unknown keys, unknown enum values and impossible rollout fractions are rejected. Declared enum values accept any letter case and serialize to the official API spelling. For example, `manual`, `Manual` and `MANUAL` all mean `MANUAL`. Configuration field names, locale keys, arbitrary API payloads, product IDs, paths and prose are not globally case-normalized. Google image-group names are normalized, with duplicate canonical groups rejected. `app-publisher schema` exports the complete typed JSON Schema.

## Application and locale selection

`app.id` is a local identifier. `app.default_locale` must appear in `locales`. `app.paid` is a manual declaration that does not modify store pricing. Each entry under `locales` may provide `common`, `apple` and `google` blocks. Common `name`, `description` and `release_notes` fill platform equivalents when the platform-specific value is absent.

Apple platforms are `IOS`, `MAC_OS`, `TV_OS` and `VISION_OS`. Watch apps typically belong to an iOS container. Apple screenshot groups use placement identifiers resolved dynamically by `app-publisher devices`. `IPHONE_DUO` may be used when the current API provides an unambiguous matching group.

Google image groups are named exactly as Google Play `AppImageType` enum values: `phoneScreenshots`, `sevenInchScreenshots`, `tenInchScreenshots`, `tvScreenshots`, `wearScreenshots`, `icon`, `featureGraphic`, `tvBanner`. Different Android form factors generally do not require separate apps in Play Console.

All declared asset globs are relative to the YAML directory. Paths are sorted for stable screenshot ordering. Missing files are validation failures. Declaring an image group instructs the publisher to replace the remote group. Missing groups are preserved.

## Apple

Set `apple.app_id`, `apple.bundle_id` and one or more platform versions. The app must be registered in App Store Connect. Authentication uses environment variable names `key_id_env`, `issuer_id_env` and `private_key_path_env`. Never include the private key itself in YAML.

Version artifacts use `artifact` and `build_number` together. Optional `build` runs Xcode archive/export using exactly one `project` or `workspace`, a `scheme`, `export_options`, `archive_path` and `export_path`. The exported artifact file still needs to be explicitly identified as `artifact` for subsequent upload.

`apple.review` configures reviewer contact fields, demo username/password environment variable names and notes. Run `app-publisher review ... --apply` only after the selected version is fully ready. Review submissions are created separately per Apple platform. When purchases or subscriptions have editable versioned metadata, `review-products` creates review submission items for those draft product versions, provided the first purchase was already submitted with an app binary.

`apple.categories` uses official App Store category resource IDs under relationship keys like `primaryCategory`. `apple.age_rating` accepts only known Apple API age rating field names. Responses must accurately reflect the application's content.

`apple.verify_base_territory` verifies the current base territory without modifying pricing. `apple.pricing` can replace the configured app price schedule using official price-point IDs, only with `confirm_price_changes: true`. `apple.preorder_territory_availability` can update pre-order territory availability where the API permits it, not general country distribution for already published apps.

`apple.in_app_purchases` declares non-renewable product IDs with `name`, `purchase_type`, `review_note`, `available_in_all_territories` and `localizations` mapping locales to `{name, description}`. Products are managed through the current versioned IAP API. Product ID and type are immutable. `apple.subscription_groups` declares subscription groups, localized group names and renewable subscriptions with pricing. Subscription period is immutable. `confirm_subscription_price_changes: true` must be explicit before live subscription price writes. Product review submissions use the separate `review-products` command.

`apple.signing.certificates` declares existing Apple signing certificate IDs and local output paths. `apple.signing.profiles` declares provisioning profile name, profile type, certificate IDs, optional device IDs and a local output path. `create_if_missing: true` permits creating a new profile when its name is absent. The manager verifies the Apple bundle identifier before updating outputs and rejects an existing local file with different bytes. Use `app-publisher signing CONFIG --apply` separately from metadata synchronization. Apple signing CSR issuance and password-encrypted private key creation are supported as guarded opt-in operations. Unattended key rotation is not supported.

`beta.group_ids` uses existing TestFlight group IDs and an already processed build number. Group creation and build processing are separate operations.

## Google Play

`google.package_name` identifies the existing store listing. An optional `release` configures `track`, `status`, `rollout_fraction`, AAB `artifact`, `version_codes` and `testers`. An `inProgress` rollout requires a fraction in `(0, 1)`; other release statuses may not specify a fraction.

`release.build` runs the declared Gradle wrapper and task. Signing remains part of the Gradle project. `store_details` provides `default_language`, `contact_website`, `contact_email` and `contact_phone` through `edits.details`.

The `data_safety_csv` file is uploaded through the Data Safety API, which is separate from the Google Play edit transaction.

Each Google `subscriptions` or `one_time_products` item provides a `product_id`, explicit `update_mask`, `regions_version` and official API request `data` object. Identity changes to product ID and package name are rejected. `google.subscription_offers` supports offer upsert with nested update masks and state changes. `google.base_plan_states` explicitly activates or deactivates existing base plans. These monetization APIs are independent of the listing edit transaction and have not been verified live.

## Firebase

`firebase.project_id` selects a Google Cloud/Firebase project. With `create_if_missing: true` the publisher can create a Google Cloud project and add Firebase if the account has the required permissions and quotas. `apple_apps` and `android_apps` are registered by Bundle ID or package name, and their configuration files are written at `output`.

Android Firebase applications can declare `sha_certificates` with `sha_hash` and `certificate_type` (`SHA_1` or `SHA_256`). Config file download does not integrate the Firebase SDK into your app automatically.

## Screenshot automation

`publication.screenshot_plans` contains a platform, device ID and scenes with `name`, `url`, `output` and `delay_seconds`. Each scene navigates to a deep link, waits and captures the device screen. macOS uses `open` for navigation and `screencapture` for the desktop rather than iOS simulator commands. The app must expose deterministic deep links. Native simulator/device SDKs are required.

`publication.screenshot_designs` contains a `source` image, PNG `output`, explicit TrueType `font`, `title`, dimensions, colors, font size and padding. The renderer preserves aspect ratio and refuses titles too long for the canvas. No implicit system-font fallback is performed.

## Write safety

Read-only commands validate YAML and compare with remote resources. `--apply` enables publication mutations. Absent fields are ignored, not implicitly cleared. Google image groups declared in YAML are replaced as a whole. Remote APIs may reject edits during review or after approval, and the CLI fails rather than silently mutating another version.

## Added declarative operations

- `apple.territory_expectations` is a read-only map of Apple territory IDs to required availability. `app-publisher availability` reports mismatches and never edits the app's country availability.
- `google.country_expectations` contains per-track CLDR country codes, optional `sync_with_production`, and optional `rest_of_world`. Country availability is read through a temporary Play edit and the edit is deleted. There is no official write endpoint for this resource.
- `apple.signing.issuance` contains `certificate_type`, `common_name`, `email_address`, `private_key_output`, `csr_output`, `certificate_output`, `password_env` and `confirm_creation`. The private key uses encrypted PKCS#8 and is created with owner-only permissions.
- `apple.privacy_manifest` declares a local `PrivacyInfo.xcprivacy`, tracking domains, collected data and required-reason APIs. `app-publisher privacy-manifest CONFIG --apply` creates or updates the file on disk.
- `publication.screenshot_plans[].scenes[].actions` describes deterministic actions to execute after opening the scene's URL. Android supports `tap`, `swipe`, `text`, `launch`, `terminate`, `open_url` and `wait`. Apple simulators support `launch`, `terminate`, `open_url` and `wait`. macOS supports `launch`, `open_url` and `wait`. Unsupported actions are rejected by the YAML schema.

See the dedicated documentation files for complete examples. All signing output paths and privacy manifest output paths must resolve within the YAML's parent directory. Never commit private keys or generated credentials.

## Official release and accessibility features

Use `app-publisher launch CONFIG` for a read-only plan and `app-publisher launch CONFIG --apply` to release a version that Apple has already approved. Explicit `manual_release: true` and `release_type: MANUAL` must appear in the matching `apple.versions[]` entry. Use `phased_release: true` to enable Apple's phased-release schedule on an eligible version. App Publisher never assumes review approval.

Use `apple.accessibility` to declare device-family capabilities. Fields are optional Boolean declarations. Only explicitly declared values are synchronized. A declaration can opt into publication with `publish: true`; publishing is not implied by the existence of a YAML entry.

```yaml
apple:
  accessibility:
    - device_family: IPHONE
      voiceover: true
      captions: true
      sufficient_contrast: true
      publish: false
```

Google Play release supports an optional `name`, `in_app_update_priority` between zero and five, and `country_targeting` for the `production` track only while `status: inProgress`. `countries` are uppercase, two-character country codes. Example:

```yaml
google:
  release:
    track: production
    status: inProgress
    rollout_fraction: 0.10
    version_codes: ["100"]
    name: October release
    in_app_update_priority: 3
    country_targeting:
      countries: [BR, US]
      include_rest_of_world: false
```

Set these optional fields only when the app has the requisite permissions and business approval. All file paths stay within the YAML parent directory, including symbolic-link targets.

## Expanded beta and offer configuration

`apple.beta_groups` declares named internal or external TestFlight groups. External groups can configure a public link and limit. Each tester has `email`, optional first/last names and an opt-in `invite` flag. Running `app-publisher beta CONFIG --apply` creates groups, registers/links testers and optionally sends invitations. The program never removes undeclared testers or groups. Pre-existing group IDs are still required when linking a specific Apple build to a TestFlight group.

`apple.signing.devices` contains device UDID, name and platform (`IOS` or `MAC_OS`). Existing registrations must agree with the configuration; disabled devices are not silently reactivated.

`apple.verify_paid`, when set to `true` or `false`, requests an explicit comparison between the declared flag and an effective manual Apple price in the base territory. It is executed by `app-publisher inspect` and fails if the schedule is ambiguous. Google Play does not expose the equivalent application-level flag through its public Publishing API.

Each Apple subscription can contain `introductory_offers`, `promotional_offers`, `win_back_offers` and `offer_codes`. These require official territory or price-point identifiers. Existing offers with immutable differences are rejected rather than silently replaced. `google.one_time_offers` includes product/purchase-option/offer identifiers, update mask, regions version, a Play API-compatible body and an explicit desired state.

Run `app-publisher inspect CONFIG` for read-only detailed store review, TestFlight and track inspection. Use `--provider apple` or `--provider google` to restrict this operation.

See [workflows and symbols](workflows-and-symbols.md) for protected execution journals, standalone Crashlytics delivery, Apple processing waits .

Declare update masks as YAML lists, for example `update_mask: [listings, basePlans]`. The publisher joins the paths with commas only at the Google API boundary. Scalar comma-delimited masks are rejected.
