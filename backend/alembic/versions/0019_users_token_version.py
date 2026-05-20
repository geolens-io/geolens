"""Add token_version column to catalog.users for JWT revocation.

When a user logs out or changes their password, `token_version` is
incremented. Any access JWT carrying an older `token_version` value
is rejected on the next request, closing the logout-doesn't-invalidate-
access-JWT gap (SEC-S15 / Phase 1062-01, CVSS 4.3).

Upgrade: adds `token_version INTEGER NOT NULL DEFAULT 1` to catalog.users.
         Back-fills all existing rows to 1 via server_default — no data loss.
Downgrade: drops the column.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_users_token_version"
down_revision: Union[str, None] = "0018_ingest_job_fanned_out_status"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("users", "token_version", schema="catalog")
