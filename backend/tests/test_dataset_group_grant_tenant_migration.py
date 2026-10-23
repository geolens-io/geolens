"""Migration 0092 puts dataset group grants inside the tenant boundary."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)
from tests.factories import get_user_id
from tests.test_tile_signature_revocation_1963 import _make_vector

pytestmark = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration roundtrip; multi-head under an enterprise overlay.",
)

_BELOW = "0091_dataset_group_grants"


@pytest.fixture
async def grant_seed(test_db_session):
    """A dataset and a group; the test decides the group's tenant."""
    dataset = await _make_vector(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        visibility="restricted",
    )
    dataset_id, table = dataset.id, dataset.table_name
    group_id = uuid.uuid4()
    yield dataset_id, group_id
    run_alembic("upgrade", "head")
    await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": group_id})
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


async def _seed_grant(dataset_id, group_id, *, group_tenant: str | None) -> None:
    await fresh_query(
        "INSERT INTO catalog.groups (id, name, tenant_id) "
        "VALUES (:id, :name, CAST(:tenant AS uuid))",
        {"id": group_id, "name": f"mig-{group_id.hex[:10]}", "tenant": group_tenant},
    )
    await fresh_query(
        "INSERT INTO catalog.dataset_group_grants (dataset_id, group_id) "
        "VALUES (:d, :g)",
        {"d": dataset_id, "g": group_id},
    )


async def _grant_columns() -> set[str]:
    rows = await fresh_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'catalog' AND table_name = 'dataset_group_grants'"
    )
    return {row[0] for row in rows}


async def test_a_roundtrip_keeps_grants_and_restores_the_boundary(grant_seed):
    dataset_id, group_id = grant_seed
    down = run_alembic("downgrade", _BELOW)
    assert down.returncode == 0, down.stderr
    assert "tenant_id" not in await _grant_columns()
    await _seed_grant(dataset_id, group_id, group_tenant=None)

    up = run_alembic("upgrade", "head")

    assert up.returncode == 0, up.stderr
    assert "tenant_id" in await _grant_columns()
    grants = await fresh_query(
        "SELECT group_id FROM catalog.dataset_group_grants WHERE dataset_id = :d",
        {"d": dataset_id},
    )
    assert grants == [(group_id,)]
    policies = await fresh_query(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'catalog' "
        "AND policyname = 'tenant_isolation_dataset_group_grants'"
    )
    assert policies == [(1,)]


async def test_upgrade_refuses_a_grant_to_another_tenants_group(grant_seed):
    dataset_id, group_id = grant_seed
    down = run_alembic("downgrade", _BELOW)
    assert down.returncode == 0, down.stderr
    await _seed_grant(dataset_id, group_id, group_tenant=str(uuid.uuid4()))

    refused = run_alembic("upgrade", "head")

    assert refused.returncode != 0
    assert "groups from another tenant" in refused.stderr
    await fresh_query(
        "DELETE FROM catalog.dataset_group_grants WHERE group_id = :g",
        {"g": group_id},
    )
