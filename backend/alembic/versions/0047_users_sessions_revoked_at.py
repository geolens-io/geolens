"""Add the session revocation horizon to catalog.users.

fix(#1455): logout revoked the refresh rows one statement's snapshot could see
and bumped ``token_version``. Neither can express "everything issued up to
now", so a refresh row inserted by a path that does not take the owner-row lock
-- a login racing the logout -- can commit after that snapshot, survive the
revocation, and rotate into a session that outlives the logout that ended it.

``sessions_revoked_at`` is that missing statement, as a use-time predicate: any
refresh row created at or before it, and any access JWT issued at or before it,
is rejected on presentation regardless of its own state. Stamped from the DB
clock, the same clock that stamps ``refresh_tokens.created_at``, so the refresh
comparison has no skew axis.

Nullable with no default and no backfill: NULL means "no horizon", which is the
correct and behaviour-preserving value for every existing row -- none of those
users has revoked anything, and inventing a timestamp would revoke live
sessions on deploy. No index: the column is only ever read through a User row
the request already loaded, or through the join the refresh lookups already
make on the primary key.

Revision ID: 0047_users_sessions_revoked_at
Revises: 0046_detached_relations
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_users_sessions_revoked_at"
down_revision: Union[str, None] = "0046_detached_relations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("users", "sessions_revoked_at", schema="catalog")
