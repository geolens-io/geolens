"""Add catalog.retired_table_names — physical table names never handed out twice.

fix(#1443). ``generate_table_name`` collided only against LIVE catalog rows
and LIVE relations, so deleting a dataset freed its physical table name for the
next dataset to draw. GH-1429 closed the tile-*bytes* half of that by keying
tile caches on the dataset id, but the tile router's ``table_name -> metadata``
map cannot be closed the same way: the vector tile route is addressed by table
name, the dataset id is the RESULT of that lookup, and the cached entry is what
decides authorization (visibility, record_status, created_by). A worker holding
a pre-delete entry authorizes an anonymous caller against the DELETED dataset's
``public`` visibility and then queries a table the successor now owns.

Propagating the eviction is not available in the supported topologies: Redis is
unset by default and PostgreSQL LISTEN/NOTIFY needs a session-pinned connection
that transaction-mode PgBouncer does not provide. This table removes the
precondition instead — a name recorded here is never redrawn, so a stale entry
can only ever describe the dataset it was cached for.

Retention is FOREVER, deliberately. A row is one name plus two ids, written
once per deleted dataset, and its whole job is to be older than any cache.
Expiring rows would re-open the window on exactly the names most likely to
still be cached. A deployment that deletes a thousand datasets a day
accumulates well under a megabyte a year.

Not unique: one row per retirement, not per name. Nothing in the schema
promises a name reaches this table only once — a future recording site, an
operator insert, a restore that merges two catalogs — and a unique constraint
would turn every one of those into a FAILED DELETE, which is the one outcome
this table must never cause. The probe is a set-membership test, so duplicates
cost nothing and buy an unconditional write.

Revision ID: 0044_retired_table_names
Revises: 0043_vrt_generations_staged_source_ids
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_retired_table_names"
down_revision: Union[str, None] = "0043_vrt_generations_staged_source_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retired_table_names",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Same width as catalog.datasets.table_name, which is what every row
        # here is a copy of.
        sa.Column("table_name", sa.String(length=255), nullable=False),
        # TSEAM-01 dormant tenant_id: nullable, no FK enforcement, no RLS
        # policy, and not in migration 0018's stamping-trigger set — the same
        # shape 0037_dataset_refresh_runs uses. Written explicitly from the
        # deleted dataset's own column, and READ by the collision probe, which
        # binds a name to its own tenant plus the NULL scope. That mirrors
        # migration 0020's per-tenant uniqueness on datasets.table_name: names
        # are already per-tenant everywhere it matters, so retiring one
        # globally would cost unrelated tenants suffixes for nothing. Rows
        # written before a single -> multi transition carry NULL and nothing
        # back-stamps them, which is why NULL binds in every scope.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Diagnostic only, and deliberately NOT a foreign key: the row it
        # names is deleted in the same transaction that writes this one, so an
        # FK would either cascade the tombstone away or refuse the delete. It
        # exists so an operator asking "why is `roads` taken?" can correlate
        # with the audit log. The security-load-bearing content is table_name.
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "retired_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="retired_table_names_pkey"),
        schema="catalog",
    )
    # Backs the prefix probe in generate_table_name. Plain btree on the bare
    # column, matching uq_datasets_table_name_global, which backs the
    # identical LIKE against catalog.datasets.
    op.create_index(
        "ix_retired_table_names_table_name",
        "retired_table_names",
        ["table_name"],
        schema="catalog",
    )

    # No backfill is possible and none is pretended. Nothing before this
    # migration recorded a deleted dataset's table name, so every name freed
    # in the past is already gone from the catalog and cannot be recovered.
    # Names freed BEFORE this deploy therefore stay redrawable exactly once
    # more; the caches that made that dangerous have long since expired.


def downgrade() -> None:
    op.drop_index(
        "ix_retired_table_names_table_name",
        table_name="retired_table_names",
        schema="catalog",
    )
    op.drop_table("retired_table_names", schema="catalog")
