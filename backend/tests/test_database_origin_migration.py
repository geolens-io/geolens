"""Migration 0103 widens both checks and refuses to narrow them over database rows."""

from __future__ import annotations

import pytest

from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    normalize_database_origins,
    run_alembic,
)
from tests.factories import create_dataset, get_user_id

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        enterprise_migrations_present(),
        reason="OSS migration round-trip runs in the no-overlay migration job",
    ),
]

_BEFORE = "0102_dataset_assets_vrt_overview"


async def _check(name: str) -> str:
    rows = await fresh_query(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name",
        {"name": name},
    )
    return rows[0][0]


async def test_the_downgrade_refuses_while_a_database_dataset_exists(
    test_db_session,
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, source_format="database"
    )
    restamp(
        dataset,
        SourceBinding.database("gis", schema="dbo", table="t"),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await test_db_session.commit()
    try:
        down = run_alembic("downgrade", _BEFORE, normalize=False)
        assert down.returncode != 0
        assert (
            "RaiseError'>: Datasets or refresh runs with the database origin exist"
            in down.stderr
        )
        assert "'database'" in await _check("chk_datasets_source_format")
        assert "'database'" in await _check("chk_refresh_runs_origin_kind")
    finally:
        normalize_database_origins()
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr


async def test_the_round_trip_narrows_and_widens_both_checks(test_db_session) -> None:
    down = run_alembic("downgrade", _BEFORE)
    try:
        assert down.returncode == 0, down.stderr
        assert "'database'" not in await _check("chk_datasets_source_format")
        assert "'database'" not in await _check("chk_refresh_runs_origin_kind")
    finally:
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
    assert "'database'" in await _check("chk_datasets_source_format")
    assert "'database'" in await _check("chk_refresh_runs_origin_kind")
