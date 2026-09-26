"""Migrations 0070 and 0071 admit the point cloud values; each downgrade refuses while a row uses one."""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query as _fresh_query,
    run_alembic as _run_alembic,
)

pytestmark = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)

_PREVIOUS = "0069_backfill_raster_dataset_assets"
_POINTCLOUD_REVISION = "0070_pointcloud_record_type"
_TITLE_PREFIX = "migration-0070-"


async def _insert_record(record_type: str) -> str:
    rows = await _fresh_query(
        "INSERT INTO catalog.records (title, record_type, visibility, record_status) "
        "VALUES (:title, :record_type, 'private', 'draft') RETURNING id",
        {"title": f"{_TITLE_PREFIX}{uuid.uuid4().hex[:8]}", "record_type": record_type},
    )
    return str(rows[0][0])


async def _insert_dataset(record_id: str, source_format: str) -> None:
    await _fresh_query(
        "INSERT INTO catalog.datasets (record_id, table_name, source_format) "
        "VALUES (CAST(:record_id AS uuid), :table_name, :source_format)",
        {
            "record_id": record_id,
            "table_name": f"m0070_{uuid.uuid4().hex[:12]}",
            "source_format": source_format,
        },
    )


async def _insert_pointcloud_facts(record_id: str) -> None:
    await _fresh_query(
        "UPDATE catalog.datasets SET pointcloud_point_count = 39025611, "
        "pointcloud_point_format = 6, pointcloud_vertical_crs = 'NGF-IGN69 height' "
        "WHERE record_id = CAST(:record_id AS uuid)",
        {"record_id": record_id},
    )


async def _pointcloud_facts(record_id: str) -> tuple:
    rows = await _fresh_query(
        "SELECT pointcloud_point_count, pointcloud_point_format, "
        "pointcloud_vertical_crs FROM catalog.datasets "
        "WHERE record_id = CAST(:record_id AS uuid)",
        {"record_id": record_id},
    )
    return tuple(rows[0])


async def _insert_pointcloud_asset(record_id: str) -> None:
    await _fresh_query(
        "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
        "SELECT id, 'pointcloud', 'pointclouds/' || id || '/a1/data.copc.laz', 1 "
        "FROM catalog.datasets WHERE record_id = CAST(:record_id AS uuid)",
        {"record_id": record_id},
    )


def _current_revision() -> list[str]:
    # stdout also carries log lines; a revision line is the id, then "(head)".
    return re.findall(r"^(\w+)(?: \(head\))?$", _run_alembic("current").stdout, re.M)


async def _remove_rows_and_restore_head() -> None:
    await _fresh_query(
        "DELETE FROM catalog.records WHERE title LIKE :p", {"p": f"{_TITLE_PREFIX}%"}
    )
    restored = _run_alembic("upgrade", "heads")
    assert restored.returncode == 0, restored.stderr


@pytest.mark.parametrize(
    ("record_type", "source_format", "constraint"),
    [
        ("pointcloud_dataset", None, "chk_records_record_type"),
        ("vector_dataset", "copc", "chk_datasets_source_format"),
    ],
)
async def test_downgrade_refuses_while_a_row_uses_a_new_value(
    record_type: str, source_format: str | None, constraint: str
) -> None:
    """The downgrade fails on the constraint the row would violate and stays at head."""
    try:
        record_id = await _insert_record(record_type)
        if source_format is not None:
            await _insert_dataset(record_id, source_format)
        head = _current_revision()
        assert head, "alembic current printed no revision"

        refused = _run_alembic("downgrade", _PREVIOUS)

        assert refused.returncode != 0
        assert constraint in refused.stderr
        assert _current_revision() == head
    finally:
        await _remove_rows_and_restore_head()


@pytest.mark.parametrize("with_asset", [True, False], ids=["published", "assetless"])
async def test_the_facts_downgrade_refuses_while_a_point_cloud_dataset_exists(
    with_asset: bool,
) -> None:
    """The 0071 downgrade refuses while any point cloud dataset exists, and its facts survive."""
    try:
        record_id = await _insert_record("pointcloud_dataset")
        await _insert_dataset(record_id, "copc")
        await _insert_pointcloud_facts(record_id)
        if with_asset:
            await _insert_pointcloud_asset(record_id)
        head = _current_revision()
        assert head, "alembic current printed no revision"

        refused = _run_alembic("downgrade", _POINTCLOUD_REVISION)

        assert refused.returncode != 0
        assert "1 point cloud dataset(s) exist" in refused.stderr
        assert _current_revision() == head
        assert await _pointcloud_facts(record_id) == (
            39025611,
            6,
            "NGF-IGN69 height",
        )
    finally:
        await _remove_rows_and_restore_head()


async def test_round_trip_closes_and_reopens_the_vocabulary() -> None:
    """With no row using a new value, 0070 downgrades and upgrades cleanly."""
    try:
        down = _run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        with pytest.raises(IntegrityError, match="chk_records_record_type"):
            await _insert_record("pointcloud_dataset")
        tileset = await _insert_record("tiles3d_dataset")
        await _insert_dataset(tileset, "3dtiles")

        up = _run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        record_id = await _insert_record("pointcloud_dataset")
        await _insert_dataset(record_id, "copc")
        await _insert_pointcloud_asset(record_id)
    finally:
        await _remove_rows_and_restore_head()
