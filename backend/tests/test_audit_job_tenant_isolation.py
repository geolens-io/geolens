"""Durable hosted-tenant isolation for audit history and ingest jobs."""

from __future__ import annotations

import importlib.util
import inspect
import uuid
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES
from app.modules.audit.models import AuditLog
from app.modules.audit.service import query_audit_logs
from app.platform.jobs.models import IngestJob

pytestmark = pytest.mark.xdist_group("tenancy_global_state")

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_MIGRATION_PATH = (
    _BACKEND_DIR / "alembic" / "versions" / "0022_tenant_audit_job_isolation.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0022_tenant_audit_job_isolation",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_extends_linear_fail_closed_boundary():
    migration = _load_migration()
    source = _MIGRATION_PATH.read_text()
    upgrade_source = inspect.getsource(migration.upgrade)

    assert migration.revision == "0022_tenant_audit_job_isolation"
    assert migration.down_revision == "0021_tenant_control_plane_hardening"
    assert migration._TABLES == ("audit_logs", "ingest_jobs")
    assert {"audit_logs", "ingest_jobs"}.issubset(RLS_TABLES)
    assert "CREATE POLICY tenant_isolation_{table}" in source
    assert "current_setting('app.current_tenant')::uuid" in source
    assert "trg_stamp_current_tenant_on_insert" in source
    assert "enforce_audit_log_user_tenant" in source
    assert "enforce_ingest_job_parent_tenant" in source
    assert "job.created_by IS NULL" in source
    assert "FROM catalog.datasets AS dataset" in source
    assert "SECURITY INVOKER" in source
    assert "GEOLENS_TENANCY_MODE" not in source
    assert "app.core" not in source
    assert "ENABLE ROW LEVEL SECURITY" not in upgrade_source
    assert "FORCE ROW LEVEL SECURITY" not in upgrade_source


def test_models_expose_nullable_indexed_durable_tenant_keys():
    for model, index_name in (
        (AuditLog, "ix_catalog_audit_logs_tenant_id"),
        (IngestJob, "ix_catalog_ingest_jobs_tenant_id"),
    ):
        table = model.__table__
        assert table.c.tenant_id.nullable is True
        indexes = {index.name: index for index in table.indexes}
        assert [column.name for column in indexes[index_name].columns] == ["tenant_id"]


async def test_live_schema_has_dormant_policies_and_parent_guards(test_db_session):
    rows = (
        await test_db_session.execute(
            sa.text(
                """
                SELECT
                    relation.relname,
                    relation.relrowsecurity,
                    relation.relforcerowsecurity,
                    policy.policyname,
                    column_info.is_nullable,
                    EXISTS (
                        SELECT 1
                        FROM pg_trigger AS trigger
                        WHERE trigger.tgrelid = relation.oid
                          AND NOT trigger.tgisinternal
                          AND trigger.tgname = 'trg_stamp_current_tenant_on_insert'
                    ) AS has_stamp_trigger
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_policies AS policy
                  ON policy.schemaname = namespace.nspname
                 AND policy.tablename = relation.relname
                JOIN information_schema.columns AS column_info
                  ON column_info.table_schema = namespace.nspname
                 AND column_info.table_name = relation.relname
                 AND column_info.column_name = 'tenant_id'
                WHERE namespace.nspname = 'catalog'
                  AND relation.relname = ANY(:tables)
                  AND policy.policyname = 'tenant_isolation_' || relation.relname
                ORDER BY relation.relname
                """
            ),
            {"tables": ["audit_logs", "ingest_jobs"]},
        )
    ).all()

    assert [row.relname for row in rows] == ["audit_logs", "ingest_jobs"]
    for row in rows:
        assert row.relrowsecurity is False
        assert row.relforcerowsecurity is False
        assert row.is_nullable == "YES"
        assert row.has_stamp_trigger is True


async def _cleanup_rows(
    db_url: str, *, audit_ids: list[uuid.UUID], job_ids: list[uuid.UUID]
):
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.audit_logs WHERE id = ANY(:ids)"),
                {"ids": audit_ids},
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.ingest_jobs WHERE id = ANY(:ids)"),
                {"ids": job_ids},
            )
    finally:
        await engine.dispose()


@pytest.mark.rls
async def test_deleted_actor_system_audit_and_job_ids_remain_tenant_isolated(
    multi_tenant_rls,
):
    ctx = multi_tenant_rls
    deleted_actor_log = uuid.uuid4()
    system_log = uuid.uuid4()
    other_tenant_log = uuid.uuid4()
    probe_resource_id = uuid.uuid4()
    job_a = uuid.uuid4()
    job_b = uuid.uuid4()
    audit_ids = [deleted_actor_log, system_log, other_tenant_log]
    job_ids = [job_a, job_b]

    # Seed through the privileged test connection while omitting tenant_id on
    # parent-backed rows. The parent guards derive it; the system row proves
    # the generic GUC trigger stamps a row that has no actor parent.
    engine = create_async_engine(
        ctx.db_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at) "
                    "VALUES (:id, :user_id, 'tenant-test', 'probe', "
                    " :resource_id, now())"
                ),
                {
                    "id": deleted_actor_log,
                    "user_id": ctx.user_a_id,
                    "resource_id": probe_resource_id,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at) "
                    "VALUES (:id, :user_id, 'tenant-test', 'probe', "
                    " :resource_id, now())"
                ),
                {
                    "id": other_tenant_log,
                    "user_id": ctx.user_b_id,
                    "resource_id": probe_resource_id,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.ingest_jobs "
                    "(id, status, source_filename, created_by, created_at) "
                    "VALUES (:id, 'pending', :filename, :created_by, now())"
                ),
                {
                    "id": job_a,
                    "filename": "tenant-a.geojson",
                    "created_by": ctx.user_a_id,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.ingest_jobs "
                    "(id, status, source_filename, created_by, created_at) "
                    "VALUES (:id, 'pending', :filename, :created_by, now())"
                ),
                {
                    "id": job_b,
                    "filename": "tenant-b.geojson",
                    "created_by": ctx.user_b_id,
                },
            )

            await conn.execute(
                sa.text("SELECT set_config('app.current_tenant', :tid, false)"),
                {"tid": ctx.tenant_a},
            )
            stamped_tenant = await conn.scalar(
                sa.text(
                    "INSERT INTO catalog.audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at) "
                    "VALUES (:id, NULL, 'system-test', 'probe', "
                    " :resource_id, now()) "
                    "RETURNING tenant_id"
                ),
                {"id": system_log, "resource_id": probe_resource_id},
            )
            await conn.execute(
                sa.text("SELECT set_config('app.current_tenant', '', false)")
            )
            assert stamped_tenant == uuid.UUID(ctx.tenant_a)

            # Both child rows keep their durable tenant when the nullable actor
            # and creator foreign keys are cleared by ON DELETE SET NULL.
            await conn.execute(
                sa.text("DELETE FROM catalog.users WHERE id = :id"),
                {"id": ctx.user_a_id},
            )

        async with ctx.tenant_session(ctx.tenant_a) as session:
            service_logs, service_total = await query_audit_logs(
                session,
                resource_id=probe_resource_id,
            )
            assert service_total == 2
            assert {log.id for log in service_logs} == {
                deleted_actor_log,
                system_log,
            }

            audit_rows = (
                await session.execute(
                    select(AuditLog.id, AuditLog.user_id, AuditLog.tenant_id).where(
                        AuditLog.id.in_(audit_ids)
                    )
                )
            ).all()
            assert {row.id for row in audit_rows} == {
                deleted_actor_log,
                system_log,
            }
            assert all(row.user_id is None for row in audit_rows)
            assert {row.tenant_id for row in audit_rows} == {uuid.UUID(ctx.tenant_a)}

            visible_jobs = set(
                (
                    await session.scalars(
                        select(IngestJob.id).where(IngestJob.id.in_(job_ids))
                    )
                ).all()
            )
            assert visible_jobs == {job_a}

        async with ctx.tenant_session(ctx.tenant_b) as session:
            assert set(
                (
                    await session.scalars(
                        select(AuditLog.id).where(AuditLog.id.in_(audit_ids))
                    )
                ).all()
            ) == {other_tenant_log}
            assert set(
                (
                    await session.scalars(
                        select(IngestJob.id).where(IngestJob.id.in_(job_ids))
                    )
                ).all()
            ) == {job_b}
    finally:
        await engine.dispose()
        await _cleanup_rows(ctx.db_url, audit_ids=audit_ids, job_ids=job_ids)


@pytest.mark.rls
async def test_parent_tenant_mismatch_is_rejected_for_privileged_sql(
    multi_tenant_rls,
):
    ctx = multi_tenant_rls
    engine = create_async_engine(
        ctx.db_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            with pytest.raises(sa.exc.DBAPIError) as audit_error:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.audit_logs "
                        "(user_id, tenant_id, action, resource_type, created_at) "
                        "VALUES (:user_id, :tenant_id, 'mismatch', 'probe', now())"
                    ),
                    {"user_id": ctx.user_a_id, "tenant_id": ctx.tenant_b},
                )
            assert audit_error.value.orig.sqlstate == "42501"

            with pytest.raises(sa.exc.DBAPIError) as job_error:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.ingest_jobs "
                        "(status, created_by, tenant_id, created_at) "
                        "VALUES ('pending', :created_by, :tenant_id, now())"
                    ),
                    {"created_by": ctx.user_a_id, "tenant_id": ctx.tenant_b},
                )
            assert job_error.value.orig.sqlstate == "42501"
    finally:
        await engine.dispose()
