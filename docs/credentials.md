# Publisher credentials

Keep credential files outside repositories. YAML stores environment variable names, never passwords or private-key contents. A developer certificate and a store API credential serve different purposes.

## App Store Connect

1. Open App Store Connect, Users and Access, Integrations, App Store Connect API.
2. The Account Holder may need to request API access. Create a team API key with the App Manager role for app publication. Provisioning operations can require a different authorized role.
3. Download the `.p8` file immediately. Apple permits only one download. Keep the Key ID and Issuer ID with the local credential configuration.
4. Set `APP_STORE_KEY_ID`, `APP_STORE_ISSUER_ID` and `APP_STORE_KEY_PATH`. A RevenueCat subscription key or finance-only key is not the appropriate publisher credential.
5. Obtain the numeric Apple app ID from the app's App Information page. It differs from the bundle identifier.

The API key authorizes store operations. Building a signed IPA also requires an Apple Distribution certificate with its private key, the correct Team ID and an App Store provisioning profile compatible with every entitlement. Automatic signing can obtain profiles when authorized. Push-enabled apps need a push-enabled explicit App ID and production APNs entitlement for distribution.

Sources: [API access](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api/), [creating keys](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api).

## Google Play

1. Create or select a Google Cloud project and enable Google Play Android Developer API.
2. Create a service account in IAM and Admin, Service Accounts.
3. In Play Console, Users and permissions, invite its service-account email and grant access to the intended application. Grant the required testing release and store listing permissions. Cloud IAM roles alone do not grant Play Console access.
4. Create a JSON service-account key when local key-based authentication is required. Download it outside the source repository and set `GOOGLE_APPLICATION_CREDENTIALS` to its path.
5. Verify access to the exact package name before applying a release. Workload identity is also supported through Google ADC without a JSON private key.

Sources: [Android Publisher setup](https://developers.google.com/android-publisher/getting_started), [service-account key management](https://docs.cloud.google.com/iam/docs/keys-create-delete).

## Android upload signing

Use the upload keystore already registered for an existing application. Google Play App Signing's app-signing key and your local upload key are separate roles. Do not generate or substitute a key for an app with an existing registered upload certificate.

For a new application without an upload key, Android Studio can create one through Build, Generate Signed Bundle / APK, Android App Bundle, Create new. Back up the keystore securely and keep its alias, store password and key password outside version control. Pass signing values to the app's Gradle signing configuration through environment variables or an ignored local file.

Source: [Android app signing](https://developer.android.com/studio/publish/app-signing).
