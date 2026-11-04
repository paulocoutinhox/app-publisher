# Extended official store APIs

The CLI implements the following declarative API paths from the expanded revision. All writes are opt-in and require `--apply`.

## Apple beta testing

`apple.beta_groups` synchronizes groups by their unique names. It can create internal or external groups, configure external public links and limits, register new beta testers, link existing testers to groups and issue optional invitations. Group membership is additive: undeclared testers are not removed. Build distribution uses already-existing group resource IDs under `apple.versions[].beta.group_ids`.

## Apple signing devices

`apple.signing.devices` registers devices by UDID using the public devices API and verifies existing platform and enabled state. Device registration is separate from profile regeneration, which must be explicitly declared. It does not bypass Apple account device limits or manually managed signing policy.

## Apple subscription offers

Subscription YAML supports `introductory_offers`, `promotional_offers`, `win_back_offers` and `offer_codes`. Introductory offers are keyed by territory and start date. Other offers are keyed by names or codes. Create requests include explicit official subscription price point resource IDs and never invent prices. Existing immutable offers are not overwritten. API validation still depends on Apple account capabilities and business policy.

## Google Play offers

`google.one_time_offers` uses the one-time product offers API to create or update masked fields and to activate, deactivate or cancel an offer. Subscription offers are managed separately by `google.subscription_offers`. Both modes require explicit regions-version and field-mask values from the current API contracts.

## Read-only diagnostics

`app-publisher inspect` reads the remote App Store versions, review submissions, TestFlight groups and Google release tracks. On Apple, set `apple.verify_paid` to explicitly verify a single effective manual base-territory price point. On Google, paid/free state cannot be verified through the public Publishing API.

No operation above requires Fastlane. All were verified with mocked HTTP provider responses and local unit tests; authenticated live acceptance remains a separate step.

References: [App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi/) and [Google Play Developer API](https://developers.google.com/android-publisher/api-ref/rest/).

## October 2026 expansion: Apple code batches

An `apple.subscription_groups[].subscriptions[].offer_codes[]` entry may declare `custom_code_batches` or `one_time_code_batches`. The matching offer-code parent is resolved by its configured name in its parent subscription. When the remote offer exists, its identifier is used for the official `subscriptionOfferCodeCustomCodes` and `subscriptionOfferCodeOneTimeUseCodes` endpoints. When the parent offer does not exist, App Publisher creates it before attempting code generation.

A custom-code batch includes `custom_code`, `number_of_codes`, optional `expiration_date`, and `confirm_creation`. A one-time-use batch includes `number_of_codes` (500–25,000), mandatory `expiration_date`, optional `environment`, and `confirm_creation`. Both are skipped when matching existing batch attributes are found. The tool never auto-deactivates existing codes. Creating a code batch is an irreversible business operation and requires `confirm_creation: true` before applying a new batch.

## October 2026 expansion: Google purchase options

`google.purchase_option_states` manages ACTIVE/INACTIVE state through `monetization.onetimeproducts.purchaseOptions.batchUpdateStates`, validating package, product and purchase-option IDs before changes. `google.purchase_option_deletions` is handled only by the separate `app-publisher delete-purchase-options CONFIG --apply` command, never by `sync`. Deletion requires `confirm_deletion: true` on each entry and defaults to `force: false`, preserving offers unless explicitly authorized.

## October 2026 expansion: idb screenshot driver

Set `driver: idb` on an iOS or tvOS screenshot plan. On iOS, `tap`, `swipe`, `text`, `tap_element`, `wait_element`, `hinge`, `rotate`, `shake`, and `pinch` are available in addition to app launch and navigation. tvOS accepts `remote` with `up`, `down`, `left`, `right`, `select`, and `menu`. Hinge actions require a simulator runtime compatible with iPhone Duo. Device and simulator availability, and idb companion permissions, must be tested on a macOS host. `doctor-full` checks the idb executable when configured. Other Apple platforms retain the native deep-link-driven capture plan and do not claim unavailable gesture support.

Official references: [idb commands](https://fbidb.io/idb/commands/), [Google purchase-option states](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.onetimeproducts.purchaseOptions/batchUpdateStates), [Apple subscription offer codes](https://developer.apple.com/documentation/appstoreconnectapi/subscription-offer-codes).

## Explicit Google Play offer deletion

Use `google.one_time_offer_deletions` and `google.subscription_offer_deletions`, then run `app-publisher delete-offers CONFIG` to preview and `app-publisher delete-offers CONFIG --apply` to commit. Every entry requires `confirm_deletion: true`. The tool fetches existing remote resources first and skips already-missing offers. One-time purchase offers use the official `offers:batchDelete` endpoint in batches of at most 100. Subscription offers use `DELETE` and are refused unless Google confirms their remote state is `DRAFT`. These operations never execute as a side effect of `sync` or `release`. A configuration cannot simultaneously update and delete the same offer.

References: [One-time offer batch deletion](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.onetimeproducts.purchaseOptions.offers/batchDelete) and [Draft subscription offer deletion](https://developers.google.com/android-publisher/api-ref/rest/v3/monetization.subscriptions.basePlans.offers/delete).
