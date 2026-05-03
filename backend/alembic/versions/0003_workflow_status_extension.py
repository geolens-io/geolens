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
    op.execute(
        "ALTER TABLE catalog.records "
        "ADD CONSTRAINT chk_records_record_status "
        "CHECK (record_status IN ('draft', 'ready', 'internal', 'published'))"
    )
