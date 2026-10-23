"""Migration 0093 adds map group grants and the restricted map visibility."""

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
    reason="OSS migration roundtrip; multi-head under an enterprise overlay.",
)

_BELOW = "0092_dataset_group_grant_tenant"


@pytest.fixture
async def restricted_map():
    """A restricted map shared with one group."""
    map_id, group_id = uuid.uuid4(), uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.groups (id, name) VALUES (:id, :name)",
        {"id": group_id, "name": f"mig-{group_id.hex[:10]}"},
    )
    await fresh_query(
        "INSERT INTO catalog.maps (id, name, visibility) "
        "VALUES (:id, 'Restricted', 'restricted')",
        {"id": map_id},
    )
    await fresh_query(
        "INSERT INTO catalog.map_group_grants (map_id, group_id) VALUES (:m, :g)",
        {"m": map_id, "g": group_id},
    )
    yield map_id, group_id
    run_alembic("upgrade", "head")
    await fresh_query("DELETE FROM catalog.maps WHERE id = :id", {"id": map_id})
    await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": group_id})


async def _visibility(map_id) -> str:
    rows = await fresh_query(
        "SELECT visibility FROM catalog.maps WHERE id = :id", {"id": map_id}
    )
    return rows[0][0]


async def test_a_downgrade_makes_restricted_maps_private_and_an_upgrade_restores_the_table(
    restricted_map,
):
    map_id, group_id = restricted_map

    down = run_alembic("downgrade", _BELOW)

    assert down.returncode == 0, down.stderr
    assert await _visibility(map_id) == "private"
    assert await fresh_query("SELECT to_regclass('catalog.map_group_grants')") == [
        (None,)
    ]

    up = run_alembic("upgrade", "head")

    assert up.returncode == 0, up.stderr
    await fresh_query(
        "UPDATE catalog.maps SET visibility = 'restricted' WHERE id = :id",
        {"id": map_id},
    )
    await fresh_query(
        "INSERT INTO catalog.map_group_grants (map_id, group_id) VALUES (:m, :g)",
        {"m": map_id, "g": group_id},
    )
    assert await _visibility(map_id) == "restricted"
    policies = await fresh_query(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'catalog' "
        "AND policyname = 'tenant_isolation_map_group_grants'"
    )
    assert policies == [(1,)]


async def test_the_trigger_refuses_a_group_from_another_tenant(restricted_map):
    map_id, _ = restricted_map
    foreign = uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.groups (id, name, tenant_id) "
        "VALUES (:id, :name, CAST(:tenant AS uuid))",
        {"id": foreign, "name": f"mig-{foreign.hex[:10]}", "tenant": str(uuid.uuid4())},
    )
    try:
        with pytest.raises(Exception, match="does not match map tenant"):
            await fresh_query(
                "INSERT INTO catalog.map_group_grants (map_id, group_id) "
                "VALUES (:m, :g)",
                {"m": map_id, "g": foreign},
            )
    finally:
        await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": foreign})
