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
from app.datasets.models import Dataset, Record, RecordKeyword

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
    """Next link preserves bbox query parameter."""
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
