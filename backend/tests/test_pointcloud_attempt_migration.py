"""Migration 0074 copies a point cloud's attempt from a well-formed pointer row, and its downgrade drops the column."""

from __future__ import annotations

import uuid

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

_PREVIOUS = "0073_raster_crs_facts"
_TITLE_PREFIX = "migration-0074-"


async def _point_cloud(attempt: str, *, prefix_of: str | None = None) -> str:
    """A point cloud dataset whose pointer row names ``attempt``; returns the dataset id."""
    rows = await fresh_query(
        "INSERT INTO catalog.records (title, record_type, visibility, record_status) "
        "VALUES (:title, 'pointcloud_dataset', 'private', 'draft') RETURNING id",
        {"title": f"{_TITLE_PREFIX}{uuid.uuid4().hex[:8]}"},
    )
    rows = await fresh_query(
        "INSERT INTO catalog.datasets (record_id, table_name, source_format) "
        "VALUES (:record_id, :table_name, 'copc') RETURNING id",
        {"record_id": rows[0][0], "table_name": f"m0074_{uuid.uuid4().hex[:12]}"},
    )
    dataset_id = str(rows[0][0])
    await fresh_query(
        "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
        "VALUES (CAST(:dataset_id AS uuid), 'pointcloud', :href, 1)",
        {
            "dataset_id": dataset_id,
            "href": f"pointclouds/{prefix_of or dataset_id}/{attempt}/data.copc.laz",
        },
    )
    return dataset_id


async def _attempt_of(dataset_id: str) -> uuid.UUID | None:
    rows = await fresh_query(
        "SELECT pointcloud_attempt_id FROM catalog.datasets WHERE id = CAST(:id AS uuid)",
        {"id": dataset_id},
    )
    return rows[0][0]


async def _remove_rows_and_restore_head() -> None:
    await fresh_query(
        "DELETE FROM catalog.records WHERE title LIKE :p", {"p": f"{_TITLE_PREFIX}%"}
    )
    restored = run_alembic("upgrade", "heads")
    assert restored.returncode == 0, restored.stderr


async def test_the_upgrade_copies_the_attempt_only_from_a_well_formed_pointer() -> None:
    """A pointer naming one of the dataset's attempt objects fills the column; any other shape leaves it null."""
    attempt = uuid.uuid4()
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        well_formed = await _point_cloud(str(attempt))
        malformed = [
            await _point_cloud("a1"),
            await _point_cloud(str(uuid.uuid4()).upper()),
            await _point_cloud(str(uuid.uuid4()), prefix_of=str(uuid.uuid4())),
        ]

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr

        assert await _attempt_of(well_formed) == attempt
        for dataset_id in malformed:
            assert await _attempt_of(dataset_id) is None
    finally:
        await _remove_rows_and_restore_head()


async def test_the_downgrade_drops_the_column_and_the_upgrade_refills_it() -> None:
    """0074 downgrades while a point cloud exists, and upgrading again restores its attempt."""
    attempt = uuid.uuid4()
    try:
        dataset_id = await _point_cloud(str(attempt))
        await fresh_query(
            "UPDATE catalog.datasets SET pointcloud_attempt_id = CAST(:attempt AS uuid) "
            "WHERE id = CAST(:id AS uuid)",
            {"attempt": str(attempt), "id": dataset_id},
        )

        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        columns = await fresh_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'catalog' AND table_name = 'datasets' "
            "AND column_name = 'pointcloud_attempt_id'"
        )
        assert list(columns) == []

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        assert await _attempt_of(dataset_id) == attempt
    finally:
        await _remove_rows_and_restore_head()
