"""Index refresh_tokens.expires_at for cleanup DELETE.

The cleanup ``DELETE FROM refresh_tokens WHERE expires_at < ...`` runs on
every successful token rotation (``backend/app/modules/auth/service.py``).
Without an index on ``expires_at`` this is a full table scan per refresh,
which degrades steadily with active-user count.

Closes v13.12 finding H-09 (db-audit HIGH-04).
"""

from typing import Union

from alembic import op


revision: str = "0008_refresh_tokens_expires_idx"
down_revision: Union[str, None] = "0007_map_edit_history"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # IF NOT EXISTS so deployments that already had the index hand-created
    # (or that were partially-applied during dev) don't fail; the index
    # itself is identical either way.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_refresh_tokens_expires_at "
        "ON catalog.refresh_tokens (expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_catalog_refresh_tokens_expires_at")
