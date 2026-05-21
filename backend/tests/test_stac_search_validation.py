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
    async def test_sec_fu_05_over_limit_returns_422(self, client: AsyncClient):
        """A 10001-char intersects value must be rejected with 422 before the DB."""
        long_str = "x" * 10001
        resp = await client.get(
            "/stac/search",
            params={"intersects": long_str},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for 10001-char intersects, got {resp.status_code}: {resp.text}"
        )
        # FastAPI validation error body must mention the field
        body = resp.json()
        detail = str(body)
        assert "intersects" in detail or "max_length" in detail, (
            f"422 body did not mention 'intersects' or 'max_length': {body}"
        )

    async def test_sec_fu_05_just_under_limit_not_422(self, client: AsyncClient):
        """Exactly 10000-char intersects must NOT be rejected with 422.

        The request may fail with 400 (invalid JSON) or 422 from other
        validation, but NOT 422 from the max_length cap. We assert the
        response is not 422.
        """
        exactly_10000 = "x" * 10000
        resp = await client.get(
            "/stac/search",
            params={"intersects": exactly_10000},
        )
        # Must NOT be 422 — the cap is max_length=10000 (inclusive)
        assert resp.status_code != 422, (
            f"10000-char intersects incorrectly rejected with 422 (cap is ≤ 10000, not < 10000): {resp.text}"
        )

    async def test_sec_fu_05_valid_short_intersects_not_422(self, client: AsyncClient):
        """A 9000-char GeoJSON polygon string must not be rejected by max_length."""
        poly_9k = _build_polygon_string(9000)
        # Verify our builder produced something plausible
        assert len(poly_9k) < 10000, f"Builder produced {len(poly_9k)} chars, expected < 10000"
        resp = await client.get(
            "/stac/search",
            params={"intersects": poly_9k},
        )
        # Must not 422 due to max_length (may 200 or fail for other reasons)
        assert resp.status_code != 422, (
            f"9000-char intersects rejected with 422 (should not hit max_length cap): {resp.text}"
        )

    async def test_sec_fu_05_post_body_unaffected(self, client: AsyncClient):
        """POST /stac/search body.intersects dict is NOT capped by max_length.

        The POST handler accepts StacSearchBody.intersects: dict — bounded by
        the application-wide RequestBodyLimitMiddleware (default 500 MB) and
        the nginx proxy (client_max_body_size 500m), NOT by a 1MB uvicorn limit
        (uvicorn has no built-in body size cap). The Query max_length constraint
        applies only to GET query-string parameters, not to POST body fields.
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
        # Must not 422 — the body path has no max_length constraint
        assert resp.status_code != 422, (
            f"POST with large intersects dict returned 422 — "
            f"body path must not apply max_length: {resp.text}"
        )


@pytest.mark.anyio
class TestStacSearchBodyBounds:
    """KNOWN-12: POST /stac/search body.limit/offset carry Pydantic ge/le."""

    async def test_post_search_limit_above_le_rejected(self, client: AsyncClient):
        """limit=10001 must be rejected by Pydantic 422 (not silently clamped)."""
        resp = await client.post("/stac/search", json={"limit": 10001})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        # GeoLens uses RFC 7807 problem-details shape — `detail` is a string
        # (e.g. "body.limit: Input should be less than or equal to 1000"),
        # not FastAPI's default list-of-errors structure.
        detail = str(body.get("detail", "")).lower()
        assert "limit" in detail and (
            "less than or equal" in detail or "le " in detail or "<=" in detail
        ), f"422 detail did not name limit/le bound: {body}"

    async def test_post_search_negative_offset_rejected(self, client: AsyncClient):
        """offset=-1 must be rejected by Pydantic 422 (not silently clamped)."""
        resp = await client.post("/stac/search", json={"offset": -1})
        assert resp.status_code == 422, resp.text

    async def test_post_search_zero_limit_rejected(self, client: AsyncClient):
        """limit=0 must be rejected by Pydantic 422 (ge=1)."""
        resp = await client.post("/stac/search", json={"limit": 0})
        assert resp.status_code == 422, resp.text

    async def test_post_search_limit_within_bounds_accepted(self, client: AsyncClient):
        """limit=200 (within 1-1000) must pass schema validation."""
        resp = await client.post("/stac/search", json={"limit": 200, "offset": 0})
        # 200 OK or any non-422 — the schema layer accepts.
        assert resp.status_code != 422, resp.text
