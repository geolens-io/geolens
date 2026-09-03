"""Cluster-global revocation generation for cross-worker cache invalidation.

fix(#1778 codex r3). ``RedisCacheProvider``'s in-memory fallback and its
authoritative-replay queue are PROCESS-local, and production runs several
Uvicorn workers. During a Redis outage worker A could revoke an embed token and
queue the denial in A alone, while worker B held a positive for the same token;
after recovery B could still read the pre-revocation positive out of Redis
before A's replay landed. Nothing process-local can close that, because the two
workers share no memory.

This sequence is the shared, durable fact they can both consult. Every
revocation bumps it; every positive validation-cache entry is stamped with the
generation it was minted under; a validator whose stamp is behind the current
generation refuses the entry and re-reads the database. A revoke that happens
during an outage still lands here, because the database is the one thing that
stays up when Redis does not.

A SEQUENCE rather than a counter row, for three reasons. ``nextval`` takes no
row lock, so a revocation storm does not serialize on it. It is
non-transactional, so a revoke whose transaction later rolls back still leaves
the generation bumped: the consequence is that some cached positives are
re-validated against the database once, which is the harmless direction to be
wrong in. And it needs no ORM model, so it stays out of the mapper registry and
out of ``make alembic-check``'s comparison, which is correct because nothing
maps it.

DELIBERATELY OUTSIDE THE RLS BOUNDARY, like ``arcgis_signin_attempts`` (0056).
A sequence has no rows to which a policy could attach, and a per-tenant view of
it would defeat the purpose: the point is one number every worker agrees on. It
holds nothing tenant-identifying and nothing secret. It is a counter.

Revision ID: 0057_security_revocation_generation
Revises: 0056_arcgis_signin_attempts
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0057_security_revocation_generation"
down_revision: Union[str, None] = "0056_arcgis_signin_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEQUENCE = "catalog.security_revocation_generation"


def upgrade() -> None:
    # START WITH 1 so a deployment that has never revoked anything still reads a
    # stable value, and every cache entry minted before the first revoke carries
    # that same stamp.
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE} AS bigint START WITH 1")


def downgrade() -> None:
    op.execute(f"DROP SEQUENCE IF EXISTS {_SEQUENCE}")
