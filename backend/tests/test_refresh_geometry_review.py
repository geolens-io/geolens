"""Geometry changes hold a service refresh for review; normalizations never do."""

from __future__ import annotations

import pytest

from app.platform.refresh.verification import (
    GeometryContract,
    geometry_contract,
    verify_service_refresh,
)


def _contract(
    geometry_type: str | None = "POLYGON",
    srid: int | None = 2263,
    is_3d: bool | None = False,
    n_dims: int | None = 2,
) -> GeometryContract:
    return geometry_contract(
        geometry_type=geometry_type, srid=srid, is_3d=is_3d, n_dims=n_dims
    )


def _verify(live: GeometryContract, staged: GeometryContract, **extra):
    return verify_service_refresh(
        source_binding={
            "service_type": "wfs",
            "url": "https://example.com/wfs",
            "layer_id": "roads",
        },
        schema_diff={"row_count_old": 10, "row_count_new": 10},
        expected_feature_count=10,
        fetched_feature_count=10,
        content_digest="a" * 64,
        staged_geometry_type=None,
        staged_srid=None,
        staged_coordinate_dimension=None,
        live=live,
        staged=staged,
        **extra,
    )


@pytest.mark.parametrize(
    ("live", "staged", "reason"),
    [
        (_contract("POLYGON"), _contract("POINT"), "geometry_type_changed"),
        (_contract("LINESTRING"), _contract("MULTIPOLYGON"), "geometry_type_changed"),
        (_contract(srid=2263), _contract(srid=4326), "srid_changed"),
        (
            _contract(is_3d=True, n_dims=3),
            _contract(is_3d=False, n_dims=3),
            "coordinate_dimension_reduced",
        ),
        (
            _contract(is_3d=None, n_dims=3),
            _contract(is_3d=None, n_dims=2),
            "coordinate_dimension_reduced",
        ),
        (
            _contract(is_3d=False, n_dims=3),
            _contract(is_3d=True, n_dims=3),
            "coordinate_dimension_reduced",
        ),
    ],
)
def test_a_geometry_change_blocks_with_its_one_reason(live, staged, reason) -> None:
    result = _verify(live, staged)

    assert result["decision"] == "blocked"
    assert result["review_reasons"] == [reason]


@pytest.mark.parametrize(
    ("live", "staged"),
    [
        (_contract("POLYGON"), _contract("MULTIPOLYGON")),
        (_contract("MULTIPOLYGON"), _contract("POLYGON")),
        (_contract(is_3d=False, n_dims=2), _contract(is_3d=True, n_dims=3)),
        (_contract(None, None, None, None), _contract("POINT", 4326, True, 3)),
        (_contract("POLYGON"), _contract("GEOMETRY")),
        (_contract(is_3d=False, n_dims=3), _contract(is_3d=True, n_dims=4)),
        (_contract(is_3d=False, n_dims=3), _contract(is_3d=None, n_dims=3)),
    ],
)
def test_normalizations_and_unknown_facts_stay_allowed(live, staged) -> None:
    result = _verify(live, staged)

    assert result["decision"] == "allowed"
    assert result["review_reasons"] == []


def test_a_geometry_hold_is_released_by_its_own_fingerprint() -> None:
    live, staged = _contract("POLYGON"), _contract("POINT")
    held = _verify(live, staged)

    released = _verify(
        live,
        staged,
        accepted_fingerprint=held["review_fingerprint"],
        accepted_run_id="blocked-run",
    )

    assert released["decision"] == "allowed"
    assert released["accepted_blocked_run_id"] == "blocked-run"


def test_the_evidence_records_what_was_compared() -> None:
    result = _verify(_contract(srid=None), _contract("POINT", 4326))

    assert result["geometry_contract"]["live"]["srid"] is None
    assert result["geometry_contract"]["staged"]["family"] == "point"
