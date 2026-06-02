"""GIN trigram index on users.email for admin user search.

The admin user-management search (``admin/service.py`` ``list_users``) filters
``User.username ILIKE %q% OR User.email ILIKE %q%``. Migration 0015 added the
trigram index on ``users.username`` but NOT on ``users.email`` — so the OR was
forced to a sequential scan regardless (an OR with one unindexed branch cannot
use an index on the other). This adds the matching index on ``email`` so the
planner can BitmapOr both trigram indexes, and the query was rewritten to the
``lower(catalog.immutable_unaccent(...))`` shape the indexes require (T-2/T-1
follow-up).

Same ``lower(catalog.immutable_unaccent(...))`` shape and ``catalog.immutable_unaccent``
IMMUTABLE wrapper (created by 0010) as the username index in 0015.

Revision ID: 0027_users_email_trgm_idx
Revises: 0026_assoc_fk_indexes
Create Date: 2026-06-02
"""

from typing import Union

from alembic import op

revision: str = "0027_users_email_trgm_idx"
down_revision: Union[str, None] = "0026_assoc_fk_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # users.email — admin user search ILIKE (pairs with ix_users_username_trgm).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_email_trgm "
        "ON catalog.users USING gin "
        "(lower(catalog.immutable_unaccent(email)) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_users_email_trgm")
