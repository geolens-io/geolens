"""Stories and the maps their scenes use stay inside one tenant."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.catalog.stories.models import Story, StoryMap

pytestmark = [pytest.mark.rls, pytest.mark.xdist_group("tenancy_global_state")]


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
async def stories(multi_tenant_rls):
    """One story per tenant, each with a scene on that tenant's map."""
    ctx = multi_tenant_rls
    ids = {
        tenant: (uuid.uuid4(), uuid.uuid4()) for tenant in (ctx.tenant_a, ctx.tenant_b)
    }
    async with _privileged(ctx.db_url) as conn:
        for tenant, (story_id, map_id) in ids.items():
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.maps (id, name, tenant_id) "
                    "VALUES (:id, 'Scene map', :tenant)"
                ),
                {"id": map_id, "tenant": tenant},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.stories (id, title, draft, tenant_id) "
                    "VALUES (:id, 'Story', "
                    'CAST(\'{"version": 1, "chapters": []}\' AS jsonb), :tenant)'
                ),
                {"id": story_id, "tenant": tenant},
            )
            # No tenant_id: the validator takes it from the story.
            await conn.execute(
                sa.insert(StoryMap).values(story_id=story_id, map_id=map_id)
            )
    yield ctx, ids
    async with _privileged(ctx.db_url) as conn:
        await conn.execute(
            sa.text("DELETE FROM catalog.stories WHERE id = ANY(:ids)"),
            {"ids": [story for story, _ in ids.values()]},
        )
        await conn.execute(
            sa.text("DELETE FROM catalog.maps WHERE id = ANY(:ids)"),
            {"ids": [map_id for _, map_id in ids.values()]},
        )


async def test_a_tenant_sees_only_its_own_stories_and_story_maps(stories):
    ctx, ids = stories
    story_a, map_a = ids[ctx.tenant_a]
    story_b, _ = ids[ctx.tenant_b]

    async with ctx.tenant_session(ctx.tenant_a) as session:
        story_ids = set(await session.scalars(select(Story.id)))
        story_maps = (
            await session.execute(select(StoryMap.story_id, StoryMap.map_id))
        ).all()

    assert story_a in story_ids
    assert story_b not in story_ids
    assert (story_a, map_a) in story_maps
    assert all(story_id != story_b for story_id, _ in story_maps)


async def test_a_story_map_row_carries_its_storys_tenant(stories):
    ctx, ids = stories
    story_a, _ = ids[ctx.tenant_a]
    async with _privileged(ctx.db_url) as conn:
        tenant = await conn.scalar(
            sa.text("SELECT tenant_id FROM catalog.story_maps WHERE story_id = :id"),
            {"id": story_a},
        )
    assert str(tenant) == str(ctx.tenant_a)


async def test_privileged_sql_cannot_add_another_tenants_map(stories):
    ctx, ids = stories
    story_a, _ = ids[ctx.tenant_a]
    _, map_b = ids[ctx.tenant_b]
    with pytest.raises(sa.exc.DBAPIError, match="does not match story tenant"):
        async with _privileged(ctx.db_url) as conn:
            await conn.execute(
                sa.insert(StoryMap).values(story_id=story_a, map_id=map_b)
            )
