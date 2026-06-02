"""Relax record_status for workflow extensions.

Revision ID: 0003_workflow_status_extension
Revises: 0002_procrastinate
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_workflow_status_extension"
down_revision: Union[str, None] = "0002_procrastinate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.records "
        "DROP CONSTRAINT IF EXISTS chk_records_record_status"
    )


def downgrade() -> None:
    # DS-1: this migration's upgrade() DROPs the record_status CHECK entirely,
    # so the column may hold workflow-extension statuses beyond the original
    # narrow set ('draft','ready','internal','published'). Before re-imposing
    # the narrow constraint we must demote any out-of-set rows, otherwise
    # ADD CONSTRAINT validates against existing rows and aborts the downgrade
    # with a confusing constraint-violation error (cf. the 0018 WR-03 fix).
    #
    # 'draft' is the safe fallback: it is the canonical column default
    # (models.py: default="draft") and the most conservative lifecycle state,
    # so demoted rows are hidden rather than silently elevated to published.
    op.execute(
        "UPDATE catalog.records SET record_status = 'draft' "
        "WHERE record_status NOT IN ('draft', 'ready', 'internal', 'published')"
    )
    op.execute(
        "ALTER TABLE catalog.records "
        "DROP CONSTRAINT IF EXISTS chk_records_record_status"
    )
    op.execute(
        "ALTER TABLE catalog.records "
        "ADD CONSTRAINT chk_records_record_status "
        "CHECK (record_status IN ('draft', 'ready', 'internal', 'published'))"
    )
