"""FK covering btree indexes on trailing composite-PK association columns.

Each of these three association tables has a composite primary key whose
leading column is covered by the ``*_pkey`` btree, but whose SECOND
foreign-key column has no standalone index. A composite PK on ``(a, b)``
cannot serve ``WHERE b = ?`` probes or the cascade DELETE triggered from
the ``b``-side parent, so every such join/delete is a sequential scan over
the association table.

Three trailing-FK gaps (migration-audit T-3):

* ``collection_datasets.dataset_id`` -> datasets (CASCADE). Probed on
  "which collections contain this dataset" and on cascade delete of a
  dataset. PK is ``(collection_id, dataset_id)``.
* ``dataset_grants.role_id`` -> roles (CASCADE). Probed on "which datasets
  does this role grant" and on cascade delete of a role. PK is
  ``(dataset_id, role_id)``.
* ``user_roles.role_id`` -> roles (CASCADE). Probed on "which users hold
  this role" and on cascade delete of a role. PK is ``(user_id, role_id)``.

Idempotent (``IF NOT EXISTS`` / ``IF EXISTS``); safe to re-run. Mirrors the
DBM-10 FK-covering-index style from migration 0014. The matching
``Index(...)`` declarations were added to the three association models so
``alembic check`` stays green.

Revision ID: 0026_assoc_fk_indexes
Revises: 0025_widgets_to_plugins_rename
Create Date: 2026-06-02
"""

from typing import Union

from alembic import op

revision: str = "0026_assoc_fk_indexes"
down_revision: Union[str, None] = "0025_widgets_to_plugins_rename"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # collection_datasets -> datasets (CASCADE); trailing PK column.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_collection_datasets_dataset_id "
        "ON catalog.collection_datasets (dataset_id)"
    )
    # dataset_grants -> roles (CASCADE); trailing PK column.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dataset_grants_role_id "
        "ON catalog.dataset_grants (role_id)"
    )
    # user_roles -> roles (CASCADE); trailing PK column.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_roles_role_id "
        "ON catalog.user_roles (role_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_user_roles_role_id")
    op.execute("DROP INDEX IF EXISTS catalog.ix_dataset_grants_role_id")
    op.execute("DROP INDEX IF EXISTS catalog.ix_collection_datasets_dataset_id")
