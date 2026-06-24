"""Pagination stability tests for /search/datasets.

Regression coverage for B2: the standard (non-RRF) sort path used 6 ORDER BY
branches, none of which had a unique tiebreaker. When many rows tie on the
sort key (same record_status, updated_at, created_at, title) OFFSET/LIMIT
returned a non-stable order, so paging the full result set produced duplicate
records on some pages and dropped others.

The fix appends Record.id (the UUID PK) as a deterministic final tiebreaker to
every branch. These tests seed > limit datasets with identical sort keys, page
the whole set at a small limit, and assert: no dupes, no drops, full coverage,
and an identical order across two independent runs.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tied_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keyword_tag: str,
    fixed_ts,
) -> Dataset:
    """Insert a Record + Dataset whose sort keys are identical to its siblings.

    title, record_status, created_at and updated_at are all pinned to the same
    value so the only thing distinguishing rows is the UUID PK tiebreaker.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Description for {name}",
        visibility="public",
        record_status="published",
        created_by=created_by,
        theme_category=[keyword_tag],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()

    # Pin created_at / updated_at to identical timestamps so every row ties.
    await session.execute(
        update(Record)
        .where(Record.id == record.id)
        .values(created_at=fixed_ts, updated_at=fixed_ts)
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _page_all_ids(
    client: AsyncClient,
    headers: dict,
    *,
    sort_by: str,
    keyword_tag: str,
    page_size: int,
) -> list[str]:
    """Walk every page of a search and collect the dataset feature ids in order."""
    all_ids: list[str] = []
    offset = 0
    # Use the theme_category token as q so only our seeded datasets match.
    while True:
        resp = await client.get(
            "/search/datasets/",
            params={
                "q": keyword_tag,
                "sort_by": sort_by,
                "limit": page_size,
                "offset": offset,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        page_ids = [
            f["id"]
            for f in data["features"]
            if f["properties"].get("type") != "collection"
        ]
        all_ids.extend(page_ids)
        offset += page_size
        if offset >= data["numberMatched"]:
            break
        # Safety valve against an accidental infinite loop.
        if offset > data["numberMatched"] + page_size * 5:
            pytest.fail("pagination did not terminate")
    return all_ids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def tied_datasets(test_db_session):
    """Seed a pool of datasets that tie on every non-id sort key."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    keyword_tag = f"tiebreak{uuid.uuid4().hex[:8]}"
    fixed_ts = date(2024, 3, 14)
    datasets = []
    # 7 rows, all identical sort keys; page at limit=2 (4 pages).
    for _ in range(7):
        ds = await _create_tied_dataset(
            session,
            created_by=admin_id,
            name="Identical Tiebreak Dataset",
            keyword_tag=keyword_tag,
            fixed_ts=fixed_ts,
        )
        datasets.append(ds)
    return {"datasets": datasets, "keyword_tag": keyword_tag}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sort_by",
    ["relevance", "date_added", "last_updated", "title", "name"],
)
async def test_pagination_no_dupes_no_drops_across_branches(
    client: AsyncClient,
    admin_auth_header: dict,
    tied_datasets: dict,
    sort_by: str,
):
    """Paging tied rows yields every id exactly once for every sort branch."""
    expected = {str(ds.id) for ds in tied_datasets["datasets"]}
    keyword_tag = tied_datasets["keyword_tag"]

    paged = await _page_all_ids(
        client,
        admin_auth_header,
        sort_by=sort_by,
        keyword_tag=keyword_tag,
        page_size=2,
    )

    seen = [pid for pid in paged if pid in expected]
    # No duplicates across pages.
    assert len(seen) == len(set(seen)), f"duplicate ids paging sort_by={sort_by}"
    # Full coverage -- no dropped rows.
    assert set(seen) == expected, f"missing/extra ids paging sort_by={sort_by}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sort_by",
    ["relevance", "date_added", "last_updated", "title", "name"],
)
async def test_pagination_order_is_stable_across_runs(
    client: AsyncClient,
    admin_auth_header: dict,
    tied_datasets: dict,
    sort_by: str,
):
    """The full paged order is identical across two independent runs."""
    expected = {str(ds.id) for ds in tied_datasets["datasets"]}
    keyword_tag = tied_datasets["keyword_tag"]

    run1 = [
        pid
        for pid in await _page_all_ids(
            client,
            admin_auth_header,
            sort_by=sort_by,
            keyword_tag=keyword_tag,
            page_size=2,
        )
        if pid in expected
    ]
    run2 = [
        pid
        for pid in await _page_all_ids(
            client,
            admin_auth_header,
            sort_by=sort_by,
            keyword_tag=keyword_tag,
            page_size=2,
        )
        if pid in expected
    ]
    assert run1 == run2, f"unstable order across runs for sort_by={sort_by}"
