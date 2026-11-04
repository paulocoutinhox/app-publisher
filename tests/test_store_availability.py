from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from app_publisher.cli import app
from app_publisher.core.publication_engine import PublicationEngine
from app_publisher.errors.unsafe_operation_error import UnsafeOperationError
from app_publisher.models.google_config import GoogleConfig
from app_publisher.models.google_country_expectation import GoogleCountryExpectation
from app_publisher.providers.store_availability import StoreAvailability


class FakeAvailabilityAPI:
    def __init__(self, countries=("BR", "US"), sync=False, rest=False):
        self.countries = countries
        self.sync = sync
        self.rest = rest
        self.requests = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path))
        if path.endswith("appAvailabilityV2"):
            return {"data": {"id": "availability"}}
        if method == "POST":
            return {"id": "edit-id"}
        if "countryAvailability" in path:
            return {
                "countries": [{"countryCode": code} for code in self.countries],
                "syncWithProduction": self.sync,
                "restOfWorld": self.rest,
            }
        return {}

    def paginated(self, path, **kwargs):
        return [
            {"attributes": {"available": True}, "relationships": {"territory": {"data": {"id": "USA"}}}},
            {"attributes": {"available": False}, "relationships": {"territory": {"data": {"id": "BRA"}}}},
        ]


def test_apple_country_checks():
    api = FakeAvailabilityAPI()
    auditor = StoreAvailability(api)
    assert auditor.apple("123", {}) == []
    assert auditor.apple("123", {"USA": True, "BRA": False}) == [
        "Apple availability: verified 2 declared territories"
    ]
    with pytest.raises(UnsafeOperationError, match="not present"):
        auditor.apple("123", {"JPN": True})
    with pytest.raises(UnsafeOperationError, match="expected available"):
        auditor.apple("123", {"BRA": True})


def test_google_country_checks_and_cleanup():
    api = FakeAvailabilityAPI()
    auditor = StoreAvailability(api)
    assert auditor.google("com.example.app", []) == []
    assert not api.requests
    expected = GoogleCountryExpectation(
        track="internal", countries=["BR", "US"], sync_with_production=False, rest_of_world=False
    )
    assert auditor.google("com.example.app", [expected]) == [
        "Google availability: verified track internal with 2 countries"
    ]
    assert api.requests[-1] == ("DELETE", "applications/com.example.app/edits/edit-id")
    for issue, value, message in [
        ("countries", ["BR"], "availability differs"),
        ("sync_with_production", True, "synchronization differs"),
        ("rest_of_world", True, "rest-of-world"),
    ]:
        values = {
            "track": "internal",
            "countries": ["BR", "US"],
            "sync_with_production": False,
            "rest_of_world": False,
        }
        values[issue] = value
        with pytest.raises(UnsafeOperationError, match=message):
            auditor.google("com.example.app", [GoogleCountryExpectation(**values)])
        assert api.requests[-1][0] == "DELETE"
    with pytest.raises(ValidationError, match="uppercase two-letter"):
        GoogleCountryExpectation(track="internal", countries=["usa"])
    with pytest.raises(ValidationError, match="duplicate"):
        GoogleCountryExpectation(track="internal", countries=["BR", "BR"])


def test_country_engine_and_cli(project, tmp_path, monkeypatch):
    assert PublicationEngine(project, tmp_path / "project.yaml").availability("all") == []
    project.apple.territory_expectations = {"USA": True}
    project.google.country_expectations = [
        GoogleCountryExpectation(track="production", countries=["BR", "US"])
    ]
    api = FakeAvailabilityAPI()
    manager = SimpleNamespace(api=api, identify=lambda: None)
    manager.api.close = lambda: None
    monkeypatch.setattr(PublicationEngine, "apple", lambda self: manager)
    monkeypatch.setattr(PublicationEngine, "google", lambda self: manager)
    engine = PublicationEngine(project, tmp_path / "project.yaml")
    assert engine.availability("apple") == ["Apple availability: verified 1 declared territories"]
    assert engine.availability("google") == [
        "Google availability: verified track production with 2 countries"
    ]
    assert len(engine.availability("all")) == 2
    monkeypatch.setattr(PublicationEngine, "availability", lambda self, provider: [provider])
    monkeypatch.setattr("app_publisher.cli.open_engine", lambda config: engine)
    response = CliRunner().invoke(app, ["availability", "unused.yaml"])
    assert response.exit_code == 0
    assert "all" in response.stdout
    with pytest.raises(ValidationError, match="tracks must be unique"):
        GoogleConfig.model_validate(
            {
                **project.google.model_dump(),
                "country_expectations": [{"track": "production"}, {"track": "production"}],
            }
        )
