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
    # An older schema could keep an active publish key only as a full key.
    # Locked in key creation's order, so no key commits between count and drop.
    bind = op.get_bind()
    op.execute("LOCK TABLE catalog.users, catalog.api_keys IN ACCESS EXCLUSIVE MODE")
    active = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys WHERE scope = 'publish' AND is_active"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            f"{active} active publish-scoped API key(s); revoke them first "
            "(see UPGRADING.md, Rollback)."
        )
    # Expired too, so reactivating a relabelled row by hand revives nothing.
    op.execute(
        "UPDATE catalog.api_keys SET scope = 'read_only', "
        "expires_at = LEAST(COALESCE(expires_at, now()), now()) "
        "WHERE scope = 'publish'"
    )
    _replace_scope_check("'full', 'read_only', 'dataset_write', 'dataset_append'")
