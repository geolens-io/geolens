"""Allow the ``archived_original`` key on catalog.dataset_assets.

fix(#1290 review). ADR-002 Decision 7 keeps the uploaded raster when the COG
conversion was lossy, under ``originals/<dataset_id>/``. Those objects
accumulate permanently and were counted by nothing: per-user storage usage sums
``dataset_assets`` rows with ``key='data'``, so an owner could exhaust
``MAX_STORAGE_BYTES_PER_USER`` through repeated distinct lossy replacements
without any check refusing them.

Giving each archived original its own counted row makes the existing quota sum
authoritative rather than adding a second ledger beside it, and it inherits the
cleanup that already works: ``delete_dataset`` removes a dataset's asset rows
and clears the ``originals/<dataset_id>/`` object prefix in the same breath.

Widening the CHECK is the whole change. No backfill: originals archived before
this migration have no row, and inventing one would require re-reading object
sizes for a state no code has produced yet — the feature that writes them is
landing with this migration.

Revision ID: 0038_dataset_assets_archived_original
Revises: 0037_dataset_refresh_runs
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0038_dataset_assets_archived_original"
down_revision: Union[str, None] = "0037_dataset_refresh_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KEYS = "'data', 'vrt', 'thumbnail', 'overview', 'metadata'"
_NEW_KEYS = f"{_OLD_KEYS}, 'archived_original'"


def upgrade() -> None:
    op.drop_constraint(
        "chk_dataset_assets_key", "dataset_assets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_dataset_assets_key",
        "dataset_assets",
        f"key IN ({_NEW_KEYS})",
        schema="catalog",
    )


def downgrade() -> None:
    # Rows carrying the new key would violate the narrowed constraint, so they
    # go first. Dropping them loses only the quota accounting for archived
    # originals; the objects themselves live in storage and are unaffected.
    op.execute("DELETE FROM catalog.dataset_assets WHERE key = 'archived_original'")
    op.drop_constraint(
        "chk_dataset_assets_key", "dataset_assets", schema="catalog", type_="check"
    )
    op.create_check_constraint(
        "chk_dataset_assets_key",
        "dataset_assets",
        f"key IN ({_OLD_KEYS})",
        schema="catalog",
    )
