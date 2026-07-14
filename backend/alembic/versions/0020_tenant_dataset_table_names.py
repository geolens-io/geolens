"""Scope physical dataset table-name uniqueness to each tenant.

The catalog originally required ``datasets.table_name`` to be globally unique
because every deployment used one physical ``data`` schema. Multi-tenant mode
uses one ``data_t_<tenant>`` schema per tenant, so two tenants may safely use
the same physical table name. Keeping the global constraint also made
RLS-scoped collision detection race into an unexpected unique violation.

Revision ID: 0020_tenant_dataset_table_names
Revises: 0019_tenant_provisioning_boundary
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_tenant_dataset_table_names"
down_revision: Union[str, None] = "0019_tenant_provisioning_boundary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "datasets_table_name_key",
        "datasets",
        schema="catalog",
        type_="unique",
    )
    op.create_index(
        "uq_datasets_table_name_global",
        "datasets",
        ["table_name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_datasets_table_name_tenant",
        "datasets",
        ["tenant_id", "table_name"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_datasets_table_name_tenant",
        table_name="datasets",
        schema="catalog",
    )
    op.drop_index(
        "uq_datasets_table_name_global",
        table_name="datasets",
        schema="catalog",
    )
    # This intentionally fails loud if separate tenants have since reused a
    # table name: the older global-only schema cannot represent that state.
    op.create_unique_constraint(
        "datasets_table_name_key",
        "datasets",
        ["table_name"],
        schema="catalog",
    )
