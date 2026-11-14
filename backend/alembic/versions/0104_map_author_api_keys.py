"""Add map_author API keys and record which key created a map.

A ``map_author`` key reads, creates maps and styles the maps it created. The
upgrade widens the scope check, which every existing row already satisfies,
and adds a nullable ``maps.created_by_api_key_id`` with no default, so the
ALTER changes only the catalog and the previous release never reads it.

Revision ID: 0104_map_author_api_keys
Revises: 0103_database_origin
Create Date: 2026-11-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0104_map_author_api_keys"
down_revision: Union[str, None] = "0103_database_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_OLD_SCOPES = "'full', 'read_only', 'dataset_write', 'dataset_append', 'publish'"


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
    op.execute(_LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE catalog.maps ADD COLUMN IF NOT EXISTS created_by_api_key_id uuid"
    )
    _replace_scope_check(f"{_OLD_SCOPES}, 'map_author'")


def downgrade() -> None:
    # An older schema could keep an active map_author key only as a wider one.
    # Locked in key creation's order, so no key commits between count and drop.
    op.execute(_LOCK_TIMEOUT)
    bind = op.get_bind()
    op.execute("LOCK TABLE catalog.users, catalog.api_keys IN ACCESS EXCLUSIVE MODE")
    active = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys "
            "WHERE scope = 'map_author' AND is_active"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            f"{active} active map_author-scoped API key(s); revoke them first "
            "(see UPGRADING.md, Rollback)."
        )
    # Expired too, so reactivating a relabelled row by hand revives nothing.
    op.execute(
        "UPDATE catalog.api_keys SET scope = 'read_only', "
        "expires_at = LEAST(COALESCE(expires_at, now()), now()) "
        "WHERE scope = 'map_author'"
    )
    _replace_scope_check(_OLD_SCOPES)
    op.drop_column("maps", "created_by_api_key_id", schema="catalog")
