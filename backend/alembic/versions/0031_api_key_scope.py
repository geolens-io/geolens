"""Add catalog.api_keys.scope for least-privilege machine credentials.

fix(#875): an API key impersonated its owner completely, so any credential
embedded in an application could also mutate or delete everything its owner
could. ``scope`` splits that: a ``read_only`` key authenticates GET/HEAD/
OPTIONS and is refused on anything else at the resolution chokepoint.

``server_default='full'`` is what keeps this backward compatible -- every key
minted before this migration reads back as ``full`` and behaves exactly as it
did. The column is NOT NULL because a NULL scope has no safe interpretation:
treating it as ``full`` at the call site would make an accidental NULL a silent
privilege grant, and the default means no writer ever has to supply one.

Revision ID: 0031_api_key_scope
Revises: 0030_records_spatial_extent_type
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_api_key_scope"
down_revision: Union[str, None] = "0030_records_spatial_extent_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "scope",
            sa.String(length=20),
            server_default="full",
            nullable=False,
        ),
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_api_keys_scope",
        "api_keys",
        "scope IN ('full', 'read_only')",
        schema="catalog",
    )


def downgrade() -> None:
    # Dropping the column widens every read_only key back to its owner's full
    # privileges, which is a privilege ESCALATION rather than a data loss, so
    # it is not something to do silently. An operator who genuinely wants the
    # old schema deactivates or deletes the restricted keys first.
    bind = op.get_bind()
    # fix(#875 codex r1): counts only ACTIVE restricted keys, so the
    # remediation the message advertises actually clears the block. Counting
    # every row made deactivation a no-op and left rollback impossible short
    # of deleting the credentials, which the message never asked for.
    # An inactive key cannot authenticate at all, so widening its scope back
    # to 'full' grants nothing.
    restricted = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys "
            "WHERE scope = 'read_only' AND is_active"
        )
    ).scalar_one()
    if restricted:
        raise RuntimeError(
            f"{restricted} ACTIVE catalog.api_keys row(s) are scoped "
            "'read_only'. Dropping the scope column would silently restore "
            "full owner privileges to every one of them. Inspect them with:\n"
            "  SELECT id, user_id, name, fingerprint FROM catalog.api_keys "
            "WHERE scope = 'read_only' AND is_active;\n"
            "Deactivate or delete them first, then re-run the downgrade:\n"
            "  UPDATE catalog.api_keys SET is_active = false "
            "WHERE scope = 'read_only';"
        )

    op.drop_constraint(
        "chk_api_keys_scope", "api_keys", schema="catalog", type_="check"
    )
    op.drop_column("api_keys", "scope", schema="catalog")
