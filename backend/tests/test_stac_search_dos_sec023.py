"""Regression test for SEC-023: STAC POST /search intersects GeoJSON DoS cap.

The GET `intersects` query param is capped at max_length=10000 (SEC-FU-05), but
`StacSearchBody.intersects` (the POST body dict) had no bound and reached the
same anonymous ST_GeomFromGeoJSON / ST_Intersects predicate — a multi-megabyte
GeoJSON polygon could pin CPU/memory and a DB connection. The fix caps the
serialized size on the model, matching the GET handler.

Pure-model tests (no DB): instantiating StacSearchBody runs the validator.
"""

import json

import pytest
from pydantic import ValidationError

from app.standards.stac.router import StacSearchBody


def _polygon(n_vertices: int) -> dict:
    coords = [[i * 1e-6, i * 1e-6] for i in range(n_vertices)]
    return {"type": "Polygon", "coordinates": [coords]}


def test_oversized_intersects_is_rejected():
    """A huge GeoJSON polygon is rejected at validation (422 at the API)."""
    big = _polygon(5000)
    assert len(json.dumps(big)) > 10000, "test fixture should exceed the cap"
    with pytest.raises(ValidationError):
        StacSearchBody(intersects=big)


def test_normal_intersects_is_allowed():
    """GUARD: an ordinary polygon passes unchanged."""
    small = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    body = StacSearchBody(intersects=small)
    assert body.intersects == small


def test_absent_intersects_is_allowed():
    """GUARD: omitting intersects is still valid."""
    assert StacSearchBody().intersects is None
