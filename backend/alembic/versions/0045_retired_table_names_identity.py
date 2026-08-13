"""Record the freed relation's identity and its prior owner on a tombstone.

fix(#1456). ``catalog.retired_table_names`` recorded only the freed NAME. Two
review findings on #1453 converge on the same gap: a tombstone cannot tell
"the table I detached" from "a new table wearing its name", and it cannot say
who owned the dataset that freed it. Both answers have to be captured inside
the delete transaction, because both sources die in it — the relation is
dropped, and the ``catalog.records`` row carrying ``created_by`` is deleted.

This migration only makes the data exist. Nothing reads the new columns yet;
the tombstone-vs-not decision is unchanged and still keyed on whether the
delete freed the name.

``relation_oid`` is BIGINT, not INTEGER: a pg_class oid is an unsigned 32-bit
value, so int4 overflows on any oid past 2^31 and a cluster that has churned
enough objects hands those out. It is forensic identity within ONE cluster
lifetime and nothing more — oids are not preserved by pg_dump/pg_restore, so
every row here reads as a stale oid on the far side of the RUNBOOK's backup
and restore path. The durable half of the identity is ``previous_owner_id``.

``previous_owner_id`` is deliberately NOT a foreign key to ``catalog.users``.
This table is retain-forever, and an FK gives only bad options: ON DELETE
CASCADE would erase tombstones when a user is deleted (silently re-arming
GH-1443 for every name that user's datasets freed), RESTRICT would let a
tombstone block a user deletion, and SET NULL would quietly discard the one
durable half of the identity. The same reasoning already governs the
``dataset_id`` column beside it, whose referent is deleted in the very
transaction that writes the row.

Both columns are nullable and no backfill is attempted, because none is
possible by construction. Every pre-existing tombstone was written after its
relation was dropped and its record row deleted, so neither value survives
anywhere to be recovered. NULL means "not recorded", not "no owner" — a
consumer must treat a NULL as unknown, never as a match.

Revision ID: 0045_retired_table_names_identity
Revises: 0044_retired_table_names
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_retired_table_names_identity"
down_revision: Union[str, None] = "0044_retired_table_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "retired_table_names",
        sa.Column("relation_oid", sa.BigInteger(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "retired_table_names",
        sa.Column("previous_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="catalog",
    )
    # No index on either column. Nothing queries them yet, and the probe this
    # table exists to serve is still the name lookup that
    # ix_retired_table_names_table_name backs. A reader that later matches on
    # identity reaches these columns through that same name row.


def downgrade() -> None:
    op.drop_column("retired_table_names", "previous_owner_id", schema="catalog")
    op.drop_column("retired_table_names", "relation_oid", schema="catalog")
