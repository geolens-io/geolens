"""Let PostgreSQL enforce "at most one embedding backfill in flight".

fix(#1542 review P1): the admin backfill endpoint refuses a second run while
one is in flight, because two concurrent force runs mean two ``DELETE FROM
catalog.record_embeddings``. That refusal was a SELECT followed by an INSERT,
which is a TOCTOU on exactly the guard that exists to prevent the destructive
case: two requests arriving together both pass the check and both create a job.
The check narrows the window; it does not close it, and it cannot, because
nothing in the application layer serializes two transactions in two processes.

A partial unique index moves the invariant into the database, where concurrent
inserts are decided by the index rather than by timing. The loser gets a unique
violation, which the route turns into the same 409 the check produces.

Deliberately NOT an advisory lock. ``pg_advisory_xact_lock`` releases at COMMIT
and the backfill commits per batch, so the lock would be gone for most of the
run; the session-level variant survives ROLLBACK, and SQLAlchemy's pool
reset-on-return IS a rollback, so the lock leaks onto a pooled connection
nobody can see and never comes back. Commit 898048b2 reverted exactly that
after it hung CI.

Shape:

- Key is ``tenant_id``, so hosted tenants do not lock each other out. The
  backfill only ever touches records the calling tenant can see.
- ``NULLS NOT DISTINCT`` (PG15+) is what makes it work in single-tenant mode,
  where every row's ``tenant_id`` is NULL. Under the default NULLS DISTINCT,
  two NULL keys are considered different and the index would permit exactly
  the concurrent pair it exists to refuse.
- The predicate restricts the index to backfill rows in a slot-holding status.
  Terminal rows drop out (an operator may run as many backfills in sequence as
  they like), and no other job type is touched — an upload and a backfill can
  be in flight together, as they always could.

Revision ID: 0050_one_active_embedding_backfill
Revises: 0049_records_attribution
Create Date: 2026-08-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0050_one_active_embedding_backfill"
down_revision: Union[str, None] = "0049_records_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_ingest_jobs_active_embedding_backfill"


def upgrade() -> None:
    # CONCURRENTLY is deliberately not used: it cannot run inside a
    # transaction, and every other index in this chain is built the plain way.
    # The predicate matches at most a handful of rows on any real instance —
    # active backfills — so the build is effectively instant.
    #
    # An instance that somehow already holds two active backfill rows would
    # fail this build. That is the correct outcome and the loud one: the state
    # is precisely the destructive overlap the index exists to prevent, and an
    # operator has to settle the duplicate rows before it can be enforced.
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON catalog.ingest_jobs (tenant_id)
        NULLS NOT DISTINCT
        WHERE (
            user_metadata ? 'embedding_backfill'
            AND status IN ('pending', 'running')
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS catalog.{_INDEX_NAME}")
