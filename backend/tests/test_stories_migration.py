"""Migration 0095 adds stories and the maps their scenes use."""

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

_BELOW = "0094_dataset_version_columns"


@pytest.fixture
async def story_on_map():
    """A story whose scene uses one map, both without a tenant."""
    story_id, map_id = uuid.uuid4(), uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.maps (id, name) VALUES (:id, 'Scene map')", {"id": map_id}
    )
    await fresh_query(
        "INSERT INTO catalog.stories (id, title, draft) "
        "VALUES (:id, 'Story', CAST('{\"version\": 1, \"chapters\": []}' AS jsonb))",
        {"id": story_id},
    )
    await fresh_query(
        "INSERT INTO catalog.story_maps (story_id, map_id) VALUES (:s, :m)",
        {"s": story_id, "m": map_id},
    )
    yield story_id, map_id
    run_alembic("upgrade", "head")
    await fresh_query("DELETE FROM catalog.stories WHERE id = :id", {"id": story_id})
    await fresh_query("DELETE FROM catalog.maps WHERE id = :id", {"id": map_id})


async def test_a_downgrade_drops_the_tables_and_an_upgrade_restores_them(story_on_map):
    down = run_alembic("downgrade", _BELOW)

    assert down.returncode == 0, down.stderr
    assert await fresh_query("SELECT to_regclass('catalog.stories')") == [(None,)]

    up = run_alembic("upgrade", "head")

    assert up.returncode == 0, up.stderr
    policies = await fresh_query(
        "SELECT policyname FROM pg_policies WHERE schemaname = 'catalog' "
        "AND tablename IN ('stories', 'story_maps') ORDER BY policyname"
    )
    assert policies == [
        ("tenant_isolation_stories",),
        ("tenant_isolation_story_maps",),
    ]


async def test_deleting_the_map_removes_only_its_story_map_row(story_on_map):
    story_id, map_id = story_on_map
    await fresh_query("DELETE FROM catalog.maps WHERE id = :id", {"id": map_id})
    assert await fresh_query(
        "SELECT count(*) FROM catalog.story_maps WHERE story_id = :id", {"id": story_id}
    ) == [(0,)]
    assert await fresh_query(
        "SELECT count(*) FROM catalog.stories WHERE id = :id", {"id": story_id}
    ) == [(1,)]


async def test_the_trigger_refuses_a_map_from_another_tenant(story_on_map):
    story_id, _ = story_on_map
    foreign = uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.maps (id, name, tenant_id) "
        "VALUES (:id, 'Foreign', CAST(:tenant AS uuid))",
        {"id": foreign, "tenant": str(uuid.uuid4())},
    )
    try:
        with pytest.raises(Exception, match="does not match story tenant"):
            await fresh_query(
                "INSERT INTO catalog.story_maps (story_id, map_id) VALUES (:s, :m)",
                {"s": story_id, "m": foreign},
            )
    finally:
        await fresh_query("DELETE FROM catalog.maps WHERE id = :id", {"id": foreign})
