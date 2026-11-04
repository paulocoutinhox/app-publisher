from pathlib import Path

from pydantic import Field, model_validator

from app_publisher.models.google_base_plan_state import GoogleBasePlanState
from app_publisher.models.google_country_expectation import GoogleCountryExpectation
from app_publisher.models.google_listing_deletion import GoogleListingDeletion
from app_publisher.models.google_monetization_product import GoogleMonetizationProduct
from app_publisher.models.google_one_time_offer import GoogleOneTimeOffer
from app_publisher.models.google_one_time_offer_deletion import GoogleOneTimeOfferDeletion
from app_publisher.models.google_purchase_option_deletion import GooglePurchaseOptionDeletion
from app_publisher.models.google_purchase_option_state import GooglePurchaseOptionState
from app_publisher.models.google_release import GoogleRelease
from app_publisher.models.google_store_details import GoogleStoreDetails
from app_publisher.models.google_subscription_offer import GoogleSubscriptionOffer
from app_publisher.models.google_subscription_offer_deletion import GoogleSubscriptionOfferDeletion
from app_publisher.models.google_tester_group import GoogleTesterGroup
from app_publisher.models.store_review_reply import StoreReviewReply
from app_publisher.models.strict_model import StrictModel


class GoogleConfig(StrictModel):
    package_name: str = Field(min_length=3)
    release: GoogleRelease | None = None
    data_safety_csv: Path | None = None
    confirm_image_replacement: bool = False
    store_details: GoogleStoreDetails | None = None
    listing_deletions: list[GoogleListingDeletion] = Field(default_factory=list)
    review_replies: list[StoreReviewReply] = Field(default_factory=list)
    tester_groups: list[GoogleTesterGroup] = Field(default_factory=list)
    subscriptions: list[GoogleMonetizationProduct] = Field(default_factory=list)
    one_time_products: list[GoogleMonetizationProduct] = Field(default_factory=list)
    subscription_offers: list[GoogleSubscriptionOffer] = Field(default_factory=list)
    subscription_offer_deletions: list[GoogleSubscriptionOfferDeletion] = Field(default_factory=list)
    base_plan_states: list[GoogleBasePlanState] = Field(default_factory=list)
    one_time_offers: list[GoogleOneTimeOffer] = Field(default_factory=list)
    one_time_offer_deletions: list[GoogleOneTimeOfferDeletion] = Field(default_factory=list)
    purchase_option_states: list[GooglePurchaseOptionState] = Field(default_factory=list)
    purchase_option_deletions: list[GooglePurchaseOptionDeletion] = Field(default_factory=list)
    country_expectations: list[GoogleCountryExpectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_monetization_ids(self) -> "GoogleConfig":
        tester_tracks = [item.track for item in self.tester_groups]
        if len(tester_tracks) != len(set(tester_tracks)):
            raise ValueError("Google tester tracks must be unique")
        if self.release and self.release.testers and self.release.track in tester_tracks:
            raise ValueError("A Google track cannot declare both release testers and tester_groups")
        deletion_locales = [item.locale for item in self.listing_deletions]
        if len(deletion_locales) != len(set(deletion_locales)):
            raise ValueError("Google listing deletions must have unique locales")
        review_ids = [item.review_id for item in self.review_replies]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("Google review replies must have unique review IDs")
        one_time_offers = [
            (item.product_id, item.purchase_option_id, item.offer_id) for item in self.one_time_offers
        ]
        deleted_offers = [
            (item.product_id, item.purchase_option_id, item.offer_id)
            for item in self.one_time_offer_deletions
        ]
        if len(one_time_offers) != len(set(one_time_offers)) or len(deleted_offers) != len(
            set(deleted_offers)
        ):
            raise ValueError("Google one-time offer identifiers must be unique")
        if set(one_time_offers).intersection(deleted_offers):
            raise ValueError("A Google one-time offer cannot be changed and deleted in one configuration")
        option_states = [(item.product_id, item.purchase_option_id) for item in self.purchase_option_states]
        option_deletions = [
            (item.product_id, item.purchase_option_id) for item in self.purchase_option_deletions
        ]
        if len(option_states) != len(set(option_states)) or len(option_deletions) != len(
            set(option_deletions)
        ):
            raise ValueError("Google purchase option operations must have unique identifiers")
        if set(option_states).intersection(option_deletions):
            raise ValueError("A Google purchase option cannot be changed and deleted in one configuration")
        tracks = [item.track for item in self.country_expectations]
        if len(tracks) != len(set(tracks)):
            raise ValueError("Google country expectation tracks must be unique")
        subscriptions = [item.product_id for item in self.subscriptions]
        products = [item.product_id for item in self.one_time_products]
        offers = [(item.product_id, item.base_plan_id, item.offer_id) for item in self.subscription_offers]
        deleted_subscription_offers = [
            (item.product_id, item.base_plan_id, item.offer_id) for item in self.subscription_offer_deletions
        ]
        if len(deleted_subscription_offers) != len(set(deleted_subscription_offers)):
            raise ValueError("Google subscription offer deletions must be unique")
        if set(offers).intersection(deleted_subscription_offers):
            raise ValueError("A Google subscription offer cannot be changed and deleted in one configuration")
        states = [(item.product_id, item.base_plan_id) for item in self.base_plan_states]
        if (
            len(subscriptions) != len(set(subscriptions))
            or len(products) != len(set(products))
            or len(offers) != len(set(offers))
            or len(states) != len(set(states))
        ):
            raise ValueError("Google monetization identifiers must be unique within their resource type")
        return self
