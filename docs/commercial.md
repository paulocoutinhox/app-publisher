# Commercial releases and product versions

This document describes the *implemented, unverified-live* interfaces. Use a non-production app with test products for initial authenticated verification.

## Apple application pricing

`apple.pricing.base_territory` must equal the remotely configured price schedule base territory. Each `apple.pricing.prices` entry contains the official `price_point_id` and optional ISO start/end dates. The publisher reads all current manual prices, compares them with the YAML, and submits an App Store price schedule replacement only when `confirm_price_changes: true` is declared. Do not confuse this with the separate free/paid declaration at `app.paid`, which is informational.

`apple.preorder_territory_availability` supports territory updates **only** where the current record is a pre-order. The CLI refuses requests for other territories. There is no general all-country overwrite mechanism.

## Apple in-app purchases

`apple.in_app_purchases` contains products with immutable product IDs and types. `localizations` accepts locale keys with `name` and `description`. Current App Store Connect IAP metadata uses versions: the publisher selects a draft version or creates a new one, then sends v2 localizations against that version. It does not edit an approved historical version.

`apple.subscription_groups` contains `reference_name`, optional localized group names, and renewable subscriptions. Each subscription provides `product_id`, `name`, `period`, optional metadata, `localizations`, and `prices`. Use official subscription price-point IDs from your Apple team. Subscription period is immutable. Price submissions require `apple.confirm_subscription_price_changes: true`.

Run `app-publisher review-products CONFIG --first-purchase-review-completed --apply` after the product metadata is complete and Apple has accepted the app's first product submitted with a binary. Versions must be uniquely in `PREPARE_FOR_SUBMISSION`, and review submissions must not already be active on that platform.

## Google Play subscriptions and offers

`google.subscriptions` and `google.one_time_products` are body-driven upserts with explicitly selected `update_mask`, `regions_version` and `data`. Google `subscription_offers` include `product_id`, `base_plan_id`, `offer_id`, `regions_version`, `update_mask`, `data` and optional `state`. Existing offers are updated only when masked fields differ. `google.base_plan_states` can activate or deactivate an existing plan after checking it exists within the remote subscription.

Commercial operations are not all part of the Google Play edit transaction, so partial success is possible. Re-read remote state and rerun the dry run after any failed write. Do not assume a network failure means a resource was not created.

## Apple signing artifacts

`apple.signing.certificates` allows downloading a previously issued Apple signing certificate by resource ID. `apple.signing.profiles` can reuse an existing profile when name, type, Bundle ID, certificate IDs and device IDs match. With `create_if_missing: true`, the CLI can create a profile using the official endpoint. File writes are limited to the YAML folder, refuse changed existing files, and never store the signing private key.

`app-publisher signing CONFIG` displays pending changes. Add `--apply` for downloads and explicitly allowed profile creation. The signing module also supports opt-in encrypted private-key generation, CSR creation and certificate issuance. macOS Keychain integration and unattended certificate rotation remain outside the automatic workflow. These processes are sensitive and should be controlled in your signing infrastructure.

## Public API limitations

The CLI cannot complete tax forms, bank agreements, private Apple privacy questionnaires or every Google Play content declaration through official REST APIs. Apple SDK signing credentials and Google Play service account permissions are prerequisites. All requests and response structures must be verified against the actual team accounts and newest store APIs before production use.

References: [Apple App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi/), [Apple version-based product metadata](https://developer.apple.com/documentation/appstoreconnectapi/migrating-in-app-purchase-metadata-to-v2), [Google Play Developer API](https://developers.google.com/android-publisher/api-ref/rest).

## Subscription offers and one-time purchase offers

Apple subscription `introductory_offers` are identified by territory and start date; `offer_codes` are identified by name. Promotional and win-back offers have their own official resources. YAML must declare Apple price-point IDs, durations, modes and relevant eligibility settings. The CLI checks existing offers before creating resources. It refuses to silently modify immutable offer details. Generated one-time redemption-code batches are not produced by this module.

Google `one_time_offers` declares a product ID, purchase option ID, offer ID, regions version, explicit update mask and full API body. The CLI uses batch update operations and supports an explicit desired state (`DRAFT`, `ACTIVE`, `INACTIVE`, `CANCELLED`). It does not infer field masks or purchase-option configuration.

`app-publisher inspect` reads review submissions, App Store versions, TestFlight groups and Play release tracks. `apple.verify_paid` enables a strict base-territory Apple price check. When a price schedule has no unique effective manually set price the check fails rather than assuming a free app. The Google Play Publishing API does not return the app-level paid/free flag.

Declare update masks as YAML lists, for example `update_mask: [listings, basePlans]`. The publisher joins the paths with commas only at the Google API boundary. Scalar comma-delimited masks are rejected.

## Apple subscription plan availability

Subscriptions may declare `availability` entries before price schedules are applied:

```yaml
availability:
  - plan_type: upfront
    territories: [USA]
    available_in_new_territories: false
    confirm_territory_changes: false
prices:
  - price_point_id: YOUR_OFFICIAL_PRICE_POINT_ID
    plan_type: upfront
    preserve_current_price: true
```

The publisher uses current `subscriptionPlanAvailabilities` resources. `UPFRONT` and `MONTHLY` are Apple payment-plan types, separate from the subscription billing period. An annual subscription paid annually uses `UPFRONT`. Values accept any letter case. Unknown territories and duplicate plan declarations are errors. Updating existing territory availability requires explicit confirmation. Unspecified subscription availability remains unchanged.

Price identity includes the official point, start date and payment-plan type. The publisher does not invent product prices, discounts or territory lists. These come from the application YAML.

## Product review screenshots

Apple subscriptions and in-app purchases accept a `review_screenshot` asset independently from public storefront screenshots:

```yaml
review_screenshot:
  path: assets/review/premium-features.png
  confirm_replacement: false
  timeout_seconds: 300
```

The file must be a valid PNG or JPEG inside the project directory. The publisher reserves the appropriate Apple resource, transfers its upload parts, commits the required checksum and waits for `COMPLETE`. Failed processing, unknown states, mismatched checksums and timeouts stop publication. An already completed image with the same checksum is unchanged. An interrupted matching upload can resume. Replacing an existing different image requires `confirm_replacement: true`.

The image must clearly show the purchased service and meet Apple's accepted screenshot specifications. It is provided for App Review and is separate from storefront marketing images. Uploading it does not submit the product or app for review. Review assets participate in publication-plan and workflow artifact hashes.

References: [Apple purchase review information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information), [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications).

## App Review attachments

Version-level documents and videos belong under `apple.review.attachments`, separately from subscription or IAP screenshots:

```yaml
apple:
  review:
    attachments:
      - path: assets/review/feature-guide.pdf
        confirm_replacement: false
        timeout_seconds: 300
```

Attachments must be nonempty files inside the project directory, with unique filenames. The publisher creates review details when absent, preserves undeclared contact/account fields and keeps unrelated remote attachments. It uses content checksums in uploaded filenames so a pending upload can only resume for matching content. Replacing a changed attachment requires explicit confirmation. Duplicate remote matches stop synchronization. Apple performs the final file-format and processing checks.

These uploads do not submit the version for review. Their file hashes are included in publication plans and workflow journals. Missing local files are rejected before metadata writes.

References: [Apple review attachments](https://developer.apple.com/documentation/appstoreconnectapi/app-store-review-attachments), [Apple attachment creation](https://developer.apple.com/documentation/appstoreconnectapi/post-v1-appstorereviewattachments).
