"""Sharing groups and their members stay inside one tenant."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.auth.models import Group, GroupMember

pytestmark = [pytest.mark.rls, pytest.mark.xdist_group("tenancy_global_state")]

_MISMATCH = "Group member tenant does not match group tenant"


@asynccontextmanager
async def _privileged(db_url: str):
    """A connection that bypasses RLS, as maintenance SQL would."""
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            yield conn
    finally:
        await engine.dispose()


@pytest.fixture
async def groups(multi_tenant_rls):
    """One group per tenant, each holding that tenant's seeded user."""
    ctx = multi_tenant_rls
    group_a, group_b = uuid.uuid4(), uuid.uuid4()
    async with _privileged(ctx.db_url) as conn:
        for group_id, tenant, user_id in (
            (group_a, ctx.tenant_a, ctx.user_a_id),
            (group_b, ctx.tenant_b, ctx.user_b_id),
        ):
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.groups (id, name, tenant_id) "
                    "VALUES (:id, 'Field crew', :tenant)"
                ),
                {"id": group_id, "tenant": tenant},
            )
            # No tenant_id: the validator takes it from the group.
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.group_members (group_id, user_id) "
                    "VALUES (:group_id, :user_id)"
                ),
                {"group_id": group_id, "user_id": user_id},
            )
    yield ctx, group_a, group_b
    async with _privileged(ctx.db_url) as conn:
        await conn.execute(
            sa.text("DELETE FROM catalog.groups WHERE id = ANY(:ids)"),
            {"ids": [group_a, group_b]},
        )


async def test_a_tenant_sees_only_its_own_groups_and_members(groups):
    ctx, group_a, group_b = groups

    async with ctx.tenant_session(ctx.tenant_a) as session:
        group_ids = set(await session.scalars(select(Group.id)))
        members = (
            await session.execute(select(GroupMember.group_id, GroupMember.user_id))
        ).all()

    assert group_a in group_ids
    assert group_b not in group_ids
    assert (group_a, uuid.UUID(ctx.user_a_id)) in members
    assert all(group_id != group_b for group_id, _ in members)


async def test_a_member_row_carries_its_groups_tenant(groups):
    ctx, group_a, _ = groups

    async with _privileged(ctx.db_url) as conn:
        tenant = await conn.scalar(
            sa.text("SELECT tenant_id FROM catalog.group_members WHERE group_id = :g"),
            {"g": group_a},
        )

    assert str(tenant) == ctx.tenant_a


@pytest.mark.parametrize("active_tenant", ["a", None])
async def test_privileged_sql_cannot_add_another_tenants_user(groups, active_tenant):
    ctx, group_a, _ = groups

    with pytest.raises(sa.exc.DBAPIError, match=_MISMATCH):
        async with _privileged(ctx.db_url) as conn:
            if active_tenant is not None:
                await conn.execute(
                    sa.text("SELECT set_config('app.current_tenant', :t, true)"),
                    {"t": ctx.tenant_a},
                )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.group_members (group_id, user_id) "
                    "VALUES (:group_id, :user_id)"
                ),
                {"group_id": group_a, "user_id": ctx.user_b_id},
            )


@asynccontextmanager
async def _reader_may_insert_members(db_url: str):
    async with _privileged(db_url) as conn:
        await conn.execute(
            sa.text("GRANT INSERT ON catalog.group_members TO geolens_reader")
        )
    try:
        yield
    finally:
        async with _privileged(db_url) as conn:
            await conn.execute(
                sa.text("REVOKE INSERT ON catalog.group_members FROM geolens_reader")
            )


async def test_a_tenant_session_cannot_add_another_tenants_user(groups):
    """Under RLS the other tenant's user is invisible, so the add reads as a
    missing user rather than reaching the tenant comparison."""
    ctx, group_a, _ = groups

    async with _reader_may_insert_members(ctx.db_url):
        with pytest.raises(sa.exc.DBAPIError, match="does not exist"):
            async with ctx.tenant_session(ctx.tenant_a) as session:
                await session.execute(
                    sa.insert(GroupMember).values(
                        group_id=group_a, user_id=uuid.UUID(ctx.user_b_id)
                    )
                )


async def test_a_tenant_session_cannot_add_to_another_tenants_group(groups):
    ctx, _, group_b = groups

    async with _reader_may_insert_members(ctx.db_url):
        with pytest.raises(sa.exc.DBAPIError, match="does not exist"):
            async with ctx.tenant_session(ctx.tenant_a) as session:
                await session.execute(
                    sa.insert(GroupMember).values(
                        group_id=group_b, user_id=uuid.UUID(ctx.user_a_id)
                    )
                )
