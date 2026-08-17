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
from app.processing.embeddings import service as service_module
from tests.fixtures.dummy_overlay.tenant_isolation import TenantIsolationSurface


def _result(*, rows=(), scalar=None, first=None):
    result = MagicMock()
    result.all.return_value = list(rows)
    result.scalar_one.return_value = scalar
    result.scalar_one_or_none.return_value = scalar
    # fix(#1580): the anchor read returns the row rather than one column, so it
    # goes through `.first()`. Left as an explicit None by default: a MagicMock
    # here would be truthy and unpack into three MagicMocks, which is how a
    # caller that stopped reading a real row would still look like it worked.
    result.first.return_value = first
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
        "resolve_embedding_model_name",
        AsyncMock(return_value="tenant-isolation-model"),
    )
    # fix(#1580 review r4): the fingerprint resolver too. The anchor read orders
    # by "the row search would use", so it asks what the live configuration IS
    # before running its own query — and that resolution goes to the database on
    # a cold persistent-config cache, consuming one of the three results queued
    # below and killing the test with StopAsyncIteration.
    #
    # It went unnoticed because the failure is ORDER-DEPENDENT: run after any
    # test that warms the config cache and the resolver answers without a query,
    # so a whole-file or whole-suite run is green and this node alone is red.
    # Both resolvers are stubbed now, so what this test asserts — that every
    # embedding helper crosses the Record boundary — no longer depends on what
    # ran before it.
    monkeypatch.setattr(
        helpers,
        "resolve_embedding_config_fingerprint",
        AsyncMock(return_value="f" * 64),
    )

    presence_session = AsyncMock()
    presence_session.execute.return_value = _result(scalar=True)
    assert await helpers.has_embeddings(presence_session) is True
    presence_sql = str(presence_session.execute.await_args.args[0])
    assert "JOIN catalog.records AS visible_record" in presence_sql

    # fix(#1580): the anchor read now selects the row's identity alongside its
    # vector, so the stub returns the triple `get_anchor_embedding_row` unpacks.
    source_result = _result(first=([1.0, 0.0, 0.0], "tenant-isolation-model", None))
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
    monkeypatch.setattr(
        helpers,
        "resolve_embedding_model_name",
        AsyncMock(return_value="tenant-isolation-model"),
    )
    stats_result = MagicMock()
    # (total, active-model embedded, any-model embedded) — fix(#1503)
    stats_result.one.return_value = (4, 3, 3)
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
    # fix(#1511 review r3): the force path now proves it can embed before it
    # deletes. This test is about the DELETE's record scoping, so give it a
    # working provider rather than letting the pre-flight abort the run.
    monkeypatch.setattr(
        backfill_module,
        "generate_embeddings_batch",
        AsyncMock(return_value=[[1.0] + [0.0] * 1535]),
    )
    backfill_session = AsyncMock()
    # fix(#1511 review r4): the pre-flight also reads the embedding column's
    # declared width off pg_attribute, so a bare AsyncMock hands it a coroutine
    # instead of a number. Return the width the stubbed provider above actually
    # produces — a mismatch here would abort the run before the DELETE this
    # test exists to inspect.
    preflight_result = MagicMock()
    preflight_result.scalar_one_or_none.return_value = 1536
    backfill_session.execute.return_value = preflight_result

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
        "resolve_embedding_model_name",
        AsyncMock(return_value="tenant-isolation-model"),
    )
    # fix(#1546): the coverage query now scopes itself to the live embedding
    # CONFIGURATION as well as the model, and resolving that reads the
    # dimensions and the provider endpoint. These sessions run as
    # geolens_reader, which is denied app_settings — the same precondition
    # #1511 and #1525 had to supply for the force path one test down, and for
    # the same reason: the denied read aborts the transaction, so the stats
    # query behind it degrades to zeros and the isolation this test asserts is
    # never reached. Supplied here so the real fingerprint resolution runs and
    # the query under test is the real one. The seeded rows carry no stamp, so
    # which endpoint this answers with does not change what they match.
    monkeypatch.setattr(
        backfill_module.EMBEDDING_DIMS, "get", AsyncMock(return_value=1536)
    )
    monkeypatch.setattr(
        service_module,
        "resolve_embedding_base_url",
        AsyncMock(return_value=None),
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
        # fix(#1511): the force path snapshots the active model and dimensions
        # before it deletes, and this session runs as geolens_reader, which
        # cannot read app_settings. Unpinned, the resolver returns the unknown
        # sentinel and the dimensions read raises outright, either of which
        # aborts the run before the DELETE this test exists to check. Supply
        # the precondition and keep asserting the thing it asserts.
        monkeypatch.setattr(
            helpers,
            "resolve_embedding_model_name",
            AsyncMock(return_value="tenant-isolation-model"),
        )
        monkeypatch.setattr(
            backfill_module.EMBEDDING_DIMS, "get", AsyncMock(return_value=1536)
        )
        # fix(#1525 review r2): the snapshot reads the dimensions uncached now,
        # to see past a mid-eviction cache. Same app_settings denial, so the
        # same precondition has to be supplied.
        monkeypatch.setattr(
            backfill_module.EMBEDDING_DIMS, "get_uncached", AsyncMock(return_value=1536)
        )
        # fix(#1511 review r3): likewise for the AI gate, which force now
        # checks before its delete, and the pre-flight embedding. Either would
        # otherwise abort this run before the DELETE under test — the gate by
        # raising on the same app_settings denial as the keys above.
        monkeypatch.setattr(
            backfill_module.AI_ENABLED, "get", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            backfill_module,
            "generate_embeddings_batch",
            AsyncMock(return_value=[[1.0] + [0.0] * 1535]),
        )
        # fix(#1525): and for the endpoint, the third value the force path now
        # snapshots before it deletes. It resolves through the provider, whose
        # first act is another app_settings read this role is denied.
        monkeypatch.setattr(
            backfill_module,
            "resolve_embedding_base_url",
            AsyncMock(return_value=None),
        )

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
