"""Migration 0070 admits the point cloud values; its downgrade refuses while a row uses one."""

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
    finally:
        await _remove_rows_and_restore_head()
