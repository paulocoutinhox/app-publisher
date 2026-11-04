# Capability matrix

The word **implemented** means there is Python code and mocked test coverage. It does **not** imply complete live acceptance of every API operation.

| Area | Apple | Google Play | Firebase |
| --- | --- | --- | --- |
| Existing app identity | Implemented, explicit App ID plus Bundle ID check | Implemented, package-scoped edit | Explicit project ID |
| Localized names, descriptions, notes | Implemented | Implemented | Not applicable |
| Support and marketing URLs | Implemented for Apple per locale | Website, email and phone via app details | Not applicable |
| App Review attachments | Version-level documents and videos, checksum verification and guarded replacement | Not applicable | Not applicable |
| Product review screenshots | Subscription and IAP reservations, multipart transfer, checksum commit and bounded processing | Not applicable | Not applicable |
| Store screenshots | Apple Asset Library, dynamic groups | Supported image type upload | Not applicable |
| iPhone Duo, iPad, tvOS, macOS, visionOS, watchOS | Apple device placements resolved from API data | Not applicable | Platform-specific Bundle IDs supported |
| Android phone, tablet, TV, Wear OS, XR, ChromeOS | Not applicable | Android image types exposed by public API | Android apps by package name |
| Art generation and multi-scene capture | Native iOS/tvOS/watchOS/visionOS/macOS capture plus Pillow art | Native ADB capture plus Pillow art | Not applicable |
| Compile and sign | Native Xcode archive/export; project controls signing | Gradle wrapper; project controls signing | Not applicable |
| Binary upload | Apple buildUploads and upload files | Google AAB/APK edit upload and optional deobfuscation file upload | Not applicable |
| Build processing, release tracks | Version status | Internal, testing and production tracks | Not applicable |
| Review submissions | Modern reviewSubmissions workflow; live unverified | Release commit and review flag | Not applicable |
| Testers | Manage TestFlight beta groups, link existing testers, register new testers and optionally invite, plus build linking by group ID | Google tester groups | Not applicable |
| Store categories | Primary/secondary relationship IDs | Console-only when API unavailable | Not applicable |
| Age rating | Apple ageRatingDeclarations PATCH | Console-only questionnaire | Not applicable |
| Privacy declaration | Privacy policy URLs and local PrivacyInfo.xcprivacy generation; detailed Apple questionnaire remains manual | Official Data Safety CSV | Not applicable |
| Review information | Review contacts and notes, demo credentials through environment | Release review is Play-managed | Not applicable |
| Paid/free status | Opt-in verification through effective manual base-territory Apple price point, fails closed for ambiguous pricing | No public Publishing API for app-level paid/free flag; reports unsupported | Not applicable |
| App price schedules | Base territory verification and guarded replacement of the price schedule | App-level price change not covered by Publishing API | Not applicable |
| In-app products and subscriptions | IAP v2 versioned metadata, subscription groups and renewable subscriptions, introductory/promotional/win-back/offer-code offers, guarded product prices, review submissions, unverified live | Subscriptions, one-time products, base-plan state changes, subscription offers and one-time purchase offers, unverified live | Not applicable |
| Territory availability | Pre-order territory flags and read-only availability auditing, no general country editing | Read-only per-track country availability auditing | Not applicable |
| Certificate lifecycle | Register Apple signing devices by UDID, download existing certificates and profiles, opt-in certificate issuance with encrypted private key and CSR, guarded profile creation; no unattended private-key rotation | Native Gradle signing, not key provisioning | Register Android SHA-1 and SHA-256 |
| Provision project/app | Store app creation intentionally manual | Store app creation intentionally manual | Implemented for projects, Apple and Android apps |
| SDK integration | Not part of a store publisher | Not part of a store publisher | Downloads app config files; does not install SDK |
| Legal, tax and banking details | Manual | Manual | Cloud billing is manual when required |

**Other implementation boundaries**

- A new app cannot reliably be created by the public store APIs. App Publisher requires a previously registered store app.
- Apple App Privacy data-use questionnaires are not fully supported by public App Store Connect REST APIs. App Publisher does not call private APIs or automate browser forms.
- Google Play content declarations and suitability questionnaires remain in the Play Console when no public API exists.
- Apple in-app purchase and subscription localization uses version-based endpoints, with separate App Review submission. Introductory offers, promotional offers, win-back offers and offer-code parent resources have YAML integration. Generation of custom and one-time-use subscription offer-code batches is included. Redemption reports, subscription promotion images, additional eligibility variants and app/IAP availability writes remain outside the implemented feature set. Subscription payment-plan availability can be declared by territory using current subscriptionPlanAvailabilities resources.
- Google Play subscription and one-time purchase offers, purchase-option state changes and explicitly confirmed purchase-option and offer deletion are modeled, but the supported update masks must match the exact official API schema. Changes to the app-level paid/free flag and some Console-only commercial settings remain manual.
- Apple store review approval, Google production eligibility, agreements, paid-account eligibility and policy decisions are outside the control of any CLI.
- Screenshots require the app to support the configured navigation deep links. With the optional idb driver, iOS gesture automation and tvOS remote commands can be configured, subject to target and companion support. Capturing a scene is not an automated guarantee that the correct view loaded.
- Screenshot composition is an explicit file transform. It preserves the screenshot aspect ratio without stretching.
- Apple signing downloads and guarded provisioning profile creation are implemented. Certificate issuance and encrypted private-key/CSR generation now have a guarded workflow. Keychain import, certificate revocation and unattended private-key renewal remain outside the current automatic workflow. Xcode and Gradle can sign using the existing project configuration.
- Apple app schedule and subscription price changes require explicit confirmation in YAML. Pricing confirmation does not change Google Play paid/free state. Treat changing free to paid on Google Play as an irreversible policy constraint.
- Live acceptance of Apple's newest asset APIs, including iPhone Duo group mapping, is unverified.

Reference APIs: [Apple App Store Connect](https://developer.apple.com/documentation/appstoreconnectapi), [Google Android Publisher](https://developers.google.com/android-publisher/api-ref/rest), [Firebase Management](https://firebase.google.com/docs/reference/firebase-management/rest).

- `doctor-full` validates installed SDK tooling and locally configured credentials without attempting network authorization.
- The generated `PrivacyInfo.xcprivacy` is an offline source file. It does not publish App Privacy answers, and the Xcode target must include the file as a resource.
- Google screenshot dimensions and RGB/RGBA restrictions are validated locally. The Store may impose additional changing requirements.

## Additions in the October 22 audited revision

- Apple accessibility declarations are synchronized by device family using official `accessibilityDeclarations` endpoints. Drafts can be updated and published. A published declaration with differing features is not mutated silently.
- Approved Apple versions configured for manual release can be launched through `app-publisher launch CONFIG --apply` when their remote status is `PENDING_DEVELOPER_RELEASE`. This is irreversible once accepted by Apple.
- Apple phased release can be enabled for the matching version through the official `appStoreVersionPhasedReleases` API. Existing phased configurations are preserved.
- Google release metadata accepts `name`, `in_app_update_priority` (0-5) and `country_targeting` for an in-progress production rollout. `rollout_fraction` must be greater than zero and strictly less than one for staged rollouts.
- Apple territory availability records are read through the official v2 endpoint. Pre-order writes still use the v1 update resource.
- Project-relative assets, Firebase configuration destinations and build paths reject absolute paths, traversal and symlinks outside the YAML project directory.
- The package uses the maintained setuptools PEP 517 backend, and both wheel and source distributions were produced offline in the development runtime.

### Still not available as a supported end-to-end capability

The App Store Connect App Privacy questionnaire, Google Play console-only declarations, tax and payment agreements, account verification, production release acceptance, unattended signing key rotation and full UI-testing of every device family cannot be represented as verified complete features. In particular, a generated `PrivacyInfo.xcprivacy` is not a substitute for the App Store privacy questionnaire. Developer accounts and native runners are needed for real acceptance tests. The official API may also reject a syntactically valid request based on account permissions or business policy.

## Additional API adapters in the expanded revision

- Apple TestFlight beta group synchronization, tester creation/linking and optional invitation sending. Updates preserve members not present in YAML.
- Apple device registration with UDID/platform checks and refusal to silently enable a disabled device. Existing provisioning profile generation continues to require explicit certification and identities.
- Apple subscription promotional offers, win-back offers, introductory offers by territory and subscription offer-code creation with explicitly configured price-point IDs. Existing immutable offers that differ from YAML fail rather than being overwritten.
- Google Play one-time purchase option offer upsert, activation, deactivation and cancellation through the current offer API.
- `app-publisher inspect` gives version/review status and TestFlight group details for Apple, track status for Google, and opt-in Apple price verification. The Google paid/free flag is deliberately marked unavailable through the public API.

These operations have mock-based tests and require credentials and a nonproduction app for authenticated acceptance. Pricing and offer-code submission may have additional business rules not detectable locally.

## Additional operations in v0.0.1

- Google Play one-time offer batch deletion with explicit `confirm_deletion` safeguards, remote inventory checks, and 100-item request batches.
- Google Play subscription offer deletion only when the remote state is `DRAFT`, with a verified package/product/plan/offer identity.
- Apple subscription offer-code generation with explicit opt-in and idempotent matching of generated batches.
- Optional `idb` navigation driver for iOS gestures, element actions, tvOS remote controls, and compatible foldable simulator hinge actions.
- Neither full coverage of every available store API nor authenticated end-to-end acceptance is established by this release. When a feature is not represented in the strict YAML schema or documentation, assume it is not implemented and do not infer support from the coverage percentage.

## v0.0.1 additional official endpoints

- Google `edits.apks.upload`, `edits.bundles.upload` and `edits.deobfuscationfiles.upload`, with exact artifact extension and release-version validation.
- Google `edits.listings.delete` through the separate `delete-listings` CLI action, with confirmation, remote inventory and guarded edit commit.
- Apple `customerReviews` and `customerReviewResponses` and Google `reviews.list` and `reviews.reply`, with application-scoped ID checks. Publishing public replies requires an explicit YAML opt-in per review.

These features have mocked tests. Production credentials, review permissions, account-specific behavior and signing remain unverified.

## Workflow and symbol boundaries

Declared workflow stages compose the implemented operations. The protected journal supports completed-stage resume and rejects changed inputs/artifacts. It does not make providers transactional or supply missing API adapters. `apply-plan` now requires `--apply` for writes. `wait` uses exact app/version/platform/build selection, and TestFlight distribution rejects processing, failed, invalid and expired builds.

Apple dSYM delivery verifies Firebase/archive identity and binary UUIDs before invoking Firebase's official uploader. Android symbols invoke declared Crashlytics Gradle tasks after Firebase/AAB identity checks. Real crash ingestion and native symbolication remain separately unverified. Commercial values and price-point identifiers come directly from each application YAML. The publisher does not choose subscription prices.

Typed YAML enum options accept any letter case and serialize canonical API values. Raw provider request objects still follow their official schemas. No claim of complete App Store Connect, Android Publisher or Firebase API coverage is made.

Google update masks are YAML lists. Only API requests encode them as comma-delimited field paths. Scalar strings are rejected. Apple subscription plan availability and explicit payment-plan price types have mocked coverage. This does not establish general app/IAP territory-management support.
