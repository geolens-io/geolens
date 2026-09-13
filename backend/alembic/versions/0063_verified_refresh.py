"""Record refresh verification and blocked publication decisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063_verified_refresh"
down_revision = "0062_record_modified_clock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dataset_refresh_runs",
        sa.Column("verification", postgresql.JSONB(), nullable=True),
        schema="catalog",
    )
    op.drop_constraint(
        "chk_refresh_runs_status", "dataset_refresh_runs", schema="catalog"
    )
    op.create_check_constraint(
        "chk_refresh_runs_status",
        "dataset_refresh_runs",
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')",
        schema="catalog",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE catalog.dataset_refresh_runs SET status = 'failed' "
        "WHERE status = 'blocked'"
    )
    op.drop_constraint(
        "chk_refresh_runs_status", "dataset_refresh_runs", schema="catalog"
    )
    op.create_check_constraint(
        "chk_refresh_runs_status",
        "dataset_refresh_runs",
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
        schema="catalog",
    )
    op.drop_column("dataset_refresh_runs", "verification", schema="catalog")
