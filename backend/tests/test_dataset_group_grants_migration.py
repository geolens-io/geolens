"""Migration 0091 adds dataset group grants and tenant-scopes sharing groups."""

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

_BELOW = "0090_attribute_value_labels"


async def _seed_member(*, user_tenant: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    """A global group holding a fresh user; returns (group_id, user_id)."""
    group_id, user_id = uuid.uuid4(), uuid.uuid4()
    name = f"mig-{user_id.hex[:10]}"
    await fresh_query(
        "INSERT INTO catalog.users (id, username, email, status, is_active, "
        "token_version, auth_provider, tenant_id, created_at, updated_at) "
        "VALUES (:id, :name, :email, 'active', true, 1, 'local', "
        "CAST(:tenant AS uuid), now(), now())",
        {
            "id": user_id,
            "name": name,
            "email": f"{name}@mig.test",
            "tenant": user_tenant,
        },
    )
    await fresh_query(
        "INSERT INTO catalog.groups (id, name) VALUES (:id, :name)",
        {"id": group_id, "name": name},
    )
    await fresh_query(
        "INSERT INTO catalog.group_members (group_id, user_id) VALUES (:g, :u)",
        {"g": group_id, "u": user_id},
    )
    return group_id, user_id


async def _forget(group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await fresh_query("DELETE FROM catalog.groups WHERE id = :id", {"id": group_id})
    await fresh_query("DELETE FROM catalog.users WHERE id = :id", {"id": user_id})


async def _member_columns() -> set[str]:
    rows = await fresh_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'catalog' AND table_name = 'group_members'"
    )
    return {row[0] for row in rows}


async def test_a_roundtrip_keeps_members_and_restores_the_boundary():
    group_id, user_id = await _seed_member(user_tenant=None)
    try:
        down = run_alembic("downgrade", _BELOW)
        assert down.returncode == 0, down.stderr
        assert "tenant_id" not in await _member_columns()
        assert await fresh_query(
            "SELECT to_regclass('catalog.dataset_group_grants')"
        ) == [(None,)]

        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, up.stderr
        assert "tenant_id" in await _member_columns()
        members = await fresh_query(
            "SELECT user_id FROM catalog.group_members WHERE group_id = :g",
            {"g": group_id},
        )
        assert members == [(user_id,)]
        policies = await fresh_query(
            "SELECT tablename FROM pg_policies WHERE schemaname = 'catalog' "
            "AND policyname IN ('tenant_isolation_groups', "
            "'tenant_isolation_group_members')"
        )
        assert {row[0] for row in policies} == {"groups", "group_members"}
    finally:
        run_alembic("upgrade", "head")
        await _forget(group_id, user_id)


async def test_upgrade_refuses_a_member_from_another_tenant():
    down = run_alembic("downgrade", _BELOW)
    assert down.returncode == 0, down.stderr
    group_id, user_id = await _seed_member(user_tenant=str(uuid.uuid4()))
    try:
        refused = run_alembic("upgrade", "head")
        assert refused.returncode != 0
        assert "members from another tenant" in refused.stderr
    finally:
        await _forget(group_id, user_id)
        restored = run_alembic("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
