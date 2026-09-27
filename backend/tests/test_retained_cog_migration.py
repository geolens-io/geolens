"""Migration 0075 admits the retained_cog key; its downgrade refuses while a row uses it."""

from __future__ import annotations

import re
import uuid

import pytest

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query as _fresh_query,
    run_alembic as _run_alembic,
)

pytestmark = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)

_PREVIOUS = "0074_pointcloud_attempt_id"
_TITLE_PREFIX = "migration-0075-"


async def _dataset_with_retained_cog() -> None:
    record = await _fresh_query(
        "INSERT INTO catalog.records (title, record_type, visibility, record_status) "
        "VALUES (:title, 'raster_dataset', 'private', 'draft') RETURNING id",
        {"title": f"{_TITLE_PREFIX}{uuid.uuid4().hex[:8]}"},
    )
    dataset = await _fresh_query(
        "INSERT INTO catalog.datasets (record_id, table_name) "
        "VALUES (:record_id, :table_name) RETURNING id",
        {"record_id": record[0][0], "table_name": f"m0075_{uuid.uuid4().hex[:12]}"},
    )
    await _fresh_query(
        "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
        "VALUES (:id, :key, 'rasters/kept/source.cog.tif', 1)",
        {"id": dataset[0][0], "key": f"retained_cog:{uuid.uuid4()}"},
    )


def _current_revision() -> list[str]:
    return re.findall(r"^(\w+)(?: \(head\))?$", _run_alembic("current").stdout, re.M)


async def _remove_rows_and_restore_head() -> None:
    await _fresh_query(
        "DELETE FROM catalog.records WHERE title LIKE :p", {"p": f"{_TITLE_PREFIX}%"}
    )
    restored = _run_alembic("upgrade", "heads")
    assert restored.returncode == 0, restored.stderr


async def test_the_downgrade_refuses_while_a_kept_cog_is_charged() -> None:
    """The row is the only pointer to its kept COG, so the downgrade keeps it and fails."""
    try:
        await _dataset_with_retained_cog()
        head = _current_revision()
        assert head, "alembic current printed no revision"

        refused = _run_alembic("downgrade", _PREVIOUS)

        assert refused.returncode != 0
        assert "chk_dataset_assets_key" in refused.stderr
        assert _current_revision() == head
        rows = await _fresh_query(
            "SELECT count(*) FROM catalog.dataset_assets WHERE key LIKE 'retained_cog:%'"
        )
        assert rows[0][0] >= 1
    finally:
        await _remove_rows_and_restore_head()
