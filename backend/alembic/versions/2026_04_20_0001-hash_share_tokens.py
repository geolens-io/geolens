"""Hash share tokens — replace plaintext token with token_hash + token_hint.

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
Create Date: 2026-04-20 01:00:00.000000

"""

import hashlib

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k8l9m0n1o2p3"
down_revision = "j7k8l9m0n1o2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column(
        "map_share_tokens",
        sa.Column("token_hash", sa.Text(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "map_share_tokens",
        sa.Column("token_hint", sa.Text(), nullable=True),
        schema="catalog",
    )

    # Populate from existing plaintext tokens
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, token FROM catalog.map_share_tokens")
    ).fetchall()
    for row in rows:
        token_hash = hashlib.sha256(row.token.encode()).hexdigest()
        token_hint = row.token[:8]
        conn.execute(
            sa.text(
                "UPDATE catalog.map_share_tokens "
                "SET token_hash = :hash, token_hint = :hint "
                "WHERE id = :id"
            ),
            {"hash": token_hash, "hint": token_hint, "id": row.id},
        )

    # Make columns non-nullable, add unique constraint, drop old column
    op.alter_column(
        "map_share_tokens",
        "token_hash",
        nullable=False,
        schema="catalog",
    )
    op.alter_column(
        "map_share_tokens",
        "token_hint",
        nullable=False,
        schema="catalog",
    )
    op.create_unique_constraint(
        "uq_map_share_tokens_token_hash",
        "map_share_tokens",
        ["token_hash"],
        schema="catalog",
    )
    op.drop_constraint(
        "map_share_tokens_token_key",
        "map_share_tokens",
        type_="unique",
        schema="catalog",
    )
    op.drop_column("map_share_tokens", "token", schema="catalog")


def downgrade() -> None:
    # Re-add plaintext column (tokens are unrecoverable — fill with hints)
    op.add_column(
        "map_share_tokens",
        sa.Column("token", sa.Text(), nullable=True),
        schema="catalog",
    )
    op.execute(
        sa.text(
            "UPDATE catalog.map_share_tokens SET token = token_hint"
        )
    )
    op.alter_column(
        "map_share_tokens", "token", nullable=False, schema="catalog"
    )
    op.create_unique_constraint(
        "map_share_tokens_token_key",
        "map_share_tokens",
        ["token"],
        schema="catalog",
    )
    op.drop_constraint(
        "uq_map_share_tokens_token_hash",
        "map_share_tokens",
        type_="unique",
        schema="catalog",
    )
    op.drop_column("map_share_tokens", "token_hint", schema="catalog")
    op.drop_column("map_share_tokens", "token_hash", schema="catalog")
