"""Tests for OGC pagination next/prev link relations.

Verifies:
  - Next link present when more results exist beyond current page
  - No next link on last page
  - Prev link present when offset > 0
  - No prev link on first page
  - Pagination links preserve query parameters (q, tags, bbox)
  - Following next links traverses full catalog without data loss
  - Prev link offset does not go negative
"""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    visibility: str = "public",
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    theme_category: list[str] | None = None,
    keywords: list[str] | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair for pagination tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=theme_category or ["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    if keywords:
        for kw in keywords:
            session.add(
                RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
            )
        await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


def _find_link(links: list[dict], rel: str) -> dict | None:
    """Find a link by rel value in a links list."""
    for link in links:
        if link["rel"] == rel:
            return link
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pagination_next_link_present_when_more_results(
    client: AsyncClient, test_db_session
):
    """Next link present when more items exist beyond current page."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(3):
        await _create_dataset(
            session, created_by=admin_id, name=f"pg-next-{prefix}-{i}"
        )

    resp = await client.get("/collections/datasets/items", params={"limit": 1})
    assert resp.status_code == 200
    data = resp.json()

    next_link = _find_link(data["links"], "next")
    assert next_link is not None, "Expected next link when more results exist"
    assert "offset=1" in next_link["href"]
    assert "limit=1" in next_link["href"]
    assert next_link["href"].startswith("http"), "Next link must be absolute URL"


@pytest.mark.anyio
async def test_pagination_no_next_link_on_last_page(
    client: AsyncClient, test_db_session
):
    """No next link when on the last page of results."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    # Ensure at least 1 dataset exists
    prefix = uuid.uuid4().hex[:6]
    await _create_dataset(session, created_by=admin_id, name=f"pg-last-{prefix}")

    # First, get total count
    resp = await client.get("/collections/datasets/items", params={"limit": 100})
    assert resp.status_code == 200
    data = resp.json()
    total = data["numberMatched"]

    # Request with offset that puts us at or past the last page
    resp2 = await client.get(
        "/collections/datasets/items",
        params={"offset": max(0, total - 1), "limit": 100},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    next_link = _find_link(data2["links"], "next")
    assert next_link is None, "Should not have next link on last page"


@pytest.mark.anyio
async def test_pagination_prev_link_present_when_offset_gt_0(
    client: AsyncClient, test_db_session
):
    """Prev link present when offset > 0."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(2):
        await _create_dataset(
            session, created_by=admin_id, name=f"pg-prev-{prefix}-{i}"
        )

    resp = await client.get(
        "/collections/datasets/items", params={"offset": 1, "limit": 1}
    )
    assert resp.status_code == 200
    data = resp.json()

    prev_link = _find_link(data["links"], "prev")
    assert prev_link is not None, "Expected previous link when offset > 0"
    assert "offset=0" in prev_link["href"]


@pytest.mark.anyio
async def test_pagination_no_prev_link_on_first_page(client: AsyncClient):
    """No prev link when on the first page (offset=0)."""
    resp = await client.get(
        "/collections/datasets/items", params={"offset": 0, "limit": 10}
    )
    assert resp.status_code == 200
    data = resp.json()

    prev_link = _find_link(data["links"], "prev")
    assert prev_link is None, "Should not have prev link on first page"


@pytest.mark.anyio
async def test_pagination_links_preserve_query_params(
    client: AsyncClient, test_db_session
):
    """Next link preserves q and tags query parameters."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(3):
        await _create_dataset(
            session,
            created_by=admin_id,
            name=f"pg-params-{prefix}-{i}",
            theme_category=["transportation"],
            keywords=["transportation"],
        )

    resp = await client.get(
        "/collections/datasets/items",
        params={"q": "test", "limit": 1, "keywords": "transportation"},
    )
    assert resp.status_code == 200
    data = resp.json()

    next_link = _find_link(data["links"], "next")
    # Only check if we actually got a next link (there may not be enough matching results)
    if next_link is not None:
        assert "q=test" in next_link["href"], "Next link must preserve q param"
        assert "keywords=transportation" in next_link["href"], (
            "Next link must preserve keywords param"
        )
    else:
        # If no next link, numberMatched must be <= limit
        assert data["numberMatched"] <= 1, (
            "Expected next link with multiple matching results"
        )


@pytest.mark.anyio
async def test_pagination_links_preserve_bbox(client: AsyncClient, test_db_session):
    """Self and next links preserve bbox query parameters."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(3):
        await _create_dataset(
            session, created_by=admin_id, name=f"pg-bbox-{prefix}-{i}"
        )

    resp = await client.get(
        "/collections/datasets/items",
        params={"bbox": "-180,-90,180,90", "limit": 1},
    )
    assert resp.status_code == 200
    data = resp.json()

    self_link = _find_link(data["links"], "self")
    assert self_link is not None
    self_qs = parse_qs(urlparse(self_link["href"]).query)
    assert self_qs["bbox"] == ["-180,-90,180,90"]
    assert self_qs["limit"] == ["1"]
    assert self_qs["offset"] == ["0"]

    next_link = _find_link(data["links"], "next")
    if next_link is not None:
        # bbox may be URL-encoded or not
        href = next_link["href"]
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        assert "bbox" in qs, "Next link must preserve bbox param"
        assert qs["bbox"][0] == "-180,-90,180,90"


@pytest.mark.anyio
async def test_pagination_follow_next_links_no_data_loss(
    client: AsyncClient, test_db_session
):
    """Following next links traverses full catalog without losing records."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(5):
        await _create_dataset(
            session, created_by=admin_id, name=f"pg-traverse-{prefix}-{i}"
        )

    # Start with limit=2, scoped to this test's datasets to avoid cross-test contamination
    resp = await client.get(
        "/collections/datasets/items", params={"limit": 2, "q": f"pg-traverse-{prefix}"}
    )
    assert resp.status_code == 200
    data = resp.json()

    total_expected = data["numberMatched"]
    collected_ids: set[str] = set()

    # Collect IDs from first page
    for feature in data["features"]:
        collected_ids.add(feature["id"])

    # Follow next links
    pages = 1
    max_pages = total_expected  # safety limit
    while pages < max_pages:
        next_link = _find_link(data["links"], "next")
        if next_link is None:
            break
        # Extract path + query from the absolute URL
        parsed = urlparse(next_link["href"])
        path_and_query = parsed.path
        if parsed.query:
            path_and_query += "?" + parsed.query

        resp = await client.get(path_and_query)
        assert resp.status_code == 200
        data = resp.json()

        for feature in data["features"]:
            collected_ids.add(feature["id"])
        pages += 1

    assert len(collected_ids) == total_expected, (
        f"Collected {len(collected_ids)} unique IDs but numberMatched was {total_expected}"
    )


@pytest.mark.anyio
async def test_pagination_prev_offset_does_not_go_negative(
    client: AsyncClient, test_db_session
):
    """Prev link offset is clamped to 0, never negative."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    prefix = uuid.uuid4().hex[:6]
    for i in range(3):
        await _create_dataset(
            session, created_by=admin_id, name=f"pg-nonneg-{prefix}-{i}"
        )

    # offset=1 with limit=5 means prev offset should be max(0, 1-5) = 0
    resp = await client.get(
        "/collections/datasets/items", params={"offset": 1, "limit": 5}
    )
    assert resp.status_code == 200
    data = resp.json()

    prev_link = _find_link(data["links"], "prev")
    assert prev_link is not None, "Expected previous link when offset > 0"
    parsed = urlparse(prev_link["href"])
    qs = parse_qs(parsed.query)
    offset_val = int(qs["offset"][0])
    assert offset_val == 0, f"Prev offset should be 0, got {offset_val}"
    assert offset_val >= 0, "Prev offset must not be negative"


# ---------------------------------------------------------------------------
# Items page-size ceiling: admin-configurable, clamped not rejected (#665/#666)
# ---------------------------------------------------------------------------
#
# These target the per-dataset feature route (`/collections/{id}/items`), whose
# `limit` ceiling is the `ogc_items_max_page_size` PersistentConfig knob. Per
# OGC API Features Core /req/core/fc-limit-response-1(C) an over-ceiling limit
# is clamped to the maximum, never rejected. The feature-table helpers live in
# test_ogc_features.py; reuse them rather than duplicate the PostGIS DDL.
import app.standards.ogc.router as _ogc_router  # noqa: E402
from app.core.persistent_config import _DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE  # noqa: E402
from tests.test_ogc_features import (  # noqa: E402
    _cleanup_table,
    _create_test_table_and_dataset,
)


def _self_limit(data: dict) -> int:
    """Extract the echoed `limit` query param from the response's self link."""
    self_link = _find_link(data["links"], "self")
    assert self_link is not None, "Expected a self link"
    return int(parse_qs(urlparse(self_link["href"]).query)["limit"][0])


@pytest.mark.anyio
async def test_items_limit_at_default_ceiling_accepted(
    client: AsyncClient, test_db_session
):
    """A limit exactly at the default ceiling is accepted (no 4xx)."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, visibility="public", with_features=3
    )
    try:
        resp = await client.get(
            f"/collections/{dataset.id}/items",
            params={"limit": _DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["numberReturned"] == 3
        assert _self_limit(data) == _DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE
    finally:
        await _cleanup_table(test_db_session, dataset.table_name)


@pytest.mark.anyio
async def test_items_limit_above_ceiling_clamped_not_rejected(
    client: AsyncClient, test_db_session
):
    """A limit above the ceiling is clamped to it, not rejected with 400/422."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, visibility="public", with_features=5
    )
    try:
        over = _DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE * 5
        resp = await client.get(
            f"/collections/{dataset.id}/items", params={"limit": over}
        )
        # OGC /req/core/fc-limit-response-1(C): clamp, do not error.
        assert resp.status_code == 200
        data = resp.json()
        assert data["numberReturned"] == 5
        # The echoed self link carries the clamped ceiling, not the request value.
        assert _self_limit(data) == _DEFAULT_OGC_ITEMS_MAX_PAGE_SIZE
    finally:
        await _cleanup_table(test_db_session, dataset.table_name)


@pytest.mark.anyio
async def test_items_limit_clamped_to_configured_ceiling(
    client: AsyncClient, test_db_session, monkeypatch
):
    """A non-default configured ceiling is honored: the page is clamped to it."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, visibility="public", with_features=5
    )

    async def _fake_ceiling(_db):
        return 3

    monkeypatch.setattr(_ogc_router.OGC_ITEMS_MAX_PAGE_SIZE, "get", _fake_ceiling)
    try:
        resp = await client.get(
            f"/collections/{dataset.id}/items", params={"limit": 100}
        )
        assert resp.status_code == 200
        data = resp.json()
        # 5 features available, ceiling 3 -> clamped page of 3, more remain.
        assert data["numberReturned"] == 3
        assert data["numberMatched"] == 5
        assert _self_limit(data) == 3
        assert _find_link(data["links"], "next") is not None
    finally:
        await _cleanup_table(test_db_session, dataset.table_name)
