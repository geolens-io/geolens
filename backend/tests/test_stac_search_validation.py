"""SEC-FU-05: STAC /search GET intersects max_length=10000 cap.

Pins the audit finding that the GET /api/stac/search?intersects= parameter
had no length cap, allowing multi-megabyte GeoJSON payloads to force JSON
parse + ST_GeomFromGeoJSON evaluation before any DB index could short-circuit.

Fix: Query(None, max_length=10000, ...) on the intersects parameter in the
GET handler. The POST handler is NOT affected — StacSearchBody.intersects:
dict is bounded by the application-wide RequestBodyLimitMiddleware
(default 500 MB) and the nginx proxy (client_max_body_size 500m), NOT by
a 1MB uvicorn limit (uvicorn has no built-in body size cap).
"""

import json

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helper: build a synthetic GeoJSON polygon string of a target byte count
# ---------------------------------------------------------------------------


def _build_polygon_string(target_len: int) -> str:
    """Build a GeoJSON Polygon string reaching approximately target_len bytes.

    Coordinates are simple lon/lat floats. The JSON is valid GeoJSON but the
    polygon is degenerate (collinear points). This is intentional: the test
    asserts the *route-level* length validation, not PostGIS validity.
    """
    # A single 2-decimal point like [1.23,4.56] is ~10 bytes including the comma.
    # Build up pairs until we overshoot then trim.
    header = '{"type":"Polygon","coordinates":[['
    footer = "]]}"
    # Reserve space for header and footer
    remaining = target_len - len(header) - len(footer) - 10  # 10 bytes slack
    coord_chunk = "[1.23,4.56],"
    pairs: list[str] = []
    total = 0
    while total + len(coord_chunk) < remaining:
        pairs.append("[1.23,4.56]")
        total += len(coord_chunk)
    # Close the ring — must repeat the first point
    if not pairs:
        pairs = ["[0.0,0.0]", "[1.0,0.0]", "[1.0,1.0]", "[0.0,1.0]", "[0.0,0.0]"]
    else:
        pairs.append(pairs[0])  # close ring
    body = header + ",".join(pairs) + footer
    return body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestSecFu05StacIntersectsMaxLength:
    async def test_sec_fu_05_over_limit_returns_problem_400(self, client: AsyncClient):
        """A 10001-char value is rejected as an OGC Problem Detail 400."""
        long_str = "x" * 10001
        resp = await client.get(
            "/stac/search",
            params={"intersects": long_str},
        )
        assert resp.status_code == 400, (
            f"Expected 400 for 10001-char intersects, got {resp.status_code}: {resp.text}"
        )
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        detail = str(body)
        assert "intersects" in detail or "max_length" in detail, (
            f"400 body did not mention 'intersects' or 'max_length': {body}"
        )

    async def test_sec_fu_05_just_under_limit_passes_length_validation(
        self, client: AsyncClient
    ):
        """Exactly 10000 chars passes the cap and reaches JSON parsing.

        The request is intentionally not JSON, so the route returns its own 400;
        the detail must be the JSON parse error rather than query validation.
        """
        exactly_10000 = "x" * 10000
        resp = await client.get(
            "/stac/search",
            params={"intersects": exactly_10000},
        )
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert "invalid intersects geometry" in resp.json()["detail"].lower()

    async def test_sec_fu_05_valid_short_intersects_not_length_rejected(
        self, client: AsyncClient
    ):
        """A 9000-char GeoJSON polygon string must not be rejected by max_length."""
        poly_9k = _build_polygon_string(9000)
        # Verify our builder produced something plausible
        assert len(poly_9k) < 10000, (
            f"Builder produced {len(poly_9k)} chars, expected < 10000"
        )
        resp = await client.get(
            "/stac/search",
            params={"intersects": poly_9k},
        )
        if resp.status_code == 400:
            assert "at most 10000" not in resp.json()["detail"].lower()

    async def test_sec_fu_05_post_body_is_capped(self, client: AsyncClient):
        """POST /stac/search body.intersects dict IS now capped (SEC-023).

        SEC-FU-05 capped only the GET `intersects` query param (max_length=10000);
        the POST body dict bypassed any bound and reached the same anonymous
        ST_GeomFromGeoJSON predicate (a multi-megabyte GeoJSON DoS amplifier).
        SEC-023 adds a matching serialized-size cap on StacSearchBody.intersects,
        so an oversized body now returns 400 before any spatial query runs. This
        test previously asserted the body was *unaffected* — that was the bug.
        """
        # Build a large polygon dict whose JSON representation exceeds 10000 chars
        coords = [[i * 0.01, j * 0.01] for i in range(50) for j in range(50)]
        # Close the ring
        coords.append(coords[0])
        intersects_dict = {
            "type": "Polygon",
            "coordinates": [coords],
        }
        serialized = json.dumps(intersects_dict)
        assert len(serialized) > 10000, (
            f"Test setup error: polygon JSON is only {len(serialized)} chars, need > 10000"
        )
        resp = await client.post(
            "/stac/search",
            json={"intersects": intersects_dict},
        )
        # The body cap rejects the oversized GeoJSON before PostGIS.
        assert resp.status_code == 400, (
            f"POST with oversized intersects dict must be capped (400), "
            f"got {resp.status_code}: {resp.text}"
        )
        assert resp.headers["content-type"].startswith("application/problem+json")


@pytest.mark.anyio
class TestStacSearchBodyBounds:
    """KNOWN-12: POST /stac/search body.limit/offset carry Pydantic ge/le."""

    async def test_post_search_limit_above_max_clamped(self, client: AsyncClient):
        """limit above the 200 ceiling is clamped, not rejected.

        The STAC Item Search spec (enforced by stac-api-validator) requires
        over-limit values to fall back to the server maximum.
        """
        resp = await client.post("/stac/search", json={"limit": 100000})
        assert resp.status_code == 200, resp.text
        assert resp.json()["context"]["limit"] == 200

    async def test_post_search_negative_offset_rejected(self, client: AsyncClient):
        """offset=-1 must be rejected with 400 (not silently clamped)."""
        resp = await client.post("/stac/search", json={"offset": -1})
        assert resp.status_code == 400, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")

    async def test_post_search_zero_limit_rejected(self, client: AsyncClient):
        """limit=0 must be rejected with 400 (ge=1)."""
        resp = await client.post("/stac/search", json={"limit": 0})
        assert resp.status_code == 400, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")

    async def test_post_search_limit_within_bounds_accepted(self, client: AsyncClient):
        """limit=200 (at the le=200 ceiling) must pass schema validation."""
        resp = await client.post("/stac/search", json={"limit": 200, "offset": 0})
        assert resp.status_code == 200, resp.text
