"""Add append-only dataset API keys.

A ``dataset_append`` key is bound to one dataset like a ``dataset_write``
key, but only creates features there: it can't read, change or delete them.
The upgrade only widens two check constraints, which every existing row
already satisfies.

Revision ID: 0086_dataset_append_api_keys
Revises: 0085_dataset_retention
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0086_dataset_append_api_keys"
down_revision: Union[str, None] = "0085_dataset_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_scope_checks(scopes: str, dataset_scopes: str) -> None:
    for name in ("chk_api_keys_scope", "chk_api_keys_dataset_scope"):
        op.drop_constraint(name, "api_keys", schema="catalog", type_="check")
    op.create_check_constraint(
        "chk_api_keys_scope",
        "api_keys",
        f"scope IN ({scopes})",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_api_keys_dataset_scope",
        "api_keys",
        f"(scope IN ({dataset_scopes})) = (dataset_id IS NOT NULL)",
        schema="catalog",
    )


def upgrade() -> None:
    _replace_scope_checks(
        "'full', 'read_only', 'dataset_write', 'dataset_append'",
        "'dataset_write', 'dataset_append'",
    )


def downgrade() -> None:
    # Every older scope would widen an append key, so an active one blocks the
    # downgrade rather than being widened or deleted. Lock first, users before
    # api_keys as key creation takes them, so a key committed after the count
    # cannot slip through.
    bind = op.get_bind()
    op.execute("LOCK TABLE catalog.users, catalog.api_keys IN ACCESS EXCLUSIVE MODE")
    active = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys "
            "WHERE scope = 'dataset_append' AND is_active"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            f"{active} ACTIVE catalog.api_keys row(s) are scoped "
            "'dataset_append'. Inspect them with:\n"
            "  SELECT id, user_id, dataset_id, name, fingerprint "
            "FROM catalog.api_keys WHERE scope = 'dataset_append' AND is_active;\n"
            "Deactivate them first, then re-run the downgrade:\n"
            "  UPDATE catalog.api_keys SET is_active = false "
            "WHERE scope = 'dataset_append';"
        )
    # An inactive key cannot authenticate, so relabelling it as the other
    # dataset scope keeps the row and its dataset for the audit trail. Its
    # expiry is pulled to now as well, so reactivating the row by hand can't
    # revive it with read and write access.
    op.execute(
        "UPDATE catalog.api_keys SET scope = 'dataset_write', "
        "expires_at = LEAST(COALESCE(expires_at, now()), now()) "
        "WHERE scope = 'dataset_append'"
    )
    _replace_scope_checks("'full', 'read_only', 'dataset_write'", "'dataset_write'")
