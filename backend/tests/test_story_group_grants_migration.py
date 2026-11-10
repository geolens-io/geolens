"""Migration 0099 adds story group grants."""

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

_BELOW = "0097_story_assets"


@pytest.fixture
async def restricted_story():
    """A restricted story shared with one group."""
    story_id, group_id = uuid.uuid4(), uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.groups (id, name) VALUES (:id, :name)",
        {"id": group_id, "name": f"mig-{group_id.hex[:10]}"},
    )
    await fresh_query(
        "INSERT INTO catalog.stories (id, title, visibility, draft) "
        "VALUES (:id, 'Story', 'restricted', "
        'CAST(\'{"version": 1, "chapters": []}\' AS jsonb))',
        {"id": story_id},
    )
    await fresh_query(
        "INSERT INTO catalog.story_group_grants (story_id, group_id) VALUES (:s, :g)",
        {"s": story_id, "g": group_id},
    )
    yield story_id, group_id
    run_alembic("upgrade", "head")
    await fresh_query("DELETE FROM catalog.stories WHERE id = :id", {"id": story_id})
    await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": group_id})


async def _visibility(story_id) -> str:
    rows = await fresh_query(
        "SELECT visibility FROM catalog.stories WHERE id = :id", {"id": story_id}
    )
    return rows[0][0]


async def test_a_downgrade_makes_restricted_stories_private_and_an_upgrade_restores_the_table(
    restricted_story,
):
    story_id, group_id = restricted_story

    down = run_alembic("downgrade", _BELOW)

    assert down.returncode == 0, down.stderr
    assert await _visibility(story_id) == "private"
    assert await fresh_query("SELECT to_regclass('catalog.story_group_grants')") == [
        (None,)
    ]

    up = run_alembic("upgrade", "head")

    assert up.returncode == 0, up.stderr
    await fresh_query(
        "INSERT INTO catalog.story_group_grants (story_id, group_id) VALUES (:s, :g)",
        {"s": story_id, "g": group_id},
    )
    policies = await fresh_query(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'catalog' "
        "AND policyname = 'tenant_isolation_story_group_grants'"
    )
    assert policies == [(1,)]


async def test_the_trigger_refuses_a_group_from_another_tenant(restricted_story):
    story_id, _ = restricted_story
    foreign = uuid.uuid4()
    await fresh_query(
        "INSERT INTO catalog.groups (id, name, tenant_id) "
        "VALUES (:id, :name, CAST(:tenant AS uuid))",
        {"id": foreign, "name": f"mig-{foreign.hex[:10]}", "tenant": str(uuid.uuid4())},
    )
    try:
        with pytest.raises(Exception, match="does not match story tenant"):
            await fresh_query(
                "INSERT INTO catalog.story_group_grants (story_id, group_id) "
                "VALUES (:s, :g)",
                {"s": story_id, "g": foreign},
            )
    finally:
        await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": foreign})
