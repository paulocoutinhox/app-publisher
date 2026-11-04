# Scope closure for the original publishing checklist

The project synchronizes an **explicit supported publishing surface**. It does not implement every endpoint in the full Apple, Android Publisher, or Firebase product ecosystems. That would include unrelated capabilities such as reports, user management, integrity, financial data and analytics. All entries marked “Implemented with mocks” need authenticated acceptance tests before production rollout.

| Checklist item | Implementation | Availability |
| --- | --- | --- |
| App identity and version discovery | `providers/apple_publisher.py`, `providers/google_publisher.py` | Implemented with mocks |
| Apple IPA/PKG and Google AAB/APK upload | `providers/apple_publisher.py`, `providers/google_publisher.py` | Implemented with mocks |
| Localized names, descriptions, subtitles, promotion, keywords, release notes, URLs | `models/`, `core/validation.py`, Apple and Google publishing adapters | Implemented with mocks |
| iPhone/iPad/iPhone Duo/Mac/TV/Watch/Vision screenshot handling | `providers/apple_asset_library.py`, `screenshots/`, dynamic Apple placement reference | Implemented where Apple placement types expose an appropriate slot |
| Apple App Preview videos | `providers/apple_app_previews.py` | Implemented with mocks |
| Google screenshots, icon, feature graphic, TV banner and video URL | `models/`, `providers/google_publisher.py` | Implemented with mocks for public image types |
| Apple categories, age rating, accessibility, review details and test account | `providers/apple_information.py`, `apple_accessibility.py`, `apple_review.py` | Implemented for exposed public fields |
| Apple review submission, scheduled/manual/phased release, review status | `providers/apple_review_manager.py`, `apple_launch.py`, `apple.py`, `store_inspection.py` | Implemented with mocks |
| Apple price point schedules and availability | `providers/apple_commercial.py`, `store_availability.py` | Editable fields and pre-order territory changes only |
| Apple IAP, subscriptions, groups, localizations, pricing, offers and codes | `providers/apple_in_app_purchase_manager.py`, `apple_subscriptions.py`, `apple_product_localizations.py`, `apple_subscription_*`, `apple_offer_code_batches.py`, `apple_product_review.py` | Configured public API operations implemented with mocks |
| TestFlight groups, invitations and builds | `providers/apple_beta_manager.py`, `apple_beta_groups.py` | Implemented with mocks |
| App Privacy and privacy policy | Apple privacy-policy URLs + `PrivacyInfo.xcprivacy` generator | Questionnaire not fully exposed by public REST API |
| Google testing tracks, groups, staged rollout and release status | `providers/google_publisher.py`, `google_testers.py`, `store_inspection.py` | Implemented with mocks, individual email lists are Console-only |
| Google Data Safety CSV | `providers/google_publisher.py` | Implemented via public endpoint |
| Google subscriptions, in-app products, plans, offers and purchase options | `providers/google_monetization.py`, `google_subscription_offers.py`, `google_one_time_offers.py`, `google_purchase_options.py` | Declared public API operations implemented with mocks |
| Google category, content, advertising, age and intended-audience questionnaires | None | Console-only for settings lacking a public publisher endpoint |
| Google paid/free app conversion | None | Console-only, irreversible constraints apply |
| Firebase project, Apple/Android app registrations, config files and Android SHA fingerprints | `providers/firebase_publisher.py`, `firebase_certificates.py` | Implemented with mocks |
| Remote change and failure reporting | `core/sync_plan.py`, `core/diagnostics.py`, `providers/store_inspection.py` | Implemented with documented race/transaction limits |

## Release verification and limitations

`pytest --cov=app_publisher --cov-branch` checks all **implemented code paths**, not the completeness of provider API schemas. Since the APIs evolve and remote acceptance is not tested, no percentage of code coverage proves 100% of store functionality.

Operations unsupported by the public APIs do not become safe just because a browser or private endpoint could technically automate a form. The project intentionally does not use private APIs, scraping or undocumented UI mutations for Console-only settings.

The publication-plan hash is a local review mechanism and checks a remote diff. It is not cryptographically signed and it cannot lock external provider state. Avoid using it as an authorization token. Remote assets or settings may change between plan generation and writes, and some APIs do not expose immutable revisions.

## Sources

- [App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi/)
- [Google Play Android Publisher API](https://developers.google.com/android-publisher/api-ref/rest)
- [Google release-note limit](https://support.google.com/googleplay/android-developer/answer/9859348)
- [Google tester API limitations](https://developers.google.com/android-publisher/api-ref/rest/v3/edits.testers)
- [Apple availability and pre-order behavior](https://developer.apple.com/documentation/appstoreconnectapi/get-v2-appavailabilities-_id_)
- [Firebase Management REST API](https://firebase.google.com/docs/projects/api/reference/rest)
