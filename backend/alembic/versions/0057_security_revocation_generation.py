"""Cluster-global revocation generation for cross-worker cache invalidation.

fix(#1778 codex r3/r4). ``RedisCacheProvider``'s in-memory fallback and its
authoritative-replay queue are PROCESS-local, and production runs several
Uvicorn workers. During a Redis outage worker A could revoke an embed token and
queue the denial in A alone, while worker B held a positive for the same token;
after recovery B could still read the pre-revocation positive out of Redis.
Nothing process-local can close that, because the two workers share no memory.

This counter is the shared, durable fact they can both consult. Every revocation
advances it, every positive validation-cache entry is stamped with the
generation it was minted under, and a validator whose stamp is behind refuses
the entry and re-reads the database.

A single-row TABLE, not a sequence (fix(#1778 codex r4)). The first draft used a
sequence because ``nextval`` takes no row lock, but ``nextval`` is also
non-transactional, and that is fatal here rather than convenient: the advance
became visible to every other worker the instant it ran, while the ``is_active``
flip it stood for stayed invisible until the revoking transaction committed. A
validator landing in that window read the NEW generation, read the token row as
still active, and cached a positive stamped with the new generation, which then
survived the commit. Ordering the publish after the commit only narrows the
window; making the counter transactional removes it, because the generation and
the ``is_active`` flip become visible in the same instant, to everyone.

The cost is that concurrent revocations serialize on this row. They already
serialize on the embed-token rows they are flipping, they are rare, and every
revoke path reaches this row in the same order (token flips first, counter
second), so the added lock introduces no new cycle.

DELIBERATELY OUTSIDE THE RLS BOUNDARY, like ``arcgis_signin_attempts`` (0056).
The value of the counter is that every worker, and in hosted mode every tenant's
request path, agrees on one number; a per-tenant view of it would let a revoke
in one tenant leave another's stale positives standing, which is the defect this
closes rather than a refinement of it. It holds nothing tenant-identifying and
nothing secret. It is a counter.

Revision ID: 0057_security_revocation_generation
Revises: 0056_arcgis_signin_attempts
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_security_revocation_generation"
down_revision: Union[str, None] = "0056_arcgis_signin_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "security_revocation_generation"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        # A one-row table: the CHECK plus the primary key make a second row
        # impossible to insert, so no reader has to ask which row it wants.
        sa.Column(
            "id",
            sa.Boolean(),
            primary_key=True,
            server_default=sa.true(),
        ),
        sa.Column(
            "generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint("id IS TRUE", name="ck_security_revocation_generation_one"),
        schema="catalog",
    )
    # Seed the row here rather than lazily: a reader that finds no row cannot
    # tell "never revoked" from "counter missing", and the safe answer to the
    # second is to refuse every cached positive.
    # fix(#1778 codex r5): seeded from the clock, not from 1. The reader
    # re-creates this row if it is ever deleted, and a re-seed that restarted at
    # 1 would walk back up through values that cache entries elsewhere in the
    # fleet are still stamped with, making a revoked entry compare equal again.
    # An epoch seed puts every (re-)seed far above any counter that reached its
    # value by counting revocations, so issued values never repeat.
    #
    # The COLUMN default stays 1: it is never used, since every row this table
    # will ever hold is inserted right here, and keeping it a literal is what
    # lets the ORM model in core/db/models.py match for `alembic check`.
    op.execute(
        f"INSERT INTO catalog.{_TABLE} (id, generation) "
        "VALUES (TRUE, EXTRACT(EPOCH FROM clock_timestamp())::bigint) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table(_TABLE, schema="catalog")
