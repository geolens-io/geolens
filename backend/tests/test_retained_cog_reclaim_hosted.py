"""On a hosted install, a tenant's sweep reclaims only that tenant's kept COGs."""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.core.db as db_module
from app.core.db.tenant_session import current_tenant_var
from app.platform.storage.local import LocalStorageProvider
from app.processing.raster.vrt_members import reclaim_retained_cogs

pytestmark = pytest.mark.anyio

_GRANTS = (
    "SELECT, DELETE ON catalog.dataset_assets",
    "SELECT ON catalog.raster_assets",
    "SELECT ON catalog.vrt_source_links",
    "SELECT ON catalog.vrt_generations",
)


@pytest.mark.rls
async def test_a_tenants_sweep_reclaims_only_its_own_kept_cogs(
    multi_tenant_rls, tmp_path, monkeypatch
) -> None:
    """Another tenant's kept COG survives the pass untouched, and its own tenant's pass reclaims it."""
    ctx = multi_tenant_rls
    storage = LocalStorageProvider(str(tmp_path / "objects"))
    monkeypatch.setattr("app.platform.storage.get_storage", lambda: storage)
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    kept: dict[str, tuple] = {}

    @asynccontextmanager
    async def _as_runtime_role():
        # The test database connects as a superuser, which RLS never filters.
        async with ctx._session_factory() as session:
            await session.execute(sa.text("SET ROLE geolens_reader"))
            yield session

    async def _charged() -> set:
        async with engine.connect() as conn:
            rows = await conn.execute(
                sa.text(
                    "SELECT dataset_id FROM catalog.dataset_assets "
                    "WHERE dataset_id = ANY(:ids) AND key LIKE 'retained_cog:%'"
                ),
                {"ids": [dataset_id for _, dataset_id, _ in kept.values()]},
            )
            return {row[0] for row in rows}

    async def _sweep_as(tenant: str) -> None:
        token = current_tenant_var.set(tenant)
        try:
            await reclaim_retained_cogs()
        finally:
            current_tenant_var.reset(token)

    try:
        async with engine.begin() as conn:
            for grant in _GRANTS:
                await conn.execute(sa.text(f"GRANT {grant} TO geolens_reader"))
            for tenant in (ctx.tenant_a, ctx.tenant_b):
                record_id, dataset_id = uuid4(), uuid4()
                href = f"rasters/{dataset_id}/old/source.cog.tif"
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.records "
                        "(id, title, visibility, record_status, record_type, "
                        " tenant_id, created_at, updated_at) "
                        "VALUES (:id, 'kept COG member', 'private', 'draft', "
                        " 'raster_dataset', :tenant_id, now(), now())"
                    ),
                    {"id": record_id, "tenant_id": tenant},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.datasets (id, record_id, table_name, tenant_id) "
                        "VALUES (:id, :record_id, :table_name, :tenant_id)"
                    ),
                    {
                        "id": dataset_id,
                        "record_id": record_id,
                        "table_name": f"raster_{uuid4().hex[:16]}",
                        "tenant_id": tenant,
                    },
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.dataset_assets "
                        "(dataset_id, key, href, size_bytes) "
                        "VALUES (:id, :key, :href, 1000)"
                    ),
                    {"id": dataset_id, "key": f"retained_cog:{uuid4()}", "href": href},
                )
                kept[tenant] = (record_id, dataset_id, f"tenants/{tenant}/{href}")
        for _, _, key in kept.values():
            await storage.put(key, io.BytesIO(b"kept"))
        monkeypatch.setattr(db_module, "async_session", _as_runtime_role)

        await _sweep_as(ctx.tenant_a)

        assert await _charged() == {kept[ctx.tenant_b][1]}
        assert not await storage.exists(kept[ctx.tenant_a][2])
        assert await storage.exists(kept[ctx.tenant_b][2])

        await _sweep_as(ctx.tenant_b)

        assert await _charged() == set()
        assert not await storage.exists(kept[ctx.tenant_b][2])
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.records WHERE id = ANY(:ids)"),
                {"ids": [record_id for record_id, _, _ in kept.values()]},
            )
            for grant in _GRANTS:
                privileges, table = grant.split(" ON ")
                await conn.execute(
                    sa.text(f"REVOKE {privileges} ON {table} FROM geolens_reader")
                )
        await engine.dispose()
