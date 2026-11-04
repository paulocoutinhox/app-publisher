from pydantic import Field, model_validator

from app_publisher.models.apple_accessibility_declaration import AppleAccessibilityDeclaration
from app_publisher.models.apple_beta_group import AppleBetaGroup
from app_publisher.models.apple_in_app_purchase import AppleInAppPurchase
from app_publisher.models.apple_pricing import ApplePricing
from app_publisher.models.apple_privacy_manifest import ApplePrivacyManifest
from app_publisher.models.apple_review import AppleReview
from app_publisher.models.apple_signing_config import AppleSigningConfig
from app_publisher.models.apple_subscription_group import AppleSubscriptionGroup
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.store_review_reply import StoreReviewReply
from app_publisher.models.strict_model import StrictModel


class AppleConfig(StrictModel):
    app_id: str = Field(pattern=r"^[0-9]+$")
    bundle_id: str = Field(min_length=3)
    key_id_env: str = "APP_STORE_KEY_ID"
    issuer_id_env: str = "APP_STORE_ISSUER_ID"
    private_key_path_env: str = "APP_STORE_KEY_PATH"
    versions: list[AppleVersion] = Field(min_length=1)
    review: AppleReview | None = None
    beta_groups: list[AppleBetaGroup] = Field(default_factory=list)
    verify_base_territory: str | None = None
    verify_paid: bool | None = None
    confirm_asset_replacement: bool = False
    categories: dict[str, str] = Field(default_factory=dict)
    age_rating: dict[str, str | bool] = Field(default_factory=dict)
    in_app_purchases: list[AppleInAppPurchase] = Field(default_factory=list)
    subscription_groups: list[AppleSubscriptionGroup] = Field(default_factory=list)
    pricing: ApplePricing | None = None
    preorder_territory_availability: dict[str, bool] = Field(default_factory=dict)
    territory_expectations: dict[str, bool] = Field(default_factory=dict)
    confirm_subscription_price_changes: bool = False
    signing: AppleSigningConfig | None = None
    accessibility: list[AppleAccessibilityDeclaration] = Field(default_factory=list)
    privacy_manifest: ApplePrivacyManifest | None = None
    review_replies: list[StoreReviewReply] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_platforms(self) -> "AppleConfig":
        review_ids = [item.review_id for item in self.review_replies]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("Apple review replies must have unique review IDs")
        beta_names = [group.name for group in self.beta_groups]
        if len(beta_names) != len(set(beta_names)):
            raise ValueError("Apple TestFlight group names must be unique")
        product_ids = [item.product_id for item in self.in_app_purchases]
        product_ids.extend(
            subscription.product_id
            for group in self.subscription_groups
            for subscription in group.subscriptions
        )
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Apple in-app purchase and subscription product identifiers must be unique")
        group_names = [group.reference_name for group in self.subscription_groups]
        if len(group_names) != len(set(group_names)):
            raise ValueError("Apple subscription group reference names must be unique")
        families = [item.device_family for item in self.accessibility]
        if len(families) != len(set(families)):
            raise ValueError("Apple accessibility device families must be unique")
        platforms = [version.platform for version in self.versions]
        if len(platforms) != len(set(platforms)):
            raise ValueError("Apple platforms must be unique")
        return self
