"""Focused API-contract checks for bounded pagination and map defaults."""

from app.api.main import app
from app.modules.settings.schemas import MapDefaultsResponse


def test_dataset_maps_pagination_parameters_are_bounded() -> None:
    operation = app.openapi()["paths"]["/datasets/{dataset_id}/maps/"]["get"]
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in operation["parameters"]
        if parameter["in"] == "query"
    }

    assert parameters["skip"]["default"] == 0
    assert parameters["skip"]["minimum"] == 0
    assert parameters["limit"]["default"] == 50
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 200


def test_map_defaults_response_matches_runtime_clamps() -> None:
    properties = MapDefaultsResponse.model_json_schema()["properties"]

    assert properties["center_lat"]["minimum"] == -90
    assert properties["center_lat"]["maximum"] == 90
    assert properties["center_lng"]["minimum"] == -180
    assert properties["center_lng"]["maximum"] == 180
    assert properties["zoom"]["minimum"] == 0
    assert properties["zoom"]["maximum"] == 22
