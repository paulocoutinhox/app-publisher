from pathlib import Path
from typing import Literal

from app_publisher.core.api_client import APIClient
from app_publisher.core.auth import apple_token, google_token
from app_publisher.core.privacy_manifest_writer import PrivacyManifestWriter
from app_publisher.core.validation import validate_project
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.project_config import ProjectConfig
from app_publisher.providers.apple_accessibility import AppleAccessibility
from app_publisher.providers.apple_beta_groups import AppleBetaGroups
from app_publisher.providers.apple_beta_manager import AppleBetaManager
from app_publisher.providers.apple_build_manager import AppleBuildManager
from app_publisher.providers.apple_certificate_issuer import AppleCertificateIssuer
from app_publisher.providers.apple_commercial import AppleCommercial
from app_publisher.providers.apple_devices import AppleDevices
from app_publisher.providers.apple_in_app_purchase_manager import AppleInAppPurchaseManager
from app_publisher.providers.apple_information import AppleInformation
from app_publisher.providers.apple_launch import AppleLaunch
from app_publisher.providers.apple_price_audit import ApplePriceAudit
from app_publisher.providers.apple_product_review import AppleProductReview
from app_publisher.providers.apple_publisher import ApplePublisher
from app_publisher.providers.apple_review_manager import AppleReviewManager
from app_publisher.providers.apple_signing_manager import AppleSigningManager
from app_publisher.providers.apple_store_reviews import AppleStoreReviews
from app_publisher.providers.apple_subscriptions import AppleSubscriptions
from app_publisher.providers.crashlytics_publisher import CrashlyticsPublisher
from app_publisher.providers.firebase_publisher import FirebasePublisher
from app_publisher.providers.google_monetization import GoogleMonetization
from app_publisher.providers.google_one_time_offers import GoogleOneTimeOffers
from app_publisher.providers.google_publisher import GooglePublisher
from app_publisher.providers.google_purchase_options import GooglePurchaseOptions
from app_publisher.providers.google_store_reviews import GoogleStoreReviews
from app_publisher.providers.google_subscription_offers import GoogleSubscriptionOffers
from app_publisher.providers.google_testers import GoogleTesters
from app_publisher.providers.store_availability import StoreAvailability
from app_publisher.providers.store_inspection import StoreInspection
from app_publisher.screenshots.screenshot_planner import ScreenshotPlanner
from app_publisher.screenshots.screenshot_renderer import ScreenshotRenderer
from app_publisher.toolchain.build_runner import BuildRunner

APPLE_SCOPE = "https://api.appstoreconnect.apple.com/v1"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
FIREBASE_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class PublicationEngine:
    def __init__(self, project: ProjectConfig, file: Path):
        self.project = project
        self.file = file
        self.directory = file.resolve().parent

    def validate(self, *, local_files: Literal["all", "store", "none"] = "all") -> None:
        errors = validate_project(self.project, self.file, local_files=local_files)
        if errors:
            raise ConfigurationError("Validation failed:\n" + "\n".join(f"- {error}" for error in errors))

    def apple(self) -> ApplePublisher:
        config = self.project.apple
        if config is None:
            raise ConfigurationError("Apple is not configured")
        api = APIClient(
            APPLE_SCOPE,
            lambda: apple_token(config.key_id_env, config.issuer_id_env, config.private_key_path_env),
        )
        return ApplePublisher(api, config)

    def google(self) -> GooglePublisher:
        config = self.project.google
        if config is None:
            raise ConfigurationError("Google Play is not configured")
        api = APIClient(
            "https://androidpublisher.googleapis.com/androidpublisher/v3",
            lambda: google_token([GOOGLE_SCOPE]),
        )
        return GooglePublisher(api, config)

    def firebase(self) -> FirebasePublisher:
        config = self.project.firebase
        if config is None:
            raise ConfigurationError("Firebase is not configured")
        api = APIClient(
            "https://firebase.googleapis.com/v1beta1",
            lambda: google_token([FIREBASE_SCOPE]),
        )
        cloud = APIClient(
            "https://cloudresourcemanager.googleapis.com/v1",
            lambda: google_token([FIREBASE_SCOPE]),
        )
        return FirebasePublisher(api, cloud, config)

    def synchronize(self, *, apply: bool, provider: str = "all") -> list[str]:
        self.validate(local_files="store")
        if apply and self.project.apple is not None and provider in {"all", "apple"}:
            pricing = self.project.apple.pricing
            if pricing and not pricing.confirm_price_changes:
                raise UnsafeOperationError(
                    "Apple app price modifications require confirm_price_changes: true"
                )
            subscription_prices = any(
                item.prices
                for group in self.project.apple.subscription_groups
                for item in group.subscriptions
            )
            if subscription_prices and not self.project.apple.confirm_subscription_price_changes:
                raise UnsafeOperationError(
                    "Apple subscription price changes require confirm_subscription_price_changes: true"
                )
        changes: list[str] = []
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                changes.extend(handler.synchronize(self.project, self.directory, apply=apply))
                if self.project.apple.accessibility:
                    changes.extend(
                        AppleAccessibility(handler.api, self.project.apple.app_id).synchronize(
                            self.project.apple.accessibility, apply=apply
                        )
                    )
                if self.project.apple.categories or self.project.apple.age_rating:
                    changes.extend(
                        AppleInformation(handler.api, self.project.apple.app_id).synchronize(
                            self.project.apple.categories, self.project.apple.age_rating, apply=apply
                        )
                    )
                if self.project.apple.in_app_purchases:
                    changes.extend(
                        AppleInAppPurchaseManager(handler.api, self.project.apple.app_id).synchronize(
                            self.project.apple.in_app_purchases, apply=apply, directory=self.directory
                        )
                    )
                if self.project.apple.subscription_groups:
                    changes.extend(
                        AppleSubscriptions(handler.api, self.project.apple.app_id).synchronize(
                            self.project.apple.subscription_groups,
                            apply=apply,
                            allow_price_changes=self.project.apple.confirm_subscription_price_changes,
                            directory=self.directory,
                        )
                    )
                commerce = AppleCommercial(handler.api, self.project.apple.app_id)
                if self.project.apple.verify_base_territory:
                    changes.extend(commerce.verify_base_territory(self.project.apple.verify_base_territory))
                if self.project.apple.pricing:
                    changes.extend(commerce.synchronize_pricing(self.project.apple.pricing, apply=apply))
                if self.project.apple.preorder_territory_availability:
                    changes.extend(
                        commerce.synchronize_territories(
                            self.project.apple.preorder_territory_availability, apply=apply
                        )
                    )
                if self.project.apple.review:
                    existing = handler.versions()
                    for version in self.project.apple.versions:
                        match = next(
                            (
                                item
                                for item in existing
                                if item["attributes"]["platform"] == version.platform
                                and item["attributes"]["versionString"] == version.version
                            ),
                            None,
                        )
                        if match:
                            changes.extend(
                                AppleReviewManager(
                                    handler.api, self.project.apple.app_id
                                ).synchronize_details(
                                    match["id"],
                                    self.project.apple.review,
                                    apply=apply,
                                    directory=self.directory,
                                )
                            )
            finally:
                handler.api.close()
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            try:
                changes.extend(handler.synchronize(self.project, self.directory, apply=apply))
                if self.project.google.subscriptions or self.project.google.one_time_products:
                    changes.extend(
                        GoogleMonetization(handler.api, self.project.google.package_name).synchronize(
                            self.project.google.subscriptions,
                            self.project.google.one_time_products,
                            apply=apply,
                        )
                    )
                if self.project.google.subscription_offers or self.project.google.base_plan_states:
                    changes.extend(
                        GoogleSubscriptionOffers(handler.api, self.project.google.package_name).synchronize(
                            self.project.google.subscription_offers,
                            self.project.google.base_plan_states,
                            apply=apply,
                        )
                    )
                if self.project.google.one_time_offers:
                    changes.extend(
                        GoogleOneTimeOffers(handler.api, self.project.google.package_name).synchronize(
                            self.project.google.one_time_offers, apply=apply
                        )
                    )
                if self.project.google.purchase_option_states:
                    changes.extend(
                        GooglePurchaseOptions(handler.api, self.project.google.package_name).synchronize(
                            self.project.google.purchase_option_states, apply=apply
                        )
                    )
            finally:
                handler.api.close()
        if self.project.firebase is not None and provider in {"all", "firebase"}:
            handler = self.firebase()
            try:
                changes.extend(handler.synchronize(self.directory, apply=apply))
            finally:
                handler.api.close()
                handler.cloud.close()
        return changes

    def delete_listings(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.google is None:
            raise ConfigurationError("Google Play is not configured")
        handler = self.google()
        try:
            return handler.delete_listings(self.project.google.listing_deletions, apply=apply)
        finally:
            handler.api.close()

    def reply_reviews(self, *, apply: bool, provider: str = "all") -> list[str]:
        self.validate(local_files="none")
        changes: list[str] = []
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                handler.identify()
                changes.extend(
                    AppleStoreReviews(handler.api, self.project.apple.app_id).synchronize(
                        self.project.apple.review_replies, apply=apply
                    )
                )
            finally:
                handler.api.close()
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            try:
                changes.extend(
                    GoogleStoreReviews(handler.api, self.project.google.package_name).synchronize(
                        self.project.google.review_replies, apply=apply
                    )
                )
            finally:
                handler.api.close()
        return changes

    def list_reviews(self, provider: str = "all") -> dict[str, object]:
        self.validate(local_files="none")
        reviews: dict[str, object] = {}
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                handler.identify()
                reviews["apple"] = AppleStoreReviews(handler.api, self.project.apple.app_id).list_reviews()
            finally:
                handler.api.close()
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            try:
                reviews["google"] = GoogleStoreReviews(
                    handler.api, self.project.google.package_name
                ).list_reviews()
            finally:
                handler.api.close()
        return reviews

    def testers(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.google is None:
            raise ConfigurationError("Google Play is not configured")
        handler = self.google()
        try:
            return GoogleTesters(handler.api, handler.config.package_name).synchronize(
                self.project.google.tester_groups, apply=apply
            )
        finally:
            handler.api.close()

    def delete_purchase_options(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.google is None:
            raise ConfigurationError("Google Play is not configured")
        handler = self.google()
        try:
            return GooglePurchaseOptions(handler.api, self.project.google.package_name).delete(
                self.project.google.purchase_option_deletions, apply=apply
            )
        finally:
            handler.api.close()

    def delete_offers(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.google is None:
            raise ConfigurationError("Google Play is not configured")
        handler = self.google()
        try:
            changes = GoogleOneTimeOffers(handler.api, self.project.google.package_name).delete(
                self.project.google.one_time_offer_deletions, apply=apply
            )
            changes.extend(
                GoogleSubscriptionOffers(handler.api, self.project.google.package_name).delete(
                    self.project.google.subscription_offer_deletions, apply=apply
                )
            )
            return changes
        finally:
            handler.api.close()

    def build(self, *, apply: bool, provider: str = "all") -> list[str]:
        self.validate(local_files="none")
        changes: list[str] = []
        runner = BuildRunner()
        if self.project.apple and provider in {"all", "apple"}:
            for version in self.project.apple.versions:
                if version.build is not None:
                    changes.append(f"Apple {version.platform}: compile and export {version.build.scheme}")
                    if apply:
                        runner.apple(version.build, self.directory)
        if (
            self.project.google
            and provider in {"all", "google"}
            and self.project.google.release
            and self.project.google.release.build
        ):
            build = self.project.google.release.build
            changes.append(f"Google: build {build.task}")
            if apply:
                runner.android(build, self.directory)
        return changes

    def wait(self, *, timeout: int = 900) -> list[str]:
        if self.project.apple is None:
            raise ConfigurationError("Apple is not configured")

        handler = self.apple()

        try:
            handler.identify()
            manager = AppleBuildManager(handler.api, self.project.apple.app_id)
            changes = []

            for version in self.project.apple.versions:
                build = manager.wait(version, timeout=timeout)
                changes.append(
                    f"Apple {version.platform}: build {version.build_number} is VALID ({build['id']})"
                )

            return changes
        finally:
            handler.api.close()

    def symbols(self, *, apply: bool, provider: str = "all") -> list[str]:
        if self.project.firebase is None:
            raise ConfigurationError("Firebase is not configured")

        return CrashlyticsPublisher().upload(
            self.project.firebase, self.directory, apply=apply, provider=provider
        )

    def screenshots(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        changes: list[str] = []
        runner = ScreenshotPlanner()
        for plan in self.project.publication.screenshot_plans:
            changes.extend(
                f"{plan.platform} {plan.device}: capture {scene.name} -> {scene.output}"
                for scene in plan.scenes
            )
            if apply:
                runner.run(plan, self.directory)
        return changes

    def render_screenshots(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        renderer = ScreenshotRenderer()
        changes: list[str] = []
        for design in self.project.publication.screenshot_designs:
            changes.append(f"Screenshot artwork: {design.source} -> {design.output}")
            if apply:
                renderer.render(design, self.directory)
        return changes

    def review(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None:
            raise ConfigurationError("Apple review requires an Apple app")
        handler = self.apple()
        changes: list[str] = []
        try:
            handler.identify()
            existing = handler.versions()
            selected: list[tuple[str, str]] = []
            for version in self.project.apple.versions:
                match = next(
                    (
                        item
                        for item in existing
                        if item["attributes"]["platform"] == version.platform
                        and item["attributes"]["versionString"] == version.version
                    ),
                    None,
                )
                if match is None:
                    raise ConfigurationError(
                        f"Apple {version.platform} version {version.version} does not exist"
                    )
                if match["attributes"].get("appVersionState") != "PREPARE_FOR_SUBMISSION":
                    raise ConfigurationError(
                        f"Apple {version.platform} version {version.version} is not in PREPARE_FOR_SUBMISSION"
                    )
                selected.append((match["id"], version.platform))
            changes.extend(
                AppleReviewManager(handler.api, self.project.apple.app_id).submit(selected, apply=apply)
            )
        finally:
            handler.api.close()
        return changes

    def review_products(
        self, *, apply: bool, platform: str, first_purchase_review_completed: bool
    ) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None:
            raise ConfigurationError("Apple product review requires an Apple app")
        handler = self.apple()
        try:
            handler.identify()
            return AppleProductReview(handler.api, self.project.apple).submit(
                platform, apply=apply, first_purchase_review_completed=first_purchase_review_completed
            )
        finally:
            handler.api.close()

    def signing(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None or self.project.apple.signing is None:
            raise ConfigurationError("Apple signing configuration is required")
        handler = self.apple()
        try:
            handler.identify()
            changes = AppleCertificateIssuer(handler.api).synchronize(
                self.project.apple.signing.issuance, self.directory, apply=apply
            )
            changes.extend(
                AppleDevices(handler.api).synchronize(self.project.apple.signing.devices, apply=apply)
            )
            changes.extend(
                AppleSigningManager(handler.api, handler.config.bundle_id).synchronize(
                    self.project.apple.signing, self.directory, apply=apply
                )
            )
            return changes
        finally:
            handler.api.close()

    def beta(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None:
            raise ConfigurationError("Apple TestFlight requires an Apple app")
        handler = self.apple()
        try:
            handler.identify()
            changes: list[str] = []
            changes.extend(
                AppleBetaGroups(handler.api, self.project.apple.app_id).synchronize(
                    self.project.apple.beta_groups, apply=apply
                )
            )
            manager = AppleBetaManager(handler.api, self.project.apple.app_id)
            for version in self.project.apple.versions:
                changes.extend(manager.distribute(version, apply=apply))
            return changes
        finally:
            handler.api.close()

    def release(self, *, apply: bool, provider: str) -> list[str]:
        self.validate()
        changes: list[str] = []
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            locales = {
                locale: config.google.release_notes or config.common.release_notes
                for locale, config in self.project.locales.items()
                if config.google and (config.google.release_notes or config.common.release_notes)
            }
            try:
                changes.extend(
                    handler.publish_release(
                        self.directory,
                        locales,
                        apply=apply,
                        submit_for_review=self.project.publication.submit_for_review,
                    )
                )
            finally:
                handler.api.close()
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                handler.identify()
                for version in self.project.apple.versions:
                    if version.artifact is None:
                        continue
                    changes.append(f"Apple {version.platform}: upload {version.artifact}")
                    if apply:
                        handler.upload_build(version, self.directory)
            finally:
                handler.api.close()
        return changes

    def launch(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None:
            raise ConfigurationError("Apple launch requires an Apple app")
        handler = self.apple()
        try:
            handler.identify()
            remote = handler.versions()
            manager = AppleLaunch(handler.api)
            changes: list[str] = []
            for version in self.project.apple.versions:
                if not version.manual_release and not version.phased_release:
                    continue
                matches = [
                    item
                    for item in remote
                    if item["attributes"]["platform"] == version.platform
                    and item["attributes"]["versionString"] == version.version
                ]
                if len(matches) != 1:
                    raise UnsafeOperationError(
                        f"Apple {version.platform} {version.version}: expected exactly one matching remote version"
                    )
                changes.extend(manager.launch(version, matches[0], apply=apply))
            return changes
        finally:
            handler.api.close()

    def privacy(self, *, apply: bool) -> list[str]:
        self.validate(local_files="none")
        if self.project.apple is None or self.project.apple.privacy_manifest is None:
            raise ConfigurationError("Apple privacy_manifest is not configured")
        return PrivacyManifestWriter().synchronize(
            self.project.apple.privacy_manifest, self.directory, apply=apply
        )

    def availability(self, provider: str = "all") -> list[str]:
        self.validate(local_files="none")
        changes: list[str] = []
        if (
            self.project.apple is not None
            and provider in {"all", "apple"}
            and self.project.apple.territory_expectations
        ):
            handler = self.apple()
            try:
                handler.identify()
                changes.extend(
                    StoreAvailability(handler.api).apple(
                        self.project.apple.app_id, self.project.apple.territory_expectations
                    )
                )
            finally:
                handler.api.close()
        if (
            self.project.google is not None
            and provider in {"all", "google"}
            and self.project.google.country_expectations
        ):
            handler = self.google()
            try:
                changes.extend(
                    StoreAvailability(handler.api).google(
                        self.project.google.package_name, self.project.google.country_expectations
                    )
                )
            finally:
                handler.api.close()
        return changes

    def inspect(self, provider: str = "all") -> dict[str, object]:
        self.validate(local_files="none")
        report: dict[str, object] = {}
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                handler.identify()
                details = StoreInspection(handler.api, self.project.apple.app_id).apple()
                if self.project.apple.verify_paid is not None:
                    details["pricing"] = ApplePriceAudit(handler.api, self.project.apple.app_id).verify(
                        self.project.apple.verify_paid
                    )
                report["apple"] = details
            finally:
                handler.api.close()
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            try:
                edit = handler.start_edit()
                try:
                    tracks = handler.api.request("GET", f"{handler.edit_path(edit)}/tracks").get("tracks", [])
                    report["google"] = StoreInspection(handler.api, self.project.google.package_name).google(
                        tracks
                    )
                finally:
                    handler.api.request("DELETE", f"applications/{handler.config.package_name}/edits/{edit}")
            finally:
                handler.api.close()
        return report

    def status(self, provider: str) -> dict[str, object]:
        report: dict[str, object] = {}
        if self.project.apple is not None and provider in {"all", "apple"}:
            handler = self.apple()
            try:
                handler.identify()
                report["apple"] = [
                    {
                        "platform": item["attributes"]["platform"],
                        "version": item["attributes"]["versionString"],
                        "state": item["attributes"].get("appVersionState"),
                    }
                    for item in handler.versions()
                ]
            finally:
                handler.api.close()
        if self.project.google is not None and provider in {"all", "google"}:
            handler = self.google()
            try:
                edit = handler.start_edit()
                try:
                    report["google"] = handler.api.request("GET", f"{handler.edit_path(edit)}/tracks")
                finally:
                    handler.api.request("DELETE", f"applications/{handler.config.package_name}/edits/{edit}")
            finally:
                handler.api.close()
        return report
