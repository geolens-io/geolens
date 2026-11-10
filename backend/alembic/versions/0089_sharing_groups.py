"""Sharing groups and their members.

``groups`` holds named sets of users that admins create; ``group_members``
links users to them. ``tenant_id`` is nullable with no FK, and the name has a
global and a per-tenant partial unique index, the column and index pattern
``collections`` and ``users`` use. Unlike those tables, neither has a stamping
trigger or an RLS policy.

Revision ID: 0089_sharing_groups
Revises: 0088_dataset_kept_versions
Create Date: 2026-10-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0089_sharing_groups"
down_revision: Union[str, None] = "0088_dataset_kept_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "uq_groups_name_global",
        "groups",
        ["name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_groups_name_tenant",
        "groups",
        ["tenant_id", "name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_table(
        "group_members",
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_group_members_user_id",
        "group_members",
        ["user_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_group_members_user_id", table_name="group_members", schema="catalog"
    )
    op.drop_table("group_members", schema="catalog")
    op.drop_index("uq_groups_name_tenant", table_name="groups", schema="catalog")
    op.drop_index("uq_groups_name_global", table_name="groups", schema="catalog")
    op.drop_table("groups", schema="catalog")
