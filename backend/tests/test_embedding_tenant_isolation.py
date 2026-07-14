"""Tenant-isolation regressions for embedding and AI catalog paths."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.admin.service import AdminService
from app.modules.catalog.datasets.domain.models import Record
from app.platform.extensions.defaults import DefaultProcessingPort
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import helpers
from tests.fixtures.dummy_overlay.tenant_isolation import TenantIsolationSurface


def _result(*, rows=(), scalar=None):
    result = MagicMock()
    result.all.return_value = list(rows)
    result.scalar_one.return_value = scalar
    result.scalar_one_or_none.return_value = scalar
    return result


@pytest.mark.anyio
async def test_processing_vocabulary_queries_join_rls_visible_records():
    """Unscoped keyword rows must be constrained through Record RLS."""
    session = AsyncMock()
    session.execute.return_value = _result()
    port = DefaultProcessingPort()

    await port.get_catalog_vocabulary(session)
    await port.get_keywords_for_records(session, [uuid.uuid4()])

    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert len(statements) == 2
    for statement in statements:
        assert "JOIN catalog.records" in statement
        assert "catalog.record_keywords.record_id = catalog.records.id" in statement


@pytest.mark.anyio
async def test_embedding_helper_queries_join_rls_visible_records(monkeypatch):
    """Presence, target, and neighbor lookups all cross the Record boundary."""
    helpers._has_embeddings_cache.clear()
    monkeypatch.setattr(
        helpers,
        "_resolve_embedding_model_name",
        AsyncMock(return_value="tenant-isolation-model"),
    )

    presence_session = AsyncMock()
    presence_session.execute.return_value = _result(scalar=True)
    assert await helpers.has_embeddings(presence_session) is True
    presence_sql = str(presence_session.execute.await_args.args[0])
    assert "JOIN catalog.records AS visible_record" in presence_sql

    source_result = _result(scalar=[1.0, 0.0, 0.0])
    hnsw_result = _result()
    neighbor_result = _result(rows=[])
    nearest_session = AsyncMock()
    nearest_session.execute.side_effect = [
        source_result,
        hnsw_result,
        neighbor_result,
    ]

    assert await helpers.get_nearest_record_ids(nearest_session, uuid.uuid4()) == []
    target_sql = str(nearest_session.execute.await_args_list[0].args[0])
    neighbor_sql = str(nearest_session.execute.await_args_list[2].args[0])
    assert "JOIN catalog.records" in target_sql
    assert "JOIN catalog.records" in neighbor_sql

    helpers._has_embeddings_cache.clear()


@pytest.mark.anyio
async def test_admin_stats_and_force_delete_are_record_scoped(monkeypatch):
    """Stats join Record and force deletion uses a visible-Record subquery."""
    stats_result = MagicMock()
    stats_result.one.return_value = (4, 3)
    stats_session = AsyncMock()
    stats_session.execute.return_value = stats_result

    stats = await AdminService(stats_session).get_embedding_stats()
    assert (stats.total_records, stats.embedded_records) == (4, 3)
    stats_sql = str(stats_session.execute.await_args.args[0])
    assert "FROM catalog.records AS visible_record" in stats_sql
    assert "LEFT JOIN catalog.record_embeddings AS embedding" in stats_sql

    port = SimpleNamespace(
        get_record_orm_class=lambda: Record,
        get_records_without_embeddings=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(backfill_module, "get_processing_port", lambda: port)
    backfill_session = AsyncMock()

    result = await backfill_module.backfill_embeddings(backfill_session, force=True)

    assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
    delete_sql = str(backfill_session.execute.await_args.args[0])
    assert delete_sql.startswith("DELETE FROM catalog.record_embeddings")
    assert "SELECT catalog.records.id" in delete_sql
    backfill_session.commit.assert_awaited_once()


async def _execute_autocommit(engine, statement: str, params: dict | None = None):
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        return await connection.execute(sa.text(statement), params or {})


@asynccontextmanager
async def _seed_embedding_rows(ctx):
    """Seed tenant A/B keywords and equal vectors outside the RLS role."""
    async with TenantIsolationSurface(ctx) as surface:
        engine = create_async_engine(ctx.db_url, poolclass=NullPool)
        record_ids = [surface.rec_a_id, surface.rec_b_id]
        try:
            await _execute_autocommit(
                engine,
                "GRANT SELECT ON catalog.record_keywords TO geolens_reader",
            )
            await _execute_autocommit(
                engine,
                "GRANT SELECT, DELETE ON catalog.record_embeddings TO geolens_reader",
            )
            dimension_result = await _execute_autocommit(
                engine,
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'catalog.record_embeddings'::regclass "
                "AND attname = 'embedding'",
            )
            dimension = int(dimension_result.scalar_one())
            vector = "[" + ",".join(["1"] + ["0"] * (dimension - 1)) + "]"

            for label, record_id in zip(("tenant-a-only", "tenant-b-only"), record_ids):
                await _execute_autocommit(
                    engine,
                    "INSERT INTO catalog.record_keywords "
                    "(record_id, keyword, keyword_type) "
                    "VALUES (:record_id, :keyword, 'theme')",
                    {"record_id": record_id, "keyword": label},
                )
                await _execute_autocommit(
                    engine,
                    "INSERT INTO catalog.record_embeddings "
                    "(record_id, embedding, model_name, content_hash) "
                    "VALUES (:record_id, CAST(:embedding AS vector), "
                    "'tenant-isolation-model', :content_hash)",
                    {
                        "record_id": record_id,
                        "embedding": vector,
                        "content_hash": label,
                    },
                )

            yield surface, engine
        finally:
            await _execute_autocommit(
                engine,
                "DELETE FROM catalog.record_embeddings "
                "WHERE record_id = ANY(CAST(:record_ids AS uuid[]))",
                {"record_ids": record_ids},
            )
            await _execute_autocommit(
                engine,
                "DELETE FROM catalog.record_keywords "
                "WHERE record_id = ANY(CAST(:record_ids AS uuid[]))",
                {"record_ids": record_ids},
            )
            await _execute_autocommit(
                engine,
                "REVOKE SELECT, DELETE ON catalog.record_embeddings "
                "FROM geolens_reader",
            )
            await _execute_autocommit(
                engine,
                "REVOKE SELECT ON catalog.record_keywords FROM geolens_reader",
            )
            await engine.dispose()


@pytest.mark.rls
@pytest.mark.anyio
async def test_embedding_reads_and_stats_are_tenant_local(
    multi_tenant_rls,
    monkeypatch,
):
    """Two tenants cannot observe each other's keywords, vectors, or stats."""
    ctx = multi_tenant_rls
    port = DefaultProcessingPort()
    monkeypatch.setattr(
        helpers,
        "_resolve_embedding_model_name",
        AsyncMock(return_value="tenant-isolation-model"),
    )
    helpers._has_embeddings_cache.clear()

    try:
        async with _seed_embedding_rows(ctx) as (surface, engine):
            record_a = uuid.UUID(surface.rec_a_id)
            record_b = uuid.UUID(surface.rec_b_id)

            async with ctx.tenant_session(ctx.tenant_a) as session:
                assert await port.get_catalog_vocabulary(session) == ["tenant-a-only"]
                assert await port.get_keywords_for_records(
                    session, [record_a, record_b]
                ) == ["tenant-a-only"]
                assert await helpers.has_embeddings(session) is True
                assert await helpers.get_nearest_record_ids(session, record_a) == []
                assert await helpers.get_nearest_record_ids(session, record_b) == []
                stats_a = await AdminService(session).get_embedding_stats()
                assert (stats_a.total_records, stats_a.embedded_records) == (1, 1)

            async with ctx.tenant_session(ctx.tenant_b) as session:
                assert await port.get_catalog_vocabulary(session) == ["tenant-b-only"]
                assert await port.get_keywords_for_records(
                    session, [record_a, record_b]
                ) == ["tenant-b-only"]
                assert await helpers.get_nearest_record_ids(session, record_b) == []
                stats_b = await AdminService(session).get_embedding_stats()
                assert (stats_b.total_records, stats_b.embedded_records) == (1, 1)

            await _execute_autocommit(
                engine,
                "DELETE FROM catalog.record_embeddings WHERE record_id = :record_id",
                {"record_id": surface.rec_a_id},
            )
            helpers._has_embeddings_cache.clear()

            async with ctx.tenant_session(ctx.tenant_a) as session:
                assert await helpers.has_embeddings(session) is False
                stats_a = await AdminService(session).get_embedding_stats()
                assert (stats_a.total_records, stats_a.embedded_records) == (1, 0)

            async with ctx.tenant_session(ctx.tenant_b) as session:
                assert await helpers.has_embeddings(session) is True
    finally:
        helpers._has_embeddings_cache.clear()


@pytest.mark.rls
@pytest.mark.anyio
async def test_force_backfill_deletes_only_active_tenant_embeddings(
    multi_tenant_rls,
    monkeypatch,
):
    """force=True must never turn into a fleet-wide embedding delete."""
    ctx = multi_tenant_rls

    async with _seed_embedding_rows(ctx) as (surface, engine):
        port = SimpleNamespace(
            get_record_orm_class=lambda: Record,
            get_records_without_embeddings=AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(backfill_module, "get_processing_port", lambda: port)

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(ctx.tenant_a)
        try:
            async with ctx._session_factory() as session:
                await session.execute(sa.text("SET LOCAL ROLE geolens_reader"))
                result = await backfill_module.backfill_embeddings(session, force=True)
        finally:
            current_tenant_var.reset(token)

        assert result == {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
        port.get_records_without_embeddings.assert_awaited_once()

        counts = await _execute_autocommit(
            engine,
            "SELECT record_id, COUNT(*) FROM catalog.record_embeddings "
            "WHERE record_id = ANY(CAST(:record_ids AS uuid[])) GROUP BY record_id",
            {"record_ids": [surface.rec_a_id, surface.rec_b_id]},
        )
        remaining = {str(record_id): count for record_id, count in counts.all()}
        assert surface.rec_a_id not in remaining
        assert remaining == {surface.rec_b_id: 1}
