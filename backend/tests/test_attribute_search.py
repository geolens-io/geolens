"""Integration tests for search behavior after records table refactor.

After 86-01, search_vector lives on catalog.records with A/B/C weights
(title, summary, tags). Column names and sample values (formerly weight D
on datasets) are no longer indexed in the tsvector.

Tests verify:
  - Title-based search (weight A) works via Record.search_vector
  - Summary-based search (weight B) works
  - Tag-based search (weight C) works
  - Column names are NOT matched by full-text search (intentional)

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (search_vector on records)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    column_info: list[dict] | None = None,
    sample_values: dict | None = None,
    description: str | None = None,
    theme_category: list[str] | None = None,
    visibility: str = "public",
) -> Dataset:
    """Insert a Record + Dataset pair with optional column_info and sample_values."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        theme_category=theme_category if theme_category is not None else [],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
        column_info=column_info if column_info is not None else [],
        sample_values=sample_values if sample_values is not None else {},
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_by_title(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a word in the title returns the dataset (weight A)."""
    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Water Infrastructure Dataset",
    )

    resp = await client.get(
        "/search/datasets",
        params={"q": "water infrastructure", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] >= 1
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_search_by_summary(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a word in the summary returns the dataset (weight B)."""
    admin_id = await _get_user_id(test_db_session, "admin")
    unique = uuid.uuid4().hex[:8]
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Generic Dataset {unique}",
        description=f"Hydrological measurements for {unique} watershed",
    )

    resp = await client.get(
        "/search/datasets",
        params={"q": f"hydrological {unique}", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] >= 1
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_search_by_tag(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a tag returns the dataset (weight C)."""
    admin_id = await _get_user_id(test_db_session, "admin")
    unique_tag = f"hydrology{uuid.uuid4().hex[:6]}"
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Tagged Dataset",
        theme_category=[unique_tag],
    )

    resp = await client.get(
        "/search/datasets",
        params={"q": unique_tag, "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] >= 1
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_title_ranks_higher_than_summary(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A dataset with a term in the title ranks higher than one
    with the term only in the summary (weight A > weight B)."""
    admin_id = await _get_user_id(test_db_session, "admin")
    unique = uuid.uuid4().hex[:8]

    # This one has the term in the title (weight A)
    ds_title = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Population Data {unique}",
        description="Demographic statistics",
    )

    # This one has the term only in the summary (weight B)
    ds_summary = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Geography Dataset {unique}",
        description=f"Contains population estimates for {unique}",
    )

    resp = await client.get(
        "/search/datasets",
        params={"q": f"population {unique}", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds_title.id) in ids
    assert str(ds_summary.id) in ids

    # Title match should rank before summary-only match
    title_idx = ids.index(str(ds_title.id))
    summary_idx = ids.index(str(ds_summary.id))
    assert title_idx < summary_idx, (
        "Dataset with term in title should rank higher than "
        "dataset with term only in summary"
    )


@pytest.mark.anyio
async def test_column_names_not_searchable_via_fts(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Column names are NOT indexed in search_vector after 86-01 refactor.

    After moving search_vector to records with A/B/C weights only,
    column names (which were at weight D on datasets) are no longer
    matched by full-text search.
    """
    admin_id = await _get_user_id(test_db_session, "admin")
    unique = uuid.uuid4().hex[:8]
    await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Plain Dataset {unique}",
        description=f"No special terms {unique}",
        column_info=[
            {"name": f"xyzcolumn{unique}", "type": "integer"},
        ],
    )

    resp = await client.get(
        "/search/datasets",
        params={"q": f"xyzcolumn{unique}", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Column name should NOT be found via FTS
    assert data["numberMatched"] == 0
