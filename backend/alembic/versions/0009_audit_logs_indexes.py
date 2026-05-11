"""Index audit_logs hot filter + sort paths.

The admin compliance UI's primary view (``GET /admin/audit-logs``) filters
by ``action``, ``resource_type``, ``resource_id``, and ``created_at`` (range)
and orders by ``created_at DESC``. Pre-fix only ``user_id`` was indexed, so
every list query was a sequential scan + sort that grew linearly with audit
volume.

Adds:

* Composite ``(created_at DESC, action, resource_type)`` — covers the
  default ORDER BY plus the two most common equality filters in one
  index, so admin-UI filtered-list views can do an index-only scan.
* Singleton ``(resource_id)`` — supports the ``GET /admin/audit-logs/by-resource/{id}``
  detail-style filter which doesn't co-vary with ``created_at``.

Closes v13.12 finding H-06 (db-audit HIGH-01).
"""

from typing import Union

from alembic import op


revision: str = "0009_audit_logs_indexes"
down_revision: Union[str, None] = "0008_refresh_tokens_expires_idx"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Composite index supports both ORDER BY created_at DESC and
    # WHERE action = ? / resource_type = ? equality filters together.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_audit_logs_created_action_resource "
        "ON catalog.audit_logs (created_at DESC, action, resource_type)"
    )
    # Standalone resource_id filter (no co-variance with created_at).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_audit_logs_resource_id "
        "ON catalog.audit_logs (resource_id) "
        "WHERE resource_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_catalog_audit_logs_resource_id")
    op.execute(
        "DROP INDEX IF EXISTS catalog.ix_catalog_audit_logs_created_action_resource"
    )
