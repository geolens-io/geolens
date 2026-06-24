"""Tests for stddev in get_column_stats (v1041 ENH-04).

The data-driven "Standard Deviation" classification method needs the backend
column-stats endpoint to return sigma. These tests run against a real database.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.column_stats import get_column_stats
from tests.factories import create_dataset, get_user_id

TEST_TABLE_NAME = f"test_stddev_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def stddev_table(test_db_session):
    """Create a small test table with a numeric and a text column."""
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{TEST_TABLE_NAME} "
            "(gid serial PRIMARY KEY, label text, value integer)"
        )
    )
    # values 1..5: sample stddev = sqrt(2.5) ~= 1.5811
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{TEST_TABLE_NAME} (label, value) VALUES "
            "('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)"
        )
    )
    await test_db_session.execute(text(f"ANALYZE data.{TEST_TABLE_NAME}"))
    await test_db_session.commit()

    yield TEST_TABLE_NAME

    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{TEST_TABLE_NAME}"))
    await test_db_session.commit()


@pytest.fixture
async def empty_stddev_table(test_db_session):
    """Create an empty test table with a numeric column."""
    name = f"{TEST_TABLE_NAME}_empty"
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{name} "
            "(gid serial PRIMARY KEY, value integer)"
        )
    )
    await test_db_session.commit()

    yield name

    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{name}"))
    await test_db_session.commit()


async def test_get_column_stats_returns_numeric_stddev(test_db_session, stddev_table):
    """A numeric column returns a numeric (non-None) sample stddev."""
    stats = await get_column_stats(test_db_session, stddev_table, "value")

    assert "stddev" in stats
    assert isinstance(stats["stddev"], float)
    # sample stddev of 1..5 is sqrt(2.5) ~= 1.5811
    assert stats["stddev"] == pytest.approx(1.5811, abs=1e-3)


async def test_get_column_stats_stddev_none_for_empty_column(
    test_db_session, empty_stddev_table
):
    """An empty column (no rows) yields stddev=None, not an error."""
    stats = await get_column_stats(test_db_session, empty_stddev_table, "value")

    assert stats["count"] == 0
    assert stats["stddev"] is None


async def test_get_column_stats_text_column_is_categorical(
    test_db_session, stddev_table
):
    """B3: a text column returns a categorical summary, not a 500 (::numeric cast).

    Numeric aggregates are None, count/distinct_count are populated, and
    data_type is 'categorical' so the endpoint maps to a 200 ColumnStatsResponse.
    """
    stats = await get_column_stats(test_db_session, stddev_table, "label")

    assert stats["data_type"] == "categorical"
    assert stats["min"] is None
    assert stats["max"] is None
    assert stats["mean"] is None
    assert stats["stddev"] is None
    assert stats["quantiles"] == []
    # 5 distinct non-null labels ('a'..'e').
    assert stats["count"] == 5
    assert stats["distinct_count"] == 5


async def test_get_column_stats_numeric_column_has_no_categorical_marker(
    test_db_session, stddev_table
):
    """Regression: numeric columns keep the byte-identical numeric shape."""
    stats = await get_column_stats(test_db_session, stddev_table, "value")

    # data_type is only set for categorical columns; numeric stays null.
    assert stats.get("data_type") is None
    assert stats["min"] == 1.0
    assert stats["max"] == 5.0
    assert stats["count"] == 5
    assert stats["mean"] == pytest.approx(3.0)


async def test_get_column_stats_nonexistent_column_raises_value_error(
    test_db_session, stddev_table
):
    """B3: a missing column raises ValueError (endpoint maps to 400)."""
    with pytest.raises(ValueError):
        await get_column_stats(test_db_session, stddev_table, "no_such_col")


# ---------------------------------------------------------------------------
# TQ-5: HTTP-layer coverage for /datasets/{id}/columns/{col}/stats/
# The tests above exercise the domain function directly; these drive the
# endpoint so the ValueError->400 mapping and ColumnStatsResponse shape are
# also covered.
# ---------------------------------------------------------------------------


@pytest.fixture
async def stats_dataset(test_db_session):
    """A dataset backed by a real physical table with a numeric + text column."""
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"http_stats_{uuid.uuid4().hex[:8]}"
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Column Stats HTTP DS",
        table_name=table_name,
    )
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} "
            "(gid serial PRIMARY KEY, label text, value integer)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (label, value) VALUES "
            "('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)"
        )
    )
    await test_db_session.commit()

    yield dataset

    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


async def test_column_stats_endpoint_text_column_is_categorical(
    client: AsyncClient, admin_auth_header: dict, stats_dataset
):
    """GET on a text column returns 200 with categorical data_type + distinct_count."""
    resp = await client.get(
        f"/datasets/{stats_dataset.id}/columns/label/stats/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["data_type"] == "categorical"
    assert data["distinct_count"] == 5
    assert data["min"] is None
    assert data["max"] is None


async def test_column_stats_endpoint_numeric_column_has_min_max(
    client: AsyncClient, admin_auth_header: dict, stats_dataset
):
    """GET on a numeric column returns 200 with null data_type and min/max set."""
    resp = await client.get(
        f"/datasets/{stats_dataset.id}/columns/value/stats/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["data_type"] is None
    assert data["min"] == 1.0
    assert data["max"] == 5.0


async def test_column_stats_endpoint_nonexistent_column_returns_400(
    client: AsyncClient, admin_auth_header: dict, stats_dataset
):
    """GET on a missing column maps the domain ValueError to HTTP 400."""
    resp = await client.get(
        f"/datasets/{stats_dataset.id}/columns/no_such_col/stats/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 400, resp.text
