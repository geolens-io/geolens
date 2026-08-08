"""Add catalog.dataset_refresh_runs.

feat(#1219) / ADR-002 Decision 4. One durable row per refresh attempt,
created at dispatch and finalized by the worker, so a refresh that never
committed still leaves a trace. Terminal ``ingest_jobs`` rows are purged after
``ingest_jobs_retention_days``, which is why the jobs table cannot be the
record of refreshes and why ``ingest_job_id`` is ON DELETE SET NULL: the run
survives the purge and only the link goes.

No backfill. Nothing before this migration recorded a refresh outcome, so
every historical row would be invented. ``dataset_versions`` is a success
ledger and says nothing about attempts that failed, which is exactly the half
this table exists to hold.

Revision ID: 0037_dataset_refresh_runs
Revises: 0036_dataset_source_state
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_dataset_refresh_runs"
down_revision: Union[str, None] = "0036_dataset_source_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_refresh_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        # TSEAM-01 dormant tenant_id: nullable, no FK enforcement, no RLS
        # policy. This table is NOT in migration 0018's stamping-trigger set,
        # so the value is written explicitly at run creation from the parent
        # dataset's stored column. RLS enablement belongs to #998; no table in
        # this database has it turned on today.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ingest_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin_kind", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # When the worker began executing, distinct from started_at (dispatch)
        # and finished_at (outcome). Queue wait is claimed_at - started_at;
        # conflating any two of the three loses that measurement.
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_count_before", sa.BigInteger(), nullable=True),
        sa.Column("feature_count_after", sa.BigInteger(), nullable=True),
        sa.Column("schema_diff", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="dataset_refresh_runs_pkey"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["catalog.datasets.id"],
            name="dataset_refresh_runs_dataset_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["catalog.dataset_versions.id"],
            name="dataset_refresh_runs_dataset_version_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ingest_job_id"],
            ["catalog.ingest_jobs.id"],
            name="dataset_refresh_runs_ingest_job_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by"],
            ["catalog.users.id"],
            name="dataset_refresh_runs_triggered_by_fkey",
            ondelete="SET NULL",
        ),
        # 'blocked' is the reserved future spelling for a run refused on
        # schema policy; v1 has no policy, so the state is unreachable and
        # shipping it would invite dead handling code.
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="chk_refresh_runs_status",
        ),
        # 'scheduled' is excluded because nothing schedules (gate 4). Whoever
        # adds it must add scheduled_for and its UNIQUE (dataset_id,
        # scheduled_for) partial index in the SAME migration, or a scheduled
        # occurrence loses the durable identity invariant 8 requires.
        sa.CheckConstraint(
            "trigger IN ('manual', 'api', 'cli')",
            name="chk_refresh_runs_trigger",
        ),
        sa.CheckConstraint(
            "origin_kind IN ('upload', 'postgis', 'service', 'stac', 'raster')",
            name="chk_refresh_runs_origin_kind",
        ),
        schema="catalog",
    )
    # Admission control, in the schema rather than in a check-then-insert.
    # ADR-002 Decision 5b says at most one mutation per dataset at a time and
    # that v1 REJECTS a concurrent trigger with 409 dataset_busy. Enforcing it
    # with a partial unique index makes the decision atomic at request time:
    # the loser of a race gets an IntegrityError the dispatch handler turns
    # into that 409, instead of two runs both reaching the worker and
    # discovering each other at the advisory lock.
    op.create_index(
        "uq_refresh_runs_one_active",
        "dataset_refresh_runs",
        ["dataset_id"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_index(
        "ix_dataset_refresh_runs_dataset_started",
        "dataset_refresh_runs",
        ["dataset_id", "started_at"],
        schema="catalog",
    )
    # The three nullable FKs each need a leading index of their own or a
    # parent delete degrades to a full child scan
    # (tests/test_fk_support_indexes_database.py). Partial on IS NOT NULL,
    # matching ix_dataset_versions_uploaded_by: a NULL references nothing.
    op.create_index(
        "ix_dataset_refresh_runs_version",
        "dataset_refresh_runs",
        ["dataset_version_id"],
        schema="catalog",
        postgresql_where=sa.text("dataset_version_id IS NOT NULL"),
    )
    op.create_index(
        "ix_dataset_refresh_runs_job",
        "dataset_refresh_runs",
        ["ingest_job_id"],
        schema="catalog",
        postgresql_where=sa.text("ingest_job_id IS NOT NULL"),
    )
    op.create_index(
        "ix_dataset_refresh_runs_triggered_by",
        "dataset_refresh_runs",
        ["triggered_by"],
        schema="catalog",
        postgresql_where=sa.text("triggered_by IS NOT NULL"),
    )

    # fix(#1274 review): the admission index can only referee runs that HAVE
    # rows. Reupload tasks queued or claimed by pre-migration code have none,
    # so without a backfill the index would see their dataset as idle and
    # admit a concurrent post-deploy refresh while the old durable task can
    # still reach the swap. Give every genuinely in-flight legacy reupload
    # job — claimed, or dispatched with an attempt token — a `running` row
    # here. The rows are finalized by the same machinery as native ones (the
    # worker keys on ingest_job_id; the stale sweep cancels any whose job
    # died with the old deploy). DISTINCT ON keeps the newest per dataset so
    # a pathological double cannot violate the one-active index and abort
    # the upgrade. Jobs dispatched by still-draining pre-migration API pods
    # AFTER this statement stay unrefereed for the minutes those pods live;
    # that window was equally unprotected before this table existed, so the
    # backfill removes the regression without claiming to rewrite history.
    op.execute(
        sa.text(
            """
            INSERT INTO catalog.dataset_refresh_runs
                (id, dataset_id, tenant_id, ingest_job_id, origin_kind,
                 trigger, status, triggered_by, started_at, created_at)
            SELECT gen_random_uuid(), s.dataset_id, s.tenant_id, s.job_id,
                   s.origin_kind, 'manual', 'running', s.created_by,
                   s.job_created_at, now()
            FROM (
                SELECT DISTINCT ON (j.dataset_id)
                       j.dataset_id,
                       d.tenant_id,
                       j.id AS job_id,
                       CASE WHEN j.source_url IS NOT NULL
                                 AND j.file_path IS NULL
                            THEN 'service' ELSE 'upload' END AS origin_kind,
                       j.created_by,
                       j.created_at AS job_created_at
                FROM catalog.ingest_jobs j
                JOIN catalog.datasets d ON d.id = j.dataset_id
                WHERE (j.user_metadata->>'reupload') = 'true'
                  AND (
                        j.status = 'running'
                        OR (j.status = 'pending' AND j.attempt_id IS NOT NULL)
                  )
                  -- Idempotent, and safe beside any row the new code already
                  -- wrote: a dataset with an active run needs no referee.
                  AND NOT EXISTS (
                      SELECT 1 FROM catalog.dataset_refresh_runs r
                      WHERE r.dataset_id = j.dataset_id
                        AND r.status IN ('pending', 'running')
                  )
                ORDER BY j.dataset_id, j.created_at DESC
            ) AS s
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dataset_refresh_runs_triggered_by",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_index(
        "ix_dataset_refresh_runs_job",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_index(
        "ix_dataset_refresh_runs_version",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_index(
        "ix_dataset_refresh_runs_dataset_started",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_index(
        "uq_refresh_runs_one_active",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_table("dataset_refresh_runs", schema="catalog")
