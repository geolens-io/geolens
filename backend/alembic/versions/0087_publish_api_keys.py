"""Add publish-scoped API keys.

A ``publish`` key uploads, applies manifests and writes metadata and maps, but
can't delete anything or write features. The upgrade only widens the scope
check constraint, which every existing row already satisfies.

Revision ID: 0087_publish_api_keys
Revises: 0086_dataset_append_api_keys
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0087_publish_api_keys"
down_revision: Union[str, None] = "0086_dataset_append_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_scope_check(scopes: str) -> None:
    op.drop_constraint(
        "chk_api_keys_scope", "api_keys", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_api_keys_scope",
        "api_keys",
        f"scope IN ({scopes})",
        schema="catalog",
    )


def upgrade() -> None:
    _replace_scope_check(
        "'full', 'read_only', 'dataset_write', 'dataset_append', 'publish'"
    )


def downgrade() -> None:
    # The only older scope a publish key could become without losing its row is
    # full, which would let it delete, so an active one blocks the downgrade.
    # Lock first, users before api_keys as key creation takes them, so a key
    # committed after the count cannot slip through.
    bind = op.get_bind()
    op.execute("LOCK TABLE catalog.users, catalog.api_keys IN ACCESS EXCLUSIVE MODE")
    active = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys WHERE scope = 'publish' AND is_active"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            f"{active} ACTIVE catalog.api_keys row(s) are scoped 'publish'. "
            "Inspect them with:\n"
            "  SELECT id, user_id, name, fingerprint "
            "FROM catalog.api_keys WHERE scope = 'publish' AND is_active;\n"
            "Revoke them first, then re-run the downgrade:\n"
            "  UPDATE catalog.api_keys SET is_active = false "
            "WHERE scope = 'publish';"
        )
    # An inactive key cannot authenticate, so relabelling it read_only keeps the
    # row for the audit trail. Its expiry is pulled to now as well, so
    # reactivating the row by hand can't revive it.
    op.execute(
        "UPDATE catalog.api_keys SET scope = 'read_only', "
        "expires_at = LEAST(COALESCE(expires_at, now()), now()) "
        "WHERE scope = 'publish'"
    )
    _replace_scope_check("'full', 'read_only', 'dataset_write', 'dataset_append'")
