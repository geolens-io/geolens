"""Add one-dataset write API keys.

A ``dataset_write`` key may read and write one dataset's features and
nothing else, so a webhook that writes features no longer has to carry a key
with its owner's full privileges. ``api_keys.dataset_id`` names that dataset
and is set if and only if the key has that scope. Deleting the dataset
deletes its keys.

The upgrade only adds a nullable column, an index and constraints that every
existing row already satisfies.

Revision ID: 0084_dataset_write_api_keys
Revises: 0083_list_order_indexes
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0084_dataset_write_api_keys"
down_revision: Union[str, None] = "0083_list_order_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        schema="catalog",
    )
    op.create_foreign_key(
        "api_keys_dataset_id_fkey",
        "api_keys",
        "datasets",
        ["dataset_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_catalog_api_keys_dataset_id"),
        "api_keys",
        ["dataset_id"],
        schema="catalog",
    )
    op.drop_constraint(
        "chk_api_keys_scope", "api_keys", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_api_keys_scope",
        "api_keys",
        "scope IN ('full', 'read_only', 'dataset_write')",
        schema="catalog",
    )
    op.create_check_constraint(
        "chk_api_keys_dataset_scope",
        "api_keys",
        "(scope = 'dataset_write') = (dataset_id IS NOT NULL)",
        schema="catalog",
    )


def downgrade() -> None:
    # Without the column a dataset_write key has no scope that keeps it to one
    # dataset, so an active one blocks the downgrade rather than being widened
    # or deleted. Lock first, users before api_keys as key creation takes
    # them, so a key committed after the count cannot slip through.
    bind = op.get_bind()
    op.execute("LOCK TABLE catalog.users, catalog.api_keys IN ACCESS EXCLUSIVE MODE")
    active = bind.execute(
        sa.text(
            "SELECT count(*) FROM catalog.api_keys "
            "WHERE scope = 'dataset_write' AND is_active"
        )
    ).scalar_one()
    if active:
        raise RuntimeError(
            f"{active} ACTIVE catalog.api_keys row(s) are scoped "
            "'dataset_write'. Inspect them with:\n"
            "  SELECT id, user_id, dataset_id, name, fingerprint "
            "FROM catalog.api_keys WHERE scope = 'dataset_write' AND is_active;\n"
            "Deactivate them first, then re-run the downgrade:\n"
            "  UPDATE catalog.api_keys SET is_active = false "
            "WHERE scope = 'dataset_write';"
        )
    # An inactive key cannot authenticate, so the narrowest older scope keeps
    # the row for the audit trail without granting anything.
    op.drop_constraint(
        "chk_api_keys_dataset_scope", "api_keys", schema="catalog", type_="check"
    )
    op.execute(
        "UPDATE catalog.api_keys SET scope = 'read_only' WHERE scope = 'dataset_write'"
    )
    op.drop_constraint(
        "chk_api_keys_scope", "api_keys", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_api_keys_scope",
        "api_keys",
        "scope IN ('full', 'read_only')",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_api_keys_dataset_id"), table_name="api_keys", schema="catalog"
    )
    op.drop_constraint(
        "api_keys_dataset_id_fkey", "api_keys", schema="catalog", type_="foreignkey"
    )
    op.drop_column("api_keys", "dataset_id", schema="catalog")
