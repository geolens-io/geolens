"""Tests for stddev in get_column_stats (v1041 ENH-04).

The data-driven "Standard Deviation" classification method needs the backend
column-stats endpoint to return sigma. These tests run against a real database.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from sqlalchemy import text

from app.modules.catalog.datasets.domain.column_stats import get_column_stats

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
