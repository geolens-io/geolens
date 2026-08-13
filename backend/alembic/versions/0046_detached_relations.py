"""Record a relation GeoLens released a claim on while it was still standing.

fix(#1456 review round 1). 0045 stamped the freed relation's identity onto the
tombstone, which covers every delete that RELEASES a name. It does not cover
the case #1456's window 1 is actually about: a detach that leaves the
operator's table standing writes no tombstone at all, so the oid and the prior
owner were probed and then discarded. If the operator drops that relation after
the delete commits, the name goes free with nothing recorded anywhere, which is
precisely the window the identity was collected to let a later change close.

Both values are as unrecoverable here as they are on the freed paths: the
record row carrying ``created_by`` dies in the delete transaction, and the oid
dies with the relation whenever the operator gets around to dropping it.

A SIBLING TABLE, not a flag on ``catalog.retired_table_names``. That table's
entire API is set membership: ``generate_table_name`` asks "is this name
retired?" and ``register_existing_table`` refuses any name that answers yes.
A row recording a relation that still holds its name is not a prohibition, and
putting one in that set would either burn the operator's own table name (if the
readers ignore the discriminator) or make every future reader responsible for
remembering a predicate whose failure direction is silent. GH-1456 sanctioned
either shape; this is the one that cannot be read wrong. Nothing reads this
table yet.

Shape mirrors 0044 deliberately, including its reasoning:

* Retention is FOREVER. A detach is rarer than a delete and the row is one name
  plus three ids.
* No unique constraint. The same table can be registered and detached any
  number of times, and a duplicate must never be able to fail a delete.
* ``tenant_id`` is the dormant TSEAM-01 shape: nullable, no FK, no RLS policy,
  written from the deleted dataset's own column.
* ``dataset_id`` and ``previous_owner_id`` carry no foreign keys. The dataset is
  deleted in the transaction that writes this row, and an FK to
  ``catalog.users`` would let a retain-forever row block a user deletion or be
  cascaded away by one. See 0045 for the full argument.
* ``relation_oid`` is BIGINT (a pg_class oid is unsigned 32-bit) and identifies
  the relation for one cluster lifetime only, since pg_dump/pg_restore does not
  preserve oids. It is nullable even though the only write site reaches it with
  a non-null oid, because a NOT NULL here could turn a surprise into a FAILED
  DELETE, and no record is worth that.

The index on ``table_name`` matches 0044's. Nothing queries this table today,
but every plausible consumer arrives by name, the write happens at most once
per dataset delete, and adding the index later means migrating a table that has
been accumulating since this deploy.

Revision ID: 0046_detached_relations
Revises: 0045_retired_table_names_identity
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046_detached_relations"
down_revision: Union[str, None] = "0045_retired_table_names_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "detached_relations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Same width as catalog.datasets.table_name, which is what this copies.
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relation_oid", sa.BigInteger(), nullable=True),
        sa.Column("previous_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "detached_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="detached_relations_pkey"),
        schema="catalog",
    )
    op.create_index(
        "ix_detached_relations_table_name",
        "detached_relations",
        ["table_name"],
        schema="catalog",
    )

    # No backfill, and none is possible. Every detach before this migration
    # left the relation standing and recorded nothing, so its oid is knowable
    # only while that relation survives and its owner is already gone with the
    # record row. Relations detached before this deploy stay unidentified.


def downgrade() -> None:
    op.drop_index(
        "ix_detached_relations_table_name",
        table_name="detached_relations",
        schema="catalog",
    )
    op.drop_table("detached_relations", schema="catalog")
