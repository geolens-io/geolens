"""Migration 0068 adds the two nullable tileset contents columns and its downgrade drops them."""

from __future__ import annotations

import pytest

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)

pytestmark = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)

_COLUMNS = [
    ("tileset_content_types", "ARRAY", "_text", "YES"),
    ("tileset_extensions_required", "ARRAY", "_text", "YES"),
]


async def _contents_columns() -> list[tuple]:
    rows = await fresh_query(
        "SELECT column_name, data_type, udt_name, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'catalog' "
        "AND table_name = 'datasets' AND column_name IN "
        "('tileset_content_types', 'tileset_extensions_required') "
        "ORDER BY column_name"
    )
    return [tuple(row) for row in rows]


async def test_the_round_trip_drops_and_restores_the_contents_columns() -> None:
    """Down to 0067 the columns are gone; back at head they are nullable again."""
    assert await _contents_columns() == _COLUMNS
    try:
        down = run_alembic("downgrade", "0067_tileset_facts")
        assert down.returncode == 0, down.stderr
        assert await _contents_columns() == []
    finally:
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
    assert await _contents_columns() == _COLUMNS
