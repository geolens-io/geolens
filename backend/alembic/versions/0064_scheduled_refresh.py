"""Preserve scheduled occurrence identity and admitted execution fences."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0064_scheduled_refresh"
down_revision = "0063_verified_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_key", sa.String(128), nullable=True),
        sa.Column("claim_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_binding_fingerprint", sa.String(128), nullable=True),
        sa.Column("local_edit_baseline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_policy", sa.String(64), nullable=True),
        sa.Column("credential_reference", sa.String(256), nullable=True),
        sa.Column("credential_version", sa.String(128), nullable=True),
    )
    for column in columns:
        op.add_column("dataset_refresh_runs", column, schema="catalog")
    op.drop_constraint(
        "chk_refresh_runs_trigger", "dataset_refresh_runs", schema="catalog"
    )
    op.create_check_constraint(
        "chk_refresh_runs_trigger",
        "dataset_refresh_runs",
        "trigger IN ('manual', 'api', 'cli', 'scheduled')",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_refresh_runs_scheduled_identity",
        "dataset_refresh_runs",
        "(trigger = 'scheduled' AND scheduled_for IS NOT NULL "
        "AND occurrence_key IS NOT NULL AND claim_deadline IS NOT NULL "
        "AND execution_key IS NOT NULL) "
        "OR (trigger <> 'scheduled' AND scheduled_for IS NULL)",
        schema="catalog",
    )
    op.create_index(
        "uq_refresh_runs_scheduled_occurrence",
        "dataset_refresh_runs",
        ["dataset_id", "scheduled_for"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("trigger = 'scheduled' AND scheduled_for IS NOT NULL"),
    )
    op.create_index(
        "uq_refresh_runs_execution_key",
        "dataset_refresh_runs",
        ["execution_key"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("execution_key IS NOT NULL"),
    )


def downgrade() -> None:
    # A downgrade must not strand an active execution whose identity it removes.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM catalog.dataset_refresh_runs "
        "WHERE execution_key IS NOT NULL AND status IN ('pending', 'running')) "
        "THEN RAISE EXCEPTION 'Stop admitted refreshes before downgrading'; "
        "END IF; END $$"
    )
    op.drop_index(
        "uq_refresh_runs_execution_key",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_index(
        "uq_refresh_runs_scheduled_occurrence",
        table_name="dataset_refresh_runs",
        schema="catalog",
    )
    op.drop_constraint(
        "chk_refresh_runs_scheduled_identity", "dataset_refresh_runs", schema="catalog"
    )
    op.drop_constraint(
        "chk_refresh_runs_trigger", "dataset_refresh_runs", schema="catalog"
    )
    op.execute(
        "UPDATE catalog.dataset_refresh_runs SET trigger = 'api' WHERE trigger = 'scheduled'"
    )
    op.create_check_constraint(
        "chk_refresh_runs_trigger",
        "dataset_refresh_runs",
        "trigger IN ('manual', 'api', 'cli')",
        schema="catalog",
    )
    for name in (
        "credential_version",
        "credential_reference",
        "verification_policy",
        "local_edit_baseline",
        "source_binding_fingerprint",
        "execution_key",
        "claim_deadline",
        "occurrence_key",
        "scheduled_for",
    ):
        op.drop_column("dataset_refresh_runs", name, schema="catalog")
