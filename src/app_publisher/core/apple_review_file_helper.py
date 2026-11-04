from pathlib import Path

from app_publisher.models.apple_config import AppleConfig
from app_publisher.models.apple_review_screenshot import AppleReviewScreenshot


class AppleReviewFileHelper:
    @staticmethod
    def review_screenshots(configuration: AppleConfig) -> list[AppleReviewScreenshot]:
        products = [*configuration.in_app_purchases]
        products.extend(item for group in configuration.subscription_groups for item in group.subscriptions)
        return [item.review_screenshot for item in products if item.review_screenshot is not None]

    @classmethod
    def paths(cls, configuration: AppleConfig) -> list[Path]:
        paths = [item.path for item in cls.review_screenshots(configuration)]

        if configuration.review is not None:
            paths.extend(item.path for item in configuration.review.attachments)

        return paths
