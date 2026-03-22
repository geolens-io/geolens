"""Tests for OGC datetime parsing and temporal overlap filtering on search."""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.auth.models import User
from app.datasets.models import Dataset, Record, RecordKeyword
from app.search.service import parse_ogc_datetime


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_search.py for isolation)
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_search_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keywords: list[str] | None = None,
    geometry_type: str = "MultiPolygon",
    srid: int = 4326,
    visibility: str = "public",
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
    description: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair with optional temporal extent."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        temporal_start=data_vintage_start,
        temporal_end=data_vintage_end,
    )
    session.add(record)
    await session.flush()

    for kw in keywords or []:
        session.add(
            RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
        )

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Unit tests for parse_ogc_datetime
# ---------------------------------------------------------------------------


def test_parse_single_instant():
    result = parse_ogc_datetime("2024-01-15")
    assert result == (date(2024, 1, 15), date(2024, 1, 15))


def test_parse_bounded_interval():
    result = parse_ogc_datetime("2024-01-01/2024-12-31")
    assert result == (date(2024, 1, 1), date(2024, 12, 31))


def test_parse_open_start():
    result = parse_ogc_datetime("../2024-12-31")
    assert result == (None, date(2024, 12, 31))


def test_parse_open_end():
    result = parse_ogc_datetime("2024-01-01/..")
    assert result == (date(2024, 1, 1), None)


def test_parse_full_datetime():
    result = parse_ogc_datetime("2024-01-15T00:00:00Z")
    assert result == (date(2024, 1, 15), date(2024, 1, 15))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def datetime_datasets(test_db_session):
    """Create datasets with different temporal extents for datetime tests."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    # Dataset spanning 2020-2022
    ds_2020 = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Historical Survey 2020-2022",
        data_vintage_start=date(2020, 1, 1),
        data_vintage_end=date(2022, 12, 31),
        description="Historical dataset spanning 2020 to 2022",
    )

    # Dataset spanning 2023-2025
    ds_2023 = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Current Survey 2023-2025",
        data_vintage_start=date(2023, 1, 1),
        data_vintage_end=date(2025, 12, 31),
        description="Current dataset spanning 2023 to 2025",
    )

    # Dataset with no temporal extent
    ds_none = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Timeless Reference Data",
        description="Reference dataset without temporal bounds",
    )

    return {"ds_2020": ds_2020, "ds_2023": ds_2023, "ds_none": ds_none}


# ---------------------------------------------------------------------------
# Integration tests for datetime filter on search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_datetime_overlap_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    datetime_datasets: dict,
):
    """Datetime interval 2021-01-01/2021-12-31 returns 2020-2022 dataset, not 2023-2025."""
    resp = await client.get(
        "/search/datasets",
        params={"datetime": "2021-01-01/2021-12-31", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(datetime_datasets["ds_2020"].id) in ids
    assert str(datetime_datasets["ds_2023"].id) not in ids


@pytest.mark.anyio
async def test_datetime_open_end(
    client: AsyncClient,
    admin_auth_header: dict,
    datetime_datasets: dict,
):
    """Datetime 2024-01-01/.. returns dataset 2023-2025."""
    resp = await client.get(
        "/search/datasets",
        params={"datetime": "2024-01-01/..", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(datetime_datasets["ds_2023"].id) in ids


@pytest.mark.anyio
async def test_datetime_single_instant(
    client: AsyncClient,
    admin_auth_header: dict,
    datetime_datasets: dict,
):
    """Datetime 2024-06-15 (instant) returns 2023-2025 but not 2020-2022."""
    resp = await client.get(
        "/search/datasets",
        params={"datetime": "2024-06-15", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(datetime_datasets["ds_2023"].id) in ids
    assert str(datetime_datasets["ds_2020"].id) not in ids


@pytest.mark.anyio
async def test_datetime_no_filter_returns_all(
    client: AsyncClient,
    admin_auth_header: dict,
    datetime_datasets: dict,
):
    """Search without datetime returns all datasets including temporal and non-temporal."""
    resp = await client.get(
        "/search/datasets",
        params={"limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(datetime_datasets["ds_2020"].id) in ids
    assert str(datetime_datasets["ds_2023"].id) in ids
    assert str(datetime_datasets["ds_none"].id) in ids
