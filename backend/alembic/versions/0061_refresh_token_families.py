"""Track refresh families and first rotation without discarding replay evidence.

Legacy rows have no recoverable lineage; each starts its own family. Existing
shortened expiries stay intact and are never extended by this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0061_refresh_token_families"
down_revision = "0060_dataset_publication_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "family_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        schema="catalog",
    )
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "rotated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], schema="catalog"
    )


def downgrade() -> None:
    # Old servers know only revoked/expiry: dropping rotation timestamps alone
    # would reactivate spent credentials until their original expiry.
    refresh_tokens = sa.table(
        "refresh_tokens",
        sa.column("revoked"),
        sa.column("rotated_at"),
        schema="catalog",
    )
    op.execute(
        refresh_tokens.update()
        .where(refresh_tokens.c.rotated_at.is_not(None))
        .values(revoked=True)
    )
    op.drop_index(
        "ix_refresh_tokens_family_id", table_name="refresh_tokens", schema="catalog"
    )
    op.drop_column("refresh_tokens", "rotated_at", schema="catalog")
    op.drop_column("refresh_tokens", "family_id", schema="catalog")
