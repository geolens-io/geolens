"""Resource-boundary tests for GeoJSON feature writes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.catalog.features import schemas
from app.modules.catalog.features.schemas import FeatureCreate, GeoJSONFeature


def _feature(geometry: dict) -> dict:
    return {"geometry": geometry, "properties": {}}


def test_accepts_bounded_finite_wgs84_geometry():
    parsed = FeatureCreate.model_validate(
        _feature(
            {
                "type": "LineString",
                "coordinates": [[-74.0, 40.7, 5.0], [-73.9, 40.8, 6.0]],
            }
        )
    )
    assert parsed.geometry.type == "LineString"


@pytest.mark.parametrize(
    "coordinates",
    [
        [181.0, 0.0],
        [0.0, 91.0],
        [float("nan"), 0.0],
        [0.0, float("inf")],
        [True, 0.0],
        [10**400, 0],
        [0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0],
    ],
)
def test_rejects_invalid_position_values(coordinates):
    with pytest.raises(ValidationError):
        FeatureCreate.model_validate(
            _feature({"type": "Point", "coordinates": coordinates})
        )


def test_rejects_excessive_coordinate_cardinality(monkeypatch):
    monkeypatch.setattr(schemas, "MAX_COORDINATE_TUPLES", 2)
    with pytest.raises(ValidationError, match="coordinate limit"):
        FeatureCreate.model_validate(
            _feature(
                {
                    "type": "LineString",
                    "coordinates": [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
                }
            )
        )


def test_rejects_excessive_coordinate_depth(monkeypatch):
    monkeypatch.setattr(schemas, "MAX_COORDINATE_DEPTH", 2)
    with pytest.raises(ValidationError, match="nesting"):
        FeatureCreate.model_validate(
            _feature(
                {
                    "type": "MultiPolygon",
                    "coordinates": [[[[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]],
                }
            )
        )


def test_collection_limit_applies_across_children(monkeypatch):
    monkeypatch.setattr(schemas, "MAX_COORDINATE_TUPLES", 3)
    with pytest.raises(ValidationError, match="GeometryCollection"):
        FeatureCreate.model_validate(
            _feature(
                {
                    "type": "GeometryCollection",
                    "geometries": [
                        {
                            "type": "LineString",
                            "coordinates": [[0.0, 0.0], [1.0, 1.0]],
                        },
                        {
                            "type": "LineString",
                            "coordinates": [[2.0, 2.0], [3.0, 3.0]],
                        },
                    ],
                }
            )
        )


def test_collection_member_limit(monkeypatch):
    monkeypatch.setattr(schemas, "MAX_GEOMETRY_COLLECTION_MEMBERS", 1)
    with pytest.raises(ValidationError, match="member limit"):
        FeatureCreate.model_validate(
            _feature(
                {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "Point", "coordinates": [0.0, 0.0]},
                        {"type": "Point", "coordinates": [1.0, 1.0]},
                    ],
                }
            )
        )


def test_read_schema_does_not_reject_existing_complex_geometry(monkeypatch):
    """Write budgets must not make a previously ingested feature unreadable."""
    monkeypatch.setattr(schemas, "MAX_COORDINATE_TUPLES", 1)
    parsed = GeoJSONFeature.model_validate(
        {
            "id": 1,
            "geometry": {
                "type": "LineString",
                "coordinates": [[0.0, 0.0], [1.0, 1.0]],
            },
            "properties": {},
        }
    )
    assert parsed.geometry is not None
