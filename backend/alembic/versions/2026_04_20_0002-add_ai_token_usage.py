"""Add AI token usage tracking table.

Revision ID: q3r4s5t6u7v8
Revises: k8l9m0n1o2p3
Create Date: 2026-04-20 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "q3r4s5t6u7v8"
down_revision = "k8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_token_usage",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("catalog.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subsystem", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="catalog",
    )
    # Index for per-user cost queries
    op.create_index(
        "ix_ai_token_usage_user_created",
        "ai_token_usage",
        ["user_id", "created_at"],
        schema="catalog",
    )
    # Index for subsystem-level aggregation
    op.create_index(
        "ix_ai_token_usage_subsystem_created",
        "ai_token_usage",
        ["subsystem", "created_at"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_token_usage_subsystem_created",
        table_name="ai_token_usage",
        schema="catalog",
    )
    op.drop_index(
        "ix_ai_token_usage_user_created",
        table_name="ai_token_usage",
        schema="catalog",
    )
    op.drop_table("ai_token_usage", schema="catalog")
