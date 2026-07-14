"""Tenant-isolate audit history and ingestion jobs.

``audit_logs`` and ``ingest_jobs`` predate the hosted tenant boundary.  They
are durable child records whose parent foreign keys may later become NULL, so
scoping them indirectly through the current user or dataset loses legitimate
history and leaves system-authored rows without any boundary at all.

This migration adds a durable nullable tenant key to both tables, backfills it
from the strongest available RLS parent, installs fail-closed policies and the
shared insert-stamping trigger, and enforces parent/child tenant agreement even
for privileged maintenance SQL.  The policies remain dormant after migration;
runtime enablement is still owned by ``apply_tenancy_rls()`` in multi-tenant
mode, preserving byte-identical single-tenant behavior.

Revision ID: 0022_tenant_audit_job_isolation
Revises: 0021_tenant_control_plane_hardening
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_tenant_audit_job_isolation"
down_revision: Union[str, None] = "0021_tenant_control_plane_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("audit_logs", "ingest_jobs")
_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"

_AUDIT_PARENT_TRIGGER = "trg_validate_audit_log_user_tenant"
_AUDIT_PARENT_FUNCTION = "catalog.enforce_audit_log_user_tenant"
_JOB_PARENT_TRIGGER = "trg_validate_ingest_job_parent_tenant"
_JOB_PARENT_FUNCTION = "catalog.enforce_ingest_job_parent_tenant"


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema="catalog",
        )

    # Actor-backed audit rows inherit the actor's tenant. Rows whose actor was
    # already deleted, plus historical system rows, remain NULL and therefore
    # fail closed when hosted RLS is enabled; there is no trustworthy tenant
    # source from which to infer their ownership retroactively.
    op.execute(
        """
        UPDATE catalog.audit_logs AS audit
        SET tenant_id = actor.tenant_id
        FROM catalog.users AS actor
        WHERE actor.id = audit.user_id
          AND audit.tenant_id IS DISTINCT FROM actor.tenant_id
        """
    )

    # A job may have both a creator and a dataset. Abort rather than choosing a
    # side if historical privileged writes linked parents from different
    # tenants: silently adopting either key would preserve a cross-tenant row.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM catalog.ingest_jobs AS job
                JOIN catalog.users AS creator ON creator.id = job.created_by
                JOIN catalog.datasets AS dataset ON dataset.id = job.dataset_id
                WHERE creator.tenant_id IS DISTINCT FROM dataset.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'cannot tenantize ingest_jobs with mismatched creator and dataset tenants'
                    USING ERRCODE = '42501';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        UPDATE catalog.ingest_jobs AS job
        SET tenant_id = creator.tenant_id
        FROM catalog.users AS creator
        WHERE creator.id = job.created_by
          AND job.tenant_id IS DISTINCT FROM creator.tenant_id
        """
    )
    op.execute(
        """
        UPDATE catalog.ingest_jobs AS job
        SET tenant_id = dataset.tenant_id
        FROM catalog.datasets AS dataset
        WHERE dataset.id = job.dataset_id
          AND job.created_by IS NULL
          AND job.tenant_id IS DISTINCT FROM dataset.tenant_id
        """
    )

    op.create_index(
        "ix_catalog_audit_logs_tenant_id",
        "audit_logs",
        ["tenant_id"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_ingest_jobs_tenant_id",
        "ingest_jobs",
        ["tenant_id"],
        schema="catalog",
    )

    for table in _TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON catalog.{table} "
            "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
        )
        op.execute(
            f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
        )

    # Keep the durable audit tenant when ON DELETE SET NULL clears user_id.
    # When an actor is present, derive or verify the child key against it.
    op.execute(
        f"""
        CREATE FUNCTION {_AUDIT_PARENT_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            actor_tenant uuid;
        BEGIN
            IF NEW.user_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT tenant_id INTO actor_tenant
            FROM catalog.users
            WHERE id = NEW.user_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Audit actor % does not exist', NEW.user_id
                    USING ERRCODE = '23503';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := actor_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM actor_tenant THEN
                RAISE EXCEPTION 'Audit log tenant does not match actor tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_AUDIT_PARENT_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF user_id, tenant_id ON catalog.audit_logs "
        f"FOR EACH ROW EXECUTE FUNCTION {_AUDIT_PARENT_FUNCTION}()"
    )

    # Jobs can outlive either nullable parent. Validate every parent that still
    # exists, require both parents to agree, and retain the durable key after
    # ON DELETE SET NULL removes the final parent reference.
    op.execute(
        f"""
        CREATE FUNCTION {_JOB_PARENT_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            creator_tenant uuid;
            dataset_tenant uuid;
            has_creator boolean := false;
            has_dataset boolean := false;
            parent_tenant uuid;
        BEGIN
            IF NEW.created_by IS NOT NULL THEN
                SELECT tenant_id INTO creator_tenant
                FROM catalog.users
                WHERE id = NEW.created_by;
                has_creator := FOUND;
                IF NOT has_creator THEN
                    RAISE EXCEPTION 'Ingest job creator % does not exist', NEW.created_by
                        USING ERRCODE = '23503';
                END IF;
            END IF;

            IF NEW.dataset_id IS NOT NULL THEN
                SELECT tenant_id INTO dataset_tenant
                FROM catalog.datasets
                WHERE id = NEW.dataset_id;
                has_dataset := FOUND;
                IF NOT has_dataset THEN
                    RAISE EXCEPTION 'Ingest job dataset % does not exist', NEW.dataset_id
                        USING ERRCODE = '23503';
                END IF;
            END IF;

            IF has_creator AND has_dataset
               AND creator_tenant IS DISTINCT FROM dataset_tenant THEN
                RAISE EXCEPTION
                    'Ingest job creator and dataset belong to different tenants'
                    USING ERRCODE = '42501';
            END IF;

            IF has_creator THEN
                parent_tenant := creator_tenant;
            ELSIF has_dataset THEN
                parent_tenant := dataset_tenant;
            ELSE
                RETURN NEW;
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := parent_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM parent_tenant THEN
                RAISE EXCEPTION 'Ingest job tenant does not match parent tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_JOB_PARENT_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF created_by, dataset_id, tenant_id "
        "ON catalog.ingest_jobs "
        f"FOR EACH ROW EXECUTE FUNCTION {_JOB_PARENT_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_JOB_PARENT_TRIGGER} ON catalog.ingest_jobs")
    op.execute(f"DROP FUNCTION IF EXISTS {_JOB_PARENT_FUNCTION}()")
    op.execute(f"DROP TRIGGER IF EXISTS {_AUDIT_PARENT_TRIGGER} ON catalog.audit_logs")
    op.execute(f"DROP FUNCTION IF EXISTS {_AUDIT_PARENT_FUNCTION}()")

    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {_STAMP_TRIGGER} ON catalog.{table}")
        op.execute(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON catalog.{table}")

    op.drop_index(
        "ix_catalog_ingest_jobs_tenant_id",
        table_name="ingest_jobs",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_audit_logs_tenant_id",
        table_name="audit_logs",
        schema="catalog",
    )
    for table in reversed(_TABLES):
        op.drop_column(table, "tenant_id", schema="catalog")
