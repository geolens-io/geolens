"""Add catalog.feature_create_keys for idempotent feature creates.

One row names the feature a user's ``Idempotency-Key`` created in a dataset, so
a retried create whose first attempt committed returns that feature instead of
inserting another. It records the newest attempt number whose body was applied,
which orders the bodies of retries, the ``xmin`` the feature row had after that
apply, which shows whether anyone else has written the row since, and the oid of
the dataset's data table, which a reupload swap or a registered-table overwrite
replaces, since the row's gid points into that table.

The row is written in the insert's own transaction and pruned after 24 hours.
It carries no tenant column, like ``dataset_assets``: rows are reached only
through a dataset the route has already authorized.

Revision ID: 0076_feature_create_keys
Revises: 0075_dataset_assets_retained_cog
Create Date: 2026-09-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0076_feature_create_keys"
down_revision: Union[str, None] = "0075_dataset_assets_retained_cog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.create_table(
        "feature_create_keys",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("gid", sa.BigInteger(), nullable=False),
        sa.Column("table_oid", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("row_xmin", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "dataset_id", "user_id", "key", name="uq_feature_create_keys_key"
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_feature_create_keys_user_id",
        "feature_create_keys",
        ["user_id"],
        schema="catalog",
    )
    op.create_index(
        "ix_feature_create_keys_created_at",
        "feature_create_keys",
        ["created_at"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feature_create_keys_created_at",
        table_name="feature_create_keys",
        schema="catalog",
    )
    op.drop_index(
        "ix_feature_create_keys_user_id",
        table_name="feature_create_keys",
        schema="catalog",
    )
    op.drop_table("feature_create_keys", schema="catalog")
