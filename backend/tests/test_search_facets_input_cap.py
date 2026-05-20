"""Tests for max_length=1000 enforcement on /search/facets/?q= (SEC-S13 / Phase 1062-03).

/search/datasets/?q= already caps at 1000 chars via SearchQueryParams.q.
/search/facets/?q= previously had no length cap.  SEC-S13 closes the gap.

These tests do not require a seeded database: they test Pydantic validation
at the route parameter boundary, which fires before any DB query is executed.
The ``client`` fixture suffices (no DB session needed).
"""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_facets_q_rejects_1001_chars(client: AsyncClient):
    """GET /search/facets/?q=<1001 chars> must return HTTP 422.

    A 1001-character ``q`` exceeds the ``max_length=1000`` FastAPI/Pydantic
    constraint and must be rejected before any database query is issued.
    """
    resp = await client.get("/search/facets/", params={"q": "a" * 1001})
    assert resp.status_code == 422, (
        f"Expected 422 (max_length violation) for 1001-char q, got {resp.status_code}. "
        "Was max_length=1000 applied to the /search/facets/?q= Query param? "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.anyio
async def test_facets_q_accepts_1000_chars(client: AsyncClient):
    """GET /search/facets/?q=<1000 chars> must return HTTP 200.

    The boundary value (exactly 1000 chars) must still be accepted so the
    cap does not over-reject near-boundary legitimate queries.
    """
    resp = await client.get("/search/facets/", params={"q": "a" * 1000})
    assert resp.status_code == 200, (
        f"Expected 200 for 1000-char q (boundary), got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.anyio
async def test_facets_q_accepts_short_query(client: AsyncClient):
    """GET /search/facets/?q=test must return HTTP 200 (happy path regression)."""
    resp = await client.get("/search/facets/", params={"q": "test"})
    assert resp.status_code == 200, (
        f"Expected 200 for short q='test', got {resp.status_code}. "
        f"Body: {resp.text[:200]}"
    )
