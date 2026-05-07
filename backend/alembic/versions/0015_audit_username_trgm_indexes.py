"""GIN trigram indexes for admin search hot paths.

v13.12's ``0010_trgm_search_indexes`` added pg_trgm GIN indexes for the
catalog/maps user-facing search paths but did not cover the two admin-search
hot paths:

* ``audit_logs.action`` -- the admin audit-log search filter ILIKEs this
  column with patterns like ``%user.login%`` or ``%dataset.create%``.
  Without a trigram index, every search is a sequential scan against a
  table that grows linearly with admin activity.
* ``users.username`` -- the admin user-management search filter ILIKEs
  this column. Same pattern: monotone growth, every search a seq scan.

Both indexes use the same ``lower(catalog.immutable_unaccent(...))`` shape
that ``0010_trgm_search_indexes`` established for the records / maps
columns. The ``catalog.immutable_unaccent`` IMMUTABLE wrapper is created
by ``0010``; this migration only adds the indexes referencing it.

Phase 279 ADMIN-02 verifies the admin search routes actually use these
indexes (route binding + admin-UI smoke test).

Closes v13.13 DBM-09 (db-audit/migration-audit M-03 -- completes the
trigram coverage gap left by 0010).
"""

from typing import Union

from alembic import op


revision: str = "0015_audit_username_trgm_indexes"
down_revision: Union[str, None] = "0014_fk_covering_indexes"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # audit_logs.action — admin audit-log full-text search ILIKE.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_trgm "
        "ON catalog.audit_logs USING gin "
        "(lower(catalog.immutable_unaccent(action)) gin_trgm_ops)"
    )
    # users.username — admin user search ILIKE.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_username_trgm "
        "ON catalog.users USING gin "
        "(lower(catalog.immutable_unaccent(username)) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_users_username_trgm")
    op.execute("DROP INDEX IF EXISTS catalog.ix_audit_logs_action_trgm")
