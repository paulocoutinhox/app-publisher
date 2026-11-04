import pytest
from pydantic import ValidationError

from app_publisher.enums.apple_release_type import AppleReleaseType
from app_publisher.enums.google_release_status import GoogleReleaseStatus
from app_publisher.models.apple_certificate_issuance import AppleCertificateIssuance
from app_publisher.models.apple_registered_device import AppleRegisteredDevice
from app_publisher.models.apple_subscription import AppleSubscription
from app_publisher.models.apple_version import AppleVersion
from app_publisher.models.google_metadata import GoogleMetadata
from app_publisher.models.google_release import GoogleRelease
from app_publisher.models.privacy_accessed_api import PrivacyAccessedAPI
from app_publisher.models.privacy_collected_data import PrivacyCollectedData
from app_publisher.models.project_config import ProjectConfig
from app_publisher.models.screenshot_action import ScreenshotAction
from app_publisher.models.screenshot_plan import ScreenshotPlan


@pytest.mark.parametrize("spelling", ["manual", "Manual", "MANUAL", "mAnUaL"])
def test_release_options_serialize_to_api_case(spelling):
    version = AppleVersion(platform="iOs", version="1.0.0", release_type=spelling)
    assert version.model_dump(mode="json")["release_type"] == "MANUAL"
    assert version.platform == "IOS"
    version.release_type = "aFtEr_ApPrOvAl"
    assert version.release_type == "AFTER_APPROVAL"


def test_nested_options_and_dictionary_keys_preserve_identifiers():
    item = ProjectConfig.model_validate(
        {
            "schema_version": 1,
            "app": {"id": "Keep.My.ID", "default_locale": "pt-BR", "paid": False},
            "apple": {
                "app_id": "123",
                "bundle_id": "com.Company.MyApp",
                "versions": [
                    {
                        "platform": "mac_os",
                        "version": "1.0.0",
                        "release_type": "sChEdUlEd",
                        "earliest_release_date": "2026-12-01T12:00:00Z",
                    }
                ],
            },
            "google": {
                "package_name": "com.company.myapp",
                "release": {"status": "InPrOgReSs", "rollout_fraction": 0.1, "track": "MyCustomTrack"},
            },
            "locales": {
                "pt-BR": {
                    "common": {"name": "Mixed CASE title"},
                    "google": {"images": {"PHONESCREENSHOTS": ["Screenshots/KeepCase.png"]}},
                }
            },
        }
    )
    result = item.model_dump(mode="json")
    assert result["apple"]["bundle_id"] == "com.Company.MyApp"
    assert result["app"]["id"] == "Keep.My.ID"
    assert result["app"]["default_locale"] == "pt-BR"
    assert result["google"]["release"]["status"] == "inProgress"
    assert result["google"]["release"]["track"] == "MyCustomTrack"
    assert result["locales"]["pt-BR"]["common"]["name"] == "Mixed CASE title"
    assert result["locales"]["pt-BR"]["google"]["images"] == {
        "phoneScreenshots": ["Screenshots/KeepCase.png"]
    }


def test_unknown_values_and_case_collisions_fail_explicitly():
    for value in (None, 123, "UNKNOWN", "manual "):
        with pytest.raises(ValueError):
            AppleReleaseType(value)
    with pytest.raises(ValidationError):
        AppleVersion(platform="iPhone", version="1.0.0")
    with pytest.raises(ValidationError, match="Duplicate Google image"):
        GoogleMetadata(images={"phoneScreenshots": ["a.png"], "PHONESCREENSHOTS": ["b.png"]})
    with pytest.raises(ValidationError, match="mapping"):
        GoogleMetadata(images=[])
    with pytest.raises(ValidationError):
        GoogleMetadata(images={"unsupported": ["a.png"]})
    assert GoogleReleaseStatus("INPROGRESS").value == "inProgress"


def test_screenshot_and_privacy_options():
    assert ScreenshotAction(kind="ROTATE", value="landscape_left").value == "LANDSCAPE_LEFT"
    assert ScreenshotAction(kind="REMOTE", value="MENU").value == "menu"
    assert ScreenshotAction(kind="TEXT", value="Keep THIS Case").value == "Keep THIS Case"
    assert (
        ScreenshotPlan(
            platform="AnDrOiD",
            device="KeepSerial",
            driver="NATIVE",
            scenes=[{"name": "Home", "url": "app://Home", "output": "Shots/Home.png"}],
        ).platform
        == "android"
    )
    assert (
        AppleSubscription(product_id="Keep.ProductID", name="Monthly", period="one_month").period
        == "ONE_MONTH"
    )
    assert PrivacyCollectedData(
        data_type="NSPrivacyCollectedDataTypeName",
        linked=False,
        tracking=False,
        purposes=["nsprivacycollecteddatatypepurposeanalytics"],
    ).purposes == ["NSPrivacyCollectedDataTypePurposeAnalytics"]
    assert (
        PrivacyAccessedAPI(category="nsprivacyaccessedapicategoryfiletimestamp", reasons=["C617.1"]).category
        == "NSPrivacyAccessedAPICategoryFileTimestamp"
    )
    assert AppleRegisteredDevice(name="My Phone", udid="0" * 40, platform="ios").platform == "IOS"
    assert (
        AppleCertificateIssuance(
            certificate_type="ios_distribution",
            private_key_output="keys/private.pem",
            csr_output="keys/request.csr",
            certificate_output="keys/certificate.cer",
            password_env="KEEP_SECRET_ENV",
            common_name="Test Certificate",
            email_address="test@example.com",
        ).certificate_type
        == "IOS_DISTRIBUTION"
    )


def test_defaults_use_plain_canonical_strings():
    assert type(AppleVersion(platform="IOS", version="1.0").release_type) is str
    assert type(GoogleRelease().status) is str
