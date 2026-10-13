"""The audit prune reaches every tenant's rows under enforced RLS.

``audit_logs`` is FORCE-RLS scoped, so a delete with no tenant context sees no
rows. The harness connects as a BYPASSRLS role; each session drops to
``geolens_reader`` per transaction, otherwise FORCE RLS would never apply and
the test would pass against a prune that ignores tenants.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.tenant_session import install_tenant_session_hook

pytestmark = [pytest.mark.anyio, pytest.mark.rls]


async def _seed(conn, tenant_id, *, age_days: int, count: int) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(count)]
    for row_id in ids:
        await conn.execute(
            sa.text(
                "INSERT INTO catalog.audit_logs "
                "(id, tenant_id, action, resource_type, created_at) "
                "VALUES (:id, :tid, 'retention.test', 'test', "
                " now() - make_interval(days => :age))"
            ),
            {"id": row_id, "tid": tenant_id, "age": age_days},
        )
    return ids


async def _remaining(conn, ids: list[uuid.UUID]) -> int:
    return await conn.scalar(
        sa.text("SELECT count(*) FROM catalog.audit_logs WHERE id = ANY(:ids)"),
        {"ids": ids},
    )


async def test_every_tenants_expired_rows_are_pruned(multi_tenant_rls, monkeypatch):
    from app.core.persistent_config import AUDIT_RETENTION_DAYS
    from app.platform.jobs.audit_retention import (
        prune_expired_audit_logs_for_all_tenants,
    )

    ctx = multi_tenant_rls
    monkeypatch.setattr(AUDIT_RETENTION_DAYS, "get", AsyncMock(return_value=90))

    engine = create_async_engine(
        ctx.db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    scoped_engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    install_tenant_session_hook(scoped_engine)

    @sa.event.listens_for(scoped_engine.sync_engine, "begin")
    def _drop_to_reader(conn):  # noqa: ANN001 - sqlalchemy event signature
        conn.exec_driver_sql("SET LOCAL ROLE geolens_reader")

    monkeypatch.setattr(
        "app.core.db.async_session",
        async_sessionmaker(scoped_engine, expire_on_commit=False),
    )

    tenants = (ctx.tenant_a, ctx.tenant_b)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text("GRANT SELECT ON catalog.tenants TO geolens_reader")
            )
            await conn.execute(
                sa.text(
                    "GRANT INSERT, UPDATE, DELETE ON catalog.audit_logs TO geolens_reader"
                )
            )
            for tenant_id in tenants:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.tenants (id, slug, name) "
                        "VALUES (:id, :slug, 'prune probe') ON CONFLICT (id) DO NOTHING"
                    ),
                    {"id": tenant_id, "slug": f"t-{str(tenant_id)[:8]}"},
                )
            old = {t: await _seed(conn, t, age_days=120, count=3) for t in tenants}
            new = {t: await _seed(conn, t, age_days=10, count=2) for t in tenants}

            await prune_expired_audit_logs_for_all_tenants()

            for tenant_id in tenants:
                assert await _remaining(conn, old[tenant_id]) == 0
                assert await _remaining(conn, new[tenant_id]) == 2
            event_tenants = (
                (
                    await conn.execute(
                        sa.text(
                            "SELECT tenant_id FROM catalog.audit_logs "
                            "WHERE action = 'audit.prune' AND tenant_id = ANY(:t)"
                        ),
                        {"t": list(tenants)},
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(map(str, event_tenants)) == sorted(map(str, tenants))
    finally:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.audit_logs WHERE tenant_id = ANY(:t)"),
                {"t": list(tenants)},
            )
            await conn.execute(
                sa.text(
                    "REVOKE INSERT, UPDATE, DELETE ON catalog.audit_logs FROM geolens_reader"
                )
            )
            await conn.execute(
                sa.text("REVOKE SELECT ON catalog.tenants FROM geolens_reader")
            )
            for tenant_id in tenants:
                await conn.execute(
                    sa.text("DELETE FROM catalog.tenants WHERE id = :id"),
                    {"id": tenant_id},
                )
        await engine.dispose()
        await scoped_engine.dispose()
