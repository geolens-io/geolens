"""Let PostgreSQL enforce one terminal audit entry per embedding backfill run.

fix(#1550 review): three actors can close a backfill's audit trail — the
worker, the status poll and the stale sweeper — and more than one can be right
about the same run. The first attempt at idempotency was a read-before-write
existence check, which is a check-then-insert: two actors both read "no
terminal entry yet", both insert, and the trail ends up with two conflicting
terminal outcomes, or the wrong one wins.

That is the same race this change already replaced on the job row with
``uq_ingest_jobs_active_embedding_backfill``. A uniqueness invariant belongs in
the schema, because every application-level version of it is a window.

Scope: the predicate pins ``action = 'embedding.backfill'``, so no other audit
action and no other job type is constrained — the audit log stays append-only
for everything else, including the ``requested`` entry this run's route writes,
which the predicate deliberately excludes so a run can still record that it was
asked for AND how it ended.

An instance already holding two terminal entries for one run would fail this
build. That is the loud outcome and the correct one: it is exactly the state
the index exists to prevent, and an operator has to settle the duplicates
first.

Revision ID: 0051_one_terminal_backfill_audit
Revises: 0050_one_active_embedding_backfill
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0051_one_terminal_backfill_audit"
down_revision: Union[str, None] = "0050_one_active_embedding_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_audit_logs_terminal_embedding_backfill"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON catalog.audit_logs ((details ->> 'job_id'))
        WHERE (
            action = 'embedding.backfill'
            AND details ->> 'outcome' <> 'requested'
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS catalog.{_INDEX_NAME}")
