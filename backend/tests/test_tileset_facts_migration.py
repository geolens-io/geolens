"""Migration 0067 adds the three nullable tileset fact columns and its downgrade drops them."""

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
    ("tileset_bounding_volume", "character varying", 10, "YES"),
    ("tileset_geometric_error", "double precision", None, "YES"),
    ("tileset_version", "character varying", 8, "YES"),
]


async def _tileset_columns() -> list[tuple]:
    rows = await fresh_query(
        "SELECT column_name, data_type, character_maximum_length, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'catalog' "
        "AND table_name = 'datasets' AND column_name LIKE 'tileset\\_%' "
        "ORDER BY column_name"
    )
    return [tuple(row) for row in rows]


async def test_the_round_trip_drops_and_restores_the_tileset_columns() -> None:
    """Down to 0066 the columns are gone; back at head they are nullable again."""
    assert await _tileset_columns() == _COLUMNS
    try:
        down = run_alembic("downgrade", "0066_tileset_asset_key")
        assert down.returncode == 0, down.stderr
        assert await _tileset_columns() == []
    finally:
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
    assert await _tileset_columns() == _COLUMNS
