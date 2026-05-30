"""Rename the map widget platform vocabulary to plugin (breaking, no alias).

Part of milestone v1036 (Widget -> Plugin Platform Rename). This is a hard
breaking cut — there is no back-compat alias. Existing row values (arrays of
plugin ID strings such as ``["measurement", "legend"]``) are preserved; only
the column NAME and the config KEY change, never the stored values.

Upgrade:
  1. Renames the ``catalog.maps.widgets`` JSONB column to ``catalog.maps.plugins``
     (the ``maps`` table lives in the ``catalog`` schema). ``RENAME COLUMN`` is an
     O(1) catalog-only metadata operation in Postgres — no table rewrite, no row
     scan — so it is safe on any table size and preserves the JSONB array data.
  2. Renames the ``enabled_widgets`` persistent-config key to ``enabled_plugins``
     via an in-place ``UPDATE persistent_config SET key=...`` that preserves the
     stored value. ``persistent_config`` is in the default/public schema (created
     unqualified in 0001_baseline.py), so it is NOT prefixed with ``catalog``. The
     ``WHERE key='enabled_widgets'`` predicate is an exact match on the unique
     primary key, so it touches 0 rows (feature never configured — a valid no-op)
     or exactly 1 row.

Downgrade: reverses both renames symmetrically
(``catalog.maps.plugins`` -> ``widgets`` and the config key
``enabled_plugins`` -> ``enabled_widgets``), restoring the original names with
values preserved.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_widgets_to_plugins_rename"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # BE-RENAME-01: rename the maps column (catalog schema). Renaming preserves
    # the existing JSONB array values — no drop/recreate, no transform.
    op.alter_column(
        "maps",
        "widgets",
        new_column_name="plugins",
        schema="catalog",
    )
    # BE-RENAME-02: rename the persistent_config key in place, preserving value.
    op.execute(
        "UPDATE persistent_config SET key='enabled_plugins' "
        "WHERE key='enabled_widgets'"
    )


def downgrade() -> None:
    op.alter_column(
        "maps",
        "plugins",
        new_column_name="widgets",
        schema="catalog",
    )
    op.execute(
        "UPDATE persistent_config SET key='enabled_widgets' "
        "WHERE key='enabled_plugins'"
    )
