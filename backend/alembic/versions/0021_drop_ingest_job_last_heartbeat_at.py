"""Drop catalog.ingest_jobs.last_heartbeat_at — IA-P0-04 option (b).

The column was declared (`models.py`) and queried (`worker.py:recover_stale_jobs`)
but never written by any code path — `grep -rn "last_heartbeat_at\\s*="` in
backend/app is empty. This collapsed the stale-recovery query to effectively
``created_at < now() - 5min`` and force-killed any running ingest >5 minutes
old across every rolling deploy.

Phase 1067 option (b): drop the column and rely on
``platform/jobs/router.fail_stale_jobs`` (already invoked every 5 minutes by
the lifespan ``_stale_jobs_sweeper`` task in ``api/main.py``) using the
existing ``JOB_TIMEOUT_SECONDS = 3600`` cutoff. ``recover_stale_jobs`` on
worker startup is updated to use the same ``started_at < cutoff`` criterion.

Upgrade: drops ``catalog.ingest_jobs.last_heartbeat_at``.
Downgrade: re-adds the column as nullable, default NULL (matching pre-fix shape).
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_drop_ingest_job_last_heartbeat_at"
down_revision: Union[str, None] = "0020_records_simple_search_vector_idx"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.drop_column("ingest_jobs", "last_heartbeat_at", schema="catalog")


def downgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="catalog",
    )
