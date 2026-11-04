from typing import Any

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError

CATEGORY_FIELDS = {
    "primaryCategory",
    "primarySubcategoryOne",
    "primarySubcategoryTwo",
    "secondaryCategory",
    "secondarySubcategoryOne",
    "secondarySubcategoryTwo",
}
AGE_RATING_FIELDS = {
    "advertising",
    "alcoholTobaccoOrDrugUseOrReferences",
    "contests",
    "gambling",
    "gamblingSimulated",
    "gunsOrOtherWeapons",
    "healthOrWellnessTopics",
    "kidsAgeBand",
    "lootBox",
    "medicalOrTreatmentInformation",
    "messagingAndChat",
    "parentalControls",
    "profanityOrCrudeHumor",
    "ageAssurance",
    "sexualContentGraphicAndNudity",
    "sexualContentOrNudity",
    "socialMedia",
    "socialMediaAgeRestricted",
    "horrorOrFearThemes",
    "matureOrSuggestiveThemes",
    "unrestrictedWebAccess",
    "userGeneratedContent",
    "violenceCartoonOrFantasy",
    "violenceRealisticProlongedGraphicOrSadistic",
    "violenceRealistic",
    "ageRatingOverride",
    "ageRatingOverrideV2",
    "koreaAgeRatingOverride",
    "developerAgeRatingInfoUrl",
}


class AppleInformation:
    def __init__(self, api: APIClient, app_id: str):
        self.api = api
        self.app_id = app_id

    def synchronize(
        self, categories: dict[str, str], age_rating: dict[str, Any], *, apply: bool
    ) -> list[str]:
        if not categories and not age_rating:
            return []
        unknown = set(categories) - CATEGORY_FIELDS
        if unknown:
            raise ConfigurationError(f"Unknown Apple category fields: {', '.join(sorted(unknown))}")
        unknown_age = set(age_rating) - AGE_RATING_FIELDS
        if unknown_age:
            raise ConfigurationError(f"Unknown Apple age rating fields: {', '.join(sorted(unknown_age))}")
        infos = self.api.paginated(f"apps/{self.app_id}/appInfos", params={"limit": 200})
        if len(infos) != 1:
            raise ConfigurationError("Apple app info must resolve to exactly one editable resource")
        info_id = infos[0]["id"]
        changes: list[str] = []
        if categories:
            resource = self.api.request(
                "GET", f"appInfos/{info_id}", params={"include": ",".join(sorted(categories))}
            )["data"]
            current = resource.get("relationships", {})
            updates = {
                key: value
                for key, value in categories.items()
                if current.get(key, {}).get("data", {}).get("id") != value
            }
            if updates:
                changes.append(f"Apple categories: update {', '.join(sorted(updates))}")
                if apply:
                    relationships = {
                        key: {"data": {"id": value, "type": "appCategories"}}
                        for key, value in updates.items()
                    }
                    self.api.request(
                        "PATCH",
                        f"appInfos/{info_id}",
                        payload={"data": {"id": info_id, "type": "appInfos", "relationships": relationships}},
                    )
        if age_rating:
            declaration = self.api.request("GET", f"appInfos/{info_id}/ageRatingDeclaration")["data"]
            updates = {
                key: value for key, value in age_rating.items() if declaration["attributes"].get(key) != value
            }
            if updates:
                changes.append(f"Apple age rating: update {', '.join(sorted(updates))}")
                if apply:
                    self.api.request(
                        "PATCH",
                        f"ageRatingDeclarations/{declaration['id']}",
                        payload={
                            "data": {
                                "id": declaration["id"],
                                "type": "ageRatingDeclarations",
                                "attributes": updates,
                            }
                        },
                    )
        return changes
