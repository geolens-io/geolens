"""#1010: analysis materialize carries tenant attribution end to end.

What this pins
--------------
``Dataset.tenant_id`` / ``Record.tenant_id`` are stamped by a database
trigger, not by application code: migration ``0018_tenant_insert_stamping``
installs ``catalog.stamp_current_tenant_on_insert()`` as a BEFORE INSERT
trigger that reads ``current_setting('app.current_tenant', true)``.  The
application deliberately never passes ``tenant_id`` — ``create_dataset``
constructs ``Record(...)`` and ``Dataset(...)`` with no tenant field.

So the invariant worth testing is **the analysis worker's connection has
``app.current_tenant`` set at the moment it inserts**.  Nothing else in the
chain can be observed by reading the source: ``_materialize`` commits the CTAS
transaction immediately before registration, ``SET LOCAL`` does not survive a
commit (which is why the statement timeout is re-issued by hand on the next
line), and the tenant GUC survives only because the engine's ``"begin"`` event
listener ``_on_begin`` re-issues ``set_config('app.current_tenant', ...)`` at
the start of every connection-level transaction.

A refactor that installs the hook on a different engine, or a job that loses
``current_tenant_var``, produces a dataset with a NULL ``tenant_id`` and no
error anywhere — and then the user's own analysis output 404s on tiles,
because the vector tile lookup filters ``DatasetORM.tenant_id == tid``.

Deliberately NOT a grep guard over ``tasks.py``: ``tenant_id`` already appears
there in ``_output_table_adopted``'s tenant-scoped read probe, so a grep passes
whether or not the stamp works.

Fixture decision (option B)
---------------------------
The ``multi_tenant_rls`` harness's ``tenant_session()`` issues
``SET LOCAL ROLE geolens_reader`` so FORCE RLS applies to a superuser test
login.  A reader role cannot run the materialize CTAS, the
``ALTER TABLE ... ALTER COLUMN geom TYPE``, or the ``ADD PRIMARY KEY (gid)``.
This module therefore takes option B: it drives the worker on its own
writer-capable session factory (built here exactly the way
``app/core/db/session.py`` builds the shared one) and reads the stamped rows
back through an RLS-free admin connection, asserting the column value rather
than inferring it from a lookup that merely succeeded.  The harness itself is
untouched, so its eleven existing consumers keep their current setup cost —
notably the cluster-global role churn this module needs and they do not.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_tenant_attribution_materialize.py -x -q
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.factories import create_dataset, get_user_id

# Two polygons, same shapes the analysis suite uses elsewhere.
_SQUARE = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
_FAR_SQUARE = "POLYGON((10 10, 11 10, 11 11, 10 11, 10 10))"


# ---------------------------------------------------------------------------
# Data-plane substrate
#
# In multi_tenant the analysis worker writes into ``data_t_{tid}`` and the
# statement hook binds ``geolens_writer_t_{tid}`` / ``geolens_reader_t_{tid}``
# around every data-plane statement, so those must exist.  conftest provisions
# schemas + reader roles only for two FIXED tenant ids, and the harness mints
# random ones, so this module provisions its own.  Production uses the
# SECURITY DEFINER ``catalog.provision_tenant_data_schema``; that path needs a
# ``catalog.tenants`` row and the five gateway roles, none of which this test
# is about.
# ---------------------------------------------------------------------------


def _substrate_names(tenant_id: str) -> tuple[str, str, str]:
    """Return (schema, reader_role, writer_role) via the app's own helpers.

    Using the real helpers rather than re-deriving the names here means the
    substrate is provisioned under exactly the identifiers the worker will ask
    for; a naming change in ``tenant_schema.py`` moves both sides together.
    """
    from app.core.db.tenant_schema import (
        tenant_data_schema,
        tenant_reader_role,
        tenant_writer_role,
    )

    return (
        tenant_data_schema(tenant_id),
        tenant_reader_role(tenant_id),
        tenant_writer_role(tenant_id),
    )


async def _provision_substrate(conn, tenant_id: str) -> None:
    """Create the tenant schema + reader/writer roles and their grants."""
    schema, reader, writer = _substrate_names(tenant_id)
    await conn.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    for role in (reader, writer):
        await conn.execute(
            sa.text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
                f"CREATE ROLE {role} NOLOGIN; "
                "END IF; END $$"
            )
        )
    await conn.execute(sa.text(f'GRANT USAGE ON SCHEMA "{schema}" TO {reader}'))
    await conn.execute(sa.text(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO {writer}'))
    # Reader-bound statements can reach a writer-created relation before
    # registration's explicit ``grant_reader_access`` runs (metadata probes,
    # for instance), so give the substrate the same standing default the
    # per-tenant provisioner gives it rather than depending on statement order.
    await conn.execute(
        sa.text(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE {writer} IN SCHEMA "{schema}" '
            f"GRANT SELECT ON TABLES TO {reader}"
        )
    )


async def _deprovision_substrate(conn, tenant_id: str) -> None:
    """Drop the tenant schema and its roles. Roles are CLUSTER-global."""
    schema, reader, writer = _substrate_names(tenant_id)
    await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    # Clears the remaining grants + default-ACL entries these roles own in
    # this database; DROP ROLE refuses while any dependency survives.
    await conn.execute(sa.text(f"DROP OWNED BY {reader}, {writer}"))
    await conn.execute(sa.text(f"DROP ROLE IF EXISTS {reader}"))
    await conn.execute(sa.text(f"DROP ROLE IF EXISTS {writer}"))


# The tenant boundary, minus ``users`` (the harness deletes its own two seeded
# rows).  Deleting by tenant is what makes this safe on a shared per-worker DB:
# the harness mints both tenant UUIDs per test, so no row carrying one of them
# belongs to anything else.  Listing the whole boundary rather than the three
# tables this module happens to write today means a case added later that
# creates a map or a collection is cleaned up too.
#
# Order is FK-derived, not alphabetical:
#   - ``ingest_jobs.dataset_id -> datasets`` is ON DELETE SET NULL, so a job row
#     SURVIVES a dataset delete with a nulled reference. It has to go first and
#     explicitly. (Everything else hanging off records/datasets is CASCADE.)
#   - ``maps``/``collections``/``embed_tokens`` reference datasets, so they
#     precede it.
#   - ``records`` last of the record graph: its CASCADEs take record_keywords
#     (the provenance INSERT..SELECT writes there), record_translations,
#     record_contacts, record_distributions, record_embeddings and
#     dataset_relationships with it.
_TENANT_SCOPED_CATALOG_TABLES = (
    "ingest_jobs",
    "embed_tokens",
    "maps",
    "collections",
    "datasets",
    "records",
    "audit_logs",
    "oauth_accounts",
)


async def _delete_tenant_catalog_rows(conn, tenant_ids: list[str]) -> None:
    """Delete every committed catalog row belonging to *tenant_ids*.

    ``_seed_source_dataset`` and ``_create_job`` commit before the worker even
    starts, a successful materialize commits a second record/dataset pair plus
    its provenance, and the missing-context case deliberately leaves a PENDING
    job. The per-worker test DB is shared, so anything left behind outlives the
    test: rows naming a table whose schema this fixture is about to drop, and a
    pending job that later quota or stale-sweep tests would count.
    """
    for table in _TENANT_SCOPED_CATALOG_TABLES:
        # Table name comes from the module-level tuple above, never from data.
        await conn.execute(
            sa.text(f"DELETE FROM catalog.{table} WHERE tenant_id = ANY(:tenant_ids)"),
            {"tenant_ids": tenant_ids},
        )


@asynccontextmanager
async def _admin_connection(db_url: str):
    """An AUTOCOMMIT superuser connection with NO tenant hooks installed.

    Assertions read through this: it bypasses RLS (the test DB login is a
    superuser) and never sets the tenant GUC, so a ``tenant_id`` value it
    returns is the stored column, not a row some filter happened to admit.
    """
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            yield conn
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@dataclass
class _TenantAnalysisContext:
    """The harness's two tenants plus a writer-capable worker session factory.

    ``session_factory`` is what ``app.core.db.async_session`` points at for the
    duration of a test: hook-installed, and WITHOUT the harness's
    ``SET LOCAL ROLE geolens_reader``, so it can run the materialize DDL.
    """

    tenant_a: str
    tenant_b: str
    user_a_id: uuid.UUID
    db_url: str
    session_factory: async_sessionmaker


@pytest.fixture
async def tenant_analysis(multi_tenant_rls, monkeypatch):
    """Layer a writer-capable, hook-installed worker engine over the harness.

    ``_materialize`` never accepts a session — it opens its own from
    ``app.core.db.async_session``.  conftest points that at an engine with NO
    tenant hooks, so the worker's transactions would never issue the GUC and
    the stamp could not happen for an environmental reason.  This fixture
    repoints it at an engine built the way ``app/core/db/session.py`` builds
    the shared one, which is the wiring the worker actually runs under.
    """
    from app.core.db.tenant_session import install_tenant_session_hook

    ctx = multi_tenant_rls

    async with _admin_connection(ctx.db_url) as conn:
        await _provision_substrate(conn, ctx.tenant_a)
        await _provision_substrate(conn, ctx.tenant_b)

    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    install_tenant_session_hook(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "async_session", session_factory)

    try:
        yield _TenantAnalysisContext(
            tenant_a=ctx.tenant_a,
            tenant_b=ctx.tenant_b,
            user_a_id=uuid.UUID(ctx.user_a_id),
            db_url=ctx.db_url,
            session_factory=session_factory,
        )
    finally:
        # The tile metadata cache is a module global keyed by {tid}:{table};
        # this module's tenants are gone after teardown, so drop their entries.
        from app.processing.tiles.router import _dataset_cache, _dataset_cache_lock

        with _dataset_cache_lock:
            _dataset_cache.clear()
        await engine.dispose()
        async with _admin_connection(ctx.db_url) as conn:
            # Committed rows first: a catalog row naming a table whose schema
            # the next statement drops is worse than either alone.
            await _delete_tenant_catalog_rows(conn, [ctx.tenant_a, ctx.tenant_b])
            await _deprovision_substrate(conn, ctx.tenant_a)
            await _deprovision_substrate(conn, ctx.tenant_b)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_source_dataset(env: _TenantAnalysisContext, tenant_id: str):
    """Create a two-polygon source table + its catalog rows for *tenant_id*.

    Runs on the worker's own session factory with the tenant bound, so the
    table lands in ``data_t_{tid}`` under the writer role and the catalog rows
    are stamped by the same trigger the assertions are about.
    """
    from app.core.db.tenant_session import tenant_job_context

    schema, reader, _writer = _substrate_names(tenant_id)
    table_name = f"ds_{uuid.uuid4().hex[:12]}"

    with tenant_job_context(tenant_id):
        async with env.session_factory() as session:
            await session.execute(
                sa.text(
                    f'CREATE TABLE "{schema}"."{table_name}" ('
                    f"  gid SERIAL PRIMARY KEY,"
                    f"  name TEXT,"
                    f"  geom geometry(Polygon, 4326),"
                    f"  geom_4326 geometry(Polygon, 4326)"
                    f")"
                )
            )
            await session.execute(
                sa.text(
                    f'INSERT INTO "{schema}"."{table_name}" (name, geom, geom_4326)'
                    f" VALUES"
                    f" ('a', ST_GeomFromText('{_SQUARE}', 4326),"
                    f"  ST_GeomFromText('{_SQUARE}', 4326)),"
                    f" ('b', ST_GeomFromText('{_FAR_SQUARE}', 4326),"
                    f"  ST_GeomFromText('{_FAR_SQUARE}', 4326))"
                )
            )
            await session.execute(
                sa.text(f'GRANT SELECT ON "{schema}"."{table_name}" TO {reader}')
            )
            await session.commit()

            return await create_dataset(
                session,
                created_by=env.user_a_id,
                table_name=table_name,
                geometry_type="POLYGON",
                feature_count=2,
                visibility="private",
            )


async def _create_job(env: _TenantAnalysisContext, tenant_id: str) -> uuid.UUID:
    """Insert a pending analysis job owned by the harness's tenant-A user."""
    from app.core.db.tenant_session import tenant_job_context
    from app.platform.jobs.models import IngestJob

    with tenant_job_context(tenant_id):
        async with env.session_factory() as session:
            job = IngestJob(
                source_filename="analysis-1010",
                created_by=env.user_a_id,
                status="pending",
            )
            session.add(job)
            await session.commit()
            return job.id


async def _job_row(db_url: str, job_id: uuid.UUID):
    """Read a job's terminal state through the RLS-free admin connection."""
    async with _admin_connection(db_url) as conn:
        result = await conn.execute(
            sa.text(
                "SELECT status, dataset_id, error_message"
                " FROM catalog.ingest_jobs WHERE id = :id"
            ).bindparams(id=job_id)
        )
        return result.one()


async def _stamped_tenant_ids(db_url: str, dataset_id) -> tuple:
    """Return (datasets.tenant_id, records.tenant_id) for *dataset_id*.

    Read as stored columns on an RLS-free connection — the acceptance
    criterion is the value, not that some scoped lookup found a row.
    """
    async with _admin_connection(db_url) as conn:
        result = await conn.execute(
            sa.text(
                "SELECT d.tenant_id AS dataset_tenant_id,"
                "       r.tenant_id AS record_tenant_id,"
                "       d.table_name AS table_name"
                " FROM catalog.datasets d"
                " JOIN catalog.records r ON r.id = d.record_id"
                " WHERE d.id = :dataset_id"
            ).bindparams(dataset_id=dataset_id)
        )
        return result.one()


# ---------------------------------------------------------------------------
# The stamp
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestMaterializeStampsTenantAttribution:
    async def test_dataset_and_record_carry_the_job_tenant(self, tenant_analysis):
        """A materialize bound to tenant A stamps both catalog rows with A."""
        env = tenant_analysis
        src = await _seed_source_dataset(env, env.tenant_a)
        job_id = await _create_job(env, env.tenant_a)

        from app.processing.analysis.tasks import materialize_analysis

        await materialize_analysis(
            tenant_id=env.tenant_a,
            job_id=str(job_id),
            dataset_id=str(src.id),
            user_id=str(env.user_a_id),
            operation="centroid",
            title=f"Centroids {uuid.uuid4().hex[:6]}",
        )

        job = await _job_row(env.db_url, job_id)
        assert job.status == "complete", job.error_message
        assert job.dataset_id is not None

        row = await _stamped_tenant_ids(env.db_url, job.dataset_id)
        assert str(row.dataset_tenant_id) == env.tenant_a, (
            "catalog.datasets.tenant_id is not the job's tenant — the analysis "
            "worker's connection did not carry app.current_tenant at INSERT.\n"
            f"  stored={row.dataset_tenant_id!r} expected={env.tenant_a!r}"
        )
        assert str(row.record_tenant_id) == env.tenant_a, (
            "catalog.records.tenant_id is not the job's tenant — the record "
            "insert in create_dataset ran without the tenant GUC.\n"
            f"  stored={row.record_tenant_id!r} expected={env.tenant_a!r}"
        )

    async def test_stamp_is_lost_when_the_guc_is_absent_at_registration(
        self, tenant_analysis, monkeypatch
    ):
        """Non-vacuity: break only the GUC at registration and the stamp goes NULL.

        ``_materialize`` commits the CTAS transaction and then re-opens one for
        registration; the tenant GUC is present in that second transaction only
        because the engine begin-hook re-issues ``set_config`` with
        ``current_tenant_var``.  Here the registration transaction is re-opened
        with the var momentarily cleared, so the begin-hook issues nothing —
        exactly the state a lost worker context or a hook installed on another
        engine produces.

        The var is restored before ``register_existing_table`` runs, because
        that function resolves the physical tenant schema from it and would
        otherwise raise instead of writing an unstamped row.  Clearing the var
        outright is a LOUD failure, not this silent one; the case below covers
        that direction.

        The stamped values are read from INSIDE the registration transaction,
        because a second guard downstream refuses to link a tenant-A job to a
        NULL-tenant dataset (the ``catalog.ingest_jobs`` cross-tenant trigger
        from ``0022_tenant_audit_job_isolation``) and takes the whole
        registration down with it.  That is defense in depth working, and it
        is asserted below — but it also means the unstamped rows never reach
        a committed state where the outer query could see them.
        """
        from app.core.db.tenant_session import current_tenant_var
        from app.processing.ingest import service as ingest_service

        env = tenant_analysis
        src = await _seed_source_dataset(env, env.tenant_a)
        job_id = await _create_job(env, env.tenant_a)

        real_register = ingest_service.register_existing_table
        stamped: dict[str, object] = {}

        async def _register_without_tenant_guc(session, request, user):
            # End the transaction the registration statement_timeout opened,
            # then re-open it with no tenant bound so no GUC is issued.
            await session.rollback()
            token = current_tenant_var.set(None)
            try:
                await session.execute(sa.text("SELECT 1"))
            finally:
                current_tenant_var.reset(token)
            dataset = await real_register(session, request, user)
            row = (
                await session.execute(
                    sa.text(
                        "SELECT d.tenant_id AS dataset_tenant_id,"
                        "       r.tenant_id AS record_tenant_id"
                        " FROM catalog.datasets d"
                        " JOIN catalog.records r ON r.id = d.record_id"
                        " WHERE d.id = :dataset_id"
                    ).bindparams(dataset_id=dataset.id)
                )
            ).one()
            stamped["dataset"] = row.dataset_tenant_id
            stamped["record"] = row.record_tenant_id
            return dataset

        monkeypatch.setattr(
            ingest_service, "register_existing_table", _register_without_tenant_guc
        )

        from app.processing.analysis.tasks import materialize_analysis

        await materialize_analysis(
            tenant_id=env.tenant_a,
            job_id=str(job_id),
            dataset_id=str(src.id),
            user_id=str(env.user_a_id),
            operation="centroid",
            title=f"Centroids {uuid.uuid4().hex[:6]}",
        )

        # The rows the positive case asserts on: written with no tenant.
        assert stamped["dataset"] is None, (
            "expected an unstamped dataset with the GUC absent, got "
            f"{stamped['dataset']!r} — the positive assertion would be vacuous"
        )
        assert stamped["record"] is None, (
            "expected an unstamped record with the GUC absent, got "
            f"{stamped['record']!r} — the positive assertion would be vacuous"
        )

        # ...and the job cannot complete against them.
        job = await _job_row(env.db_url, job_id)
        assert job.status == "failed"
        assert job.dataset_id is None

    async def test_missing_worker_tenant_context_fails_loudly(self, tenant_analysis):
        """A task with no tenant kwarg is refused before it can write anything.

        The silent-NULL risk is specific to the GUC; losing the worker context
        entirely is caught at the task boundary by ``tenant_task``.
        """
        env = tenant_analysis
        src = await _seed_source_dataset(env, env.tenant_a)
        job_id = await _create_job(env, env.tenant_a)

        from app.processing.analysis.tasks import materialize_analysis

        with pytest.raises(RuntimeError, match="missing tenant context"):
            await materialize_analysis(
                job_id=str(job_id),
                dataset_id=str(src.id),
                user_id=str(env.user_a_id),
                operation="centroid",
                title=f"Centroids {uuid.uuid4().hex[:6]}",
            )

        job = await _job_row(env.db_url, job_id)
        assert job.status == "pending"
        assert job.dataset_id is None


# ---------------------------------------------------------------------------
# What the stamp buys: the tile lookup
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestMaterializedOutputTileVisibility:
    async def test_tile_lookup_resolves_for_owner_and_404s_for_other_tenant(
        self, tenant_analysis
    ):
        """The output is servable to its own tenant and absent to the other.

        ``_resolve_dataset_meta`` is the vector tile path's dataset resolution
        — the ``DatasetORM.tenant_id == tid`` filter that turns an unstamped
        analysis output into a 404 lives there. Driving it directly keeps the
        assertion on the stamp rather than on tile auth middleware.
        """
        from app.core.db.tenant_session import current_tenant_var
        from app.processing.tiles.router import (
            _dataset_cache,
            _dataset_cache_lock,
            _resolve_dataset_meta,
        )

        env = tenant_analysis
        src = await _seed_source_dataset(env, env.tenant_a)
        job_id = await _create_job(env, env.tenant_a)

        from app.processing.analysis.tasks import materialize_analysis

        await materialize_analysis(
            tenant_id=env.tenant_a,
            job_id=str(job_id),
            dataset_id=str(src.id),
            user_id=str(env.user_a_id),
            operation="centroid",
            title=f"Centroids {uuid.uuid4().hex[:6]}",
        )

        job = await _job_row(env.db_url, job_id)
        assert job.status == "complete", job.error_message
        row = await _stamped_tenant_ids(env.db_url, job.dataset_id)
        table_name = row.table_name

        with _dataset_cache_lock:
            _dataset_cache.clear()

        token = current_tenant_var.set(env.tenant_a)
        try:
            async with env.session_factory() as db:
                meta = await _resolve_dataset_meta(table_name, db)
            assert str(meta.dataset_id) == str(job.dataset_id)
        finally:
            current_tenant_var.reset(token)

        token = current_tenant_var.set(env.tenant_b)
        try:
            async with env.session_factory() as db:
                with pytest.raises(HTTPException) as excinfo:
                    await _resolve_dataset_meta(table_name, db)
            assert excinfo.value.status_code == 404
        finally:
            current_tenant_var.reset(token)


# ---------------------------------------------------------------------------
# Single-tenant is unchanged
# ---------------------------------------------------------------------------


class TestSingleTenantUnchanged:
    """The same path in the default mode leaves tenant_id NULL.

    Consistent with ``test_iso_single_tenant_byte_identical.py``: the dormant
    columns stay dormant, the trigger's ``current_setting`` is NULL and it
    returns the row untouched.  No harness, no RLS — this is the default mode
    every non-cloud install runs.
    """

    async def test_materialize_leaves_tenant_id_null(self, test_db_session):
        from app.processing.analysis.tasks import materialize_analysis
        from app.platform.jobs.models import IngestJob
        from tests.test_analysis_preview import _create_polygon_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = IngestJob(
            source_filename="analysis-1010-single",
            created_by=admin_id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        await materialize_analysis(
            job_id=str(job.id),
            dataset_id=str(src.id),
            user_id=str(admin_id),
            operation="centroid",
            title=f"Centroids {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        assert job.dataset_id is not None

        row = (
            await test_db_session.execute(
                sa.text(
                    "SELECT d.tenant_id AS dataset_tenant_id,"
                    "       r.tenant_id AS record_tenant_id"
                    " FROM catalog.datasets d"
                    " JOIN catalog.records r ON r.id = d.record_id"
                    " WHERE d.id = :dataset_id"
                ).bindparams(dataset_id=job.dataset_id)
            )
        ).one()
        assert row.dataset_tenant_id is None
        assert row.record_tenant_id is None


# ---------------------------------------------------------------------------
# The wiring the stamp depends on
# ---------------------------------------------------------------------------


def test_shared_engine_carries_the_tenant_begin_hook():
    """``app/core/db/session.py`` registers the GUC re-issue on its engine.

    Half of the wiring: the hook exists on the engine that module builds. The
    other half — that the worker's session factory is bound to THAT engine —
    is the test below. Both are kept because they fail for different reasons
    and the distinction is the whole diagnosis: a passing engine assertion
    beside a failing factory assertion says the hook is installed but on the
    wrong object.
    """
    from sqlalchemy import event

    from app.core.db.session import engine
    from app.core.db.tenant_session import _on_begin

    assert event.contains(engine.sync_engine, "begin", _on_begin)


def test_worker_session_factory_is_bound_to_a_hooked_engine():
    """fix(#1171 review): the assertion above does not imply this one.

    Every DB test in this module monkeypatches ``app.core.db.async_session``
    onto a factory it built itself, so none of them can observe the production
    factory at all. And asserting the hook on ``app.core.db.session.engine``
    proves nothing about what the factory is bound to: rebuild
    ``async_session`` from a second, unhooked engine and the engine assertion
    still passes while every materialize silently stops stamping.

    So resolve the factory exactly the way ``_materialize`` does — ``from
    app.core.db import async_session`` at call time, through the package
    façade — and follow it to the engine its sessions would actually run on.
    Constructing a session opens no connection, so this stays DB-free; the
    bind it reports is the sync ``Engine`` the event listener lives on.
    """
    from sqlalchemy import event

    from app.core.db import async_session
    from app.core.db.tenant_session import _on_begin

    bind = async_session().sync_session.get_bind()
    assert event.contains(bind, "begin", _on_begin), (
        "the session factory the analysis worker imports is bound to an engine "
        "with no tenant begin-hook, so every insert it makes lands with a NULL "
        f"tenant_id.\n  factory bind={bind!r}"
    )
