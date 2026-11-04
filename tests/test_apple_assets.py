import httpx
import pytest
from conftest import Recorder

from app_publisher.core.api_client import APIClient
from app_publisher.errors.configuration_error import ConfigurationError
from app_publisher.errors.remote_api_error import RemoteAPIError
from app_publisher.providers.apple_asset_library import AppleAssetLibrary
from app_publisher.providers.apple_asset_upload_helper import AppleAssetUploadHelper


def asset_reference():
    return {
        "placementProfileGroups": [
            {"placementProfileGroupId": "IPHONE_DUO_OUTER_PROFILE", "displayClassId": "IPHONE_DUO"}
        ],
        "placementTypes": [
            {
                "placementTypeId": "APP_SCREENSHOT",
                "specMappings": [{"placementGroupId": "IPHONE_DUO_OUTER_PROFILE", "specs": ["spec"]}],
            }
        ],
        "imageSpecs": [
            {
                "specId": "spec",
                "dimensions": {"minWidth": 1200, "maxWidth": 1200, "minHeight": 1600, "maxHeight": 1600},
                "fileExtensions": [".png"],
                "maxFileSize": 5000000,
            }
        ],
    }


def test_asset_library_uploads_and_places_iphone_duo(png):

    def handler(req):
        if req.url.path.endswith("/appAssetLibraryRefData"):
            return httpx.Response(200, json={"data": [{"attributes": asset_reference()}]})
        if req.url.path.endswith("/assetLibrary"):
            return httpx.Response(200, json={"data": {"id": "lib"}})
        if req.url.path.endswith("/placements") or req.url.path.endswith("/images"):
            return httpx.Response(200, json={"data": []})
        if req.url.path.endswith("/appAssetLibraryImages") and req.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "image",
                        "attributes": {
                            "uploadOperations": [
                                {
                                    "method": "PUT",
                                    "url": "https://upload.test/image",
                                    "offset": 0,
                                    "length": png.stat().st_size,
                                    "requestHeaders": [{"name": "Content-Type", "value": "image/png"}],
                                }
                            ]
                        },
                    }
                },
            )
        if req.url.path.endswith("/appAssetLibraryImages/image") and req.method == "GET":
            return httpx.Response(200, json={"data": {"attributes": {"state": "PREPARE_FOR_SUBMISSION"}}})
        if req.url.path.endswith("/appAssetLibraryPlacements") and req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "placement"}})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    assets = AppleAssetLibrary(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(rec)), "123"
    )
    result = assets.synchronize("localization", {"IPHONE_DUO": ["shot.png"]}, png.parent)
    assert result == ["Apple IPHONE_DUO_OUTER_PROFILE: synchronized 1 screenshots"]
    assert any(req.url.host == "upload.test" for req in rec.calls)
    assert any(req.url.path.endswith("/appAssetLibraryPlacementOrderingRequests") for req in rec.calls)
    assert any(req.method == "PATCH" for req in rec.calls)


def test_asset_existing_placement_with_same_hash_is_noop(png):
    name = AppleAssetLibrary.reference_name(png)

    def handler(req):
        if req.url.path.endswith("/appAssetLibraryRefData"):
            return httpx.Response(200, json={"data": [{"attributes": asset_reference()}]})
        if req.url.path.endswith("/assetLibrary"):
            return httpx.Response(200, json={"data": {"id": "lib"}})
        if req.url.path.endswith("/placements"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "pl1",
                            "attributes": {"placementGroup": "IPHONE_DUO_OUTER_PROFILE"},
                            "relationships": {"image": {"data": {"id": "img1"}}},
                        }
                    ]
                },
            )
        if req.url.path.endswith("/appAssetLibraryImages/img1"):
            return httpx.Response(200, json={"data": {"attributes": {"referenceName": name}}})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    assets = AppleAssetLibrary(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(rec)), "123"
    )
    assert assets.synchronize("locale", {"IPHONE_DUO_OUTER_PROFILE": ["shot.png"]}, png.parent) == []
    assert not any(req.method in {"POST", "PATCH", "DELETE"} for req in rec.calls)


def test_asset_existing_library_image_and_replace_placement(png):
    def handler(req):
        if req.url.path.endswith("/appAssetLibraryRefData"):
            return httpx.Response(200, json={"data": [{"attributes": asset_reference()}]})
        if req.url.path.endswith("/assetLibrary"):
            return httpx.Response(200, json={"data": {"id": "lib"}})
        if req.url.path.endswith("/placements"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "old",
                            "attributes": {"placementGroup": "IPHONE_DUO_OUTER_PROFILE"},
                            "relationships": {"image": {"data": {"id": "oldImage"}}},
                        }
                    ]
                },
            )
        if req.url.path.endswith("/appAssetLibraryImages/oldImage"):
            return httpx.Response(200, json={"data": {"attributes": {"referenceName": "wrong"}}})
        if req.url.path.endswith("/images"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "cached",
                            "attributes": {"referenceName": AppleAssetLibrary.reference_name(png)},
                        }
                    ]
                },
            )
        if req.url.path.endswith("/appAssetLibraryImages/cached"):
            return httpx.Response(200, json={"data": {"attributes": {"state": "APPROVED"}}})
        if req.url.path.endswith("/appAssetLibraryPlacements"):
            return httpx.Response(201, json={"data": {"id": "new"}})
        return httpx.Response(200, json={})

    rec = Recorder(handler)
    assets = AppleAssetLibrary(
        APIClient("https://api.test", lambda: "token", httpx.MockTransport(rec)), "123"
    )
    assert (
        len(assets.synchronize("loc", {"IPHONE_DUO": ["shot.png"]}, png.parent, confirm_replacement=True))
        == 1
    )
    assert any(
        req.method == "DELETE" and req.url.path.endswith("/appAssetLibraryPlacements/old")
        for req in rec.calls
    )
    assert not any(
        req.method == "POST" and req.url.path.endswith("/appAssetLibraryImages") for req in rec.calls
    )


def test_asset_reference_errors_and_processing(png, monkeypatch):
    api = APIClient(
        "https://api.test",
        lambda: "token",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})),
    )
    library = AppleAssetLibrary(api, "123")
    with pytest.raises(RemoteAPIError, match="exactly one"):
        library.reference_data()
    with pytest.raises(ConfigurationError, match="Unknown"):
        library.resolve_group("UNKNOWN", asset_reference())
    with pytest.raises(ConfigurationError, match="does not accept"):
        library.validate_dimensions(png, "NONMATCH", asset_reference())
    reference = asset_reference()
    reference["placementTypes"] = []
    with pytest.raises(RemoteAPIError, match="does not describe"):
        library.validate_dimensions(png, "IPHONE_DUO_OUTER_PROFILE", reference)
    reference = asset_reference()
    reference["imageSpecs"][0]["dimensions"]["minWidth"] = 2000
    reference["imageSpecs"][0]["dimensions"]["maxWidth"] = 2000
    with pytest.raises(ConfigurationError, match="does not match"):
        library.validate_dimensions(png, "IPHONE_DUO_OUTER_PROFILE", reference)

    def client_for_state(state):
        response = {"data": {"attributes": {"state": state, "stateDetails": {"message": "bad"}}}}
        return APIClient(
            "https://api.test",
            lambda: "token",
            httpx.MockTransport(lambda req: httpx.Response(200, json=response)),
        )

    with pytest.raises(RemoteAPIError, match="Unexpected"):
        AppleAssetLibrary(client_for_state("FUTURE_STATE"), "123").wait_image("img")
    with pytest.raises(RemoteAPIError, match="processing failed"):
        AppleAssetLibrary(client_for_state("FAILED"), "123").wait_image("img")
    monkeypatch.setattr("app_publisher.providers.apple_asset_library.time.sleep", lambda _: None)
    with pytest.raises(RemoteAPIError, match="timed out"):
        AppleAssetLibrary(client_for_state("UPLOAD_COMPLETE"), "123").wait_image("img")


def test_upload_parts_rejects_network_error():
    api = APIClient(
        "https://api.test",
        lambda: "token",
        httpx.MockTransport(lambda r: httpx.Response(403, text="forbidden")),
    )
    with pytest.raises(RemoteAPIError, match="transfer"):
        AppleAssetUploadHelper.upload_parts(
            api, [{"method": "PUT", "url": "https://cdn.test/upload", "offset": 0, "length": 3}], b"abc"
        )
