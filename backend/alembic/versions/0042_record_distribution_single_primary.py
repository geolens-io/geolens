"""At most one primary distribution per record.

fix(#1383). ``record_distributions.is_primary`` is read as "THE primary
distribution" — it is emitted per distribution in the OGC Record's
``properties.distributions`` (``search/service_records.py``), which is what the
dataset detail response and the STAC item's source record carry. Nothing kept
it singular: ``create_distribution`` and ``update_distribution`` stored the flag
verbatim, and every dataset already carries a generated primary (GeoPackage
when it has geometry, CSV when it does not), so a single
``POST /records/{id}/distributions/`` with ``is_primary: true`` left the record
with two rows claiming it and no tiebreak.

The write paths now demote the incumbent (last write wins, stated on
``create_distribution``'s docstring). This index is what the API cannot route
around, and it is also what fixes the records already in the bad state — the
demote alone would leave every pre-existing double untouched.

**The repair rule, and why it is this one.** ``record_distributions`` carries
no ``created_at``/``updated_at``, so "keep the most recently updated row" is
not expressible. Per record, of the rows flagged primary, keep exactly one,
ordered by:

1. USER-AUTHORED before generated (``auto_generated`` ascending, false first).
   This is the same precedence the service layer applies going forward — an
   explicit ``is_primary: true`` from a caller outranks the platform default,
   and it is the row that produced the double in the first place, so keeping
   it preserves what the caller asked for.
2. Then the generated preference order the code normalizes with: the
   ``download``/``gpkg`` row, then ``download``/``csv``, then anything else.
   This matters only when several GENERATED rows are primary (a state that
   predates the reconcile normalization in #1314); it lands on the row a fresh
   ``generate_distributions`` would have picked.
3. Then ``id``, so the outcome is total and repeatable — re-running the
   repair on the same data always keeps the same row.

Everything else on that record has ``is_primary`` cleared. No row is deleted:
a demoted distribution is still a distribution, and the DCAT/GeoDCAT-AP feeds
never serialized the flag at all, so nothing disappears from them.

Plain, transactional ``CREATE UNIQUE INDEX`` — not ``CONCURRENTLY``, following
0040's reasoning verbatim: a CIC interrupted mid-build (lock contention from a
sibling pytest-xdist worker migrating its own database, a killed process)
leaves an INVALID index that ``IF NOT EXISTS`` then treats as already there,
invisible to reflection and never chosen by the planner. Plain DDL participates
in this migration's transaction, so the repair and the index either both land
or neither does — which also means the index can never be created over rows the
repair failed to clean.

Downgrade drops the index. It cannot restore the flags the repair cleared, and
does not try: those rows were ambiguous by construction, and nothing recorded
which of the two any consumer had been reading.

Revision ID: 0042_record_distribution_single_primary
Revises: 0041_raster_assets_crs_wkt2
Create Date: 2026-08-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0042_record_distribution_single_primary"
down_revision: Union[str, None] = "0041_raster_assets_crs_wkt2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_record_distribution_primary"

# Deterministic demotion of every primary row but the winner — see the module
# docstring for the ordering and why each term is in it. Imported by
# tests/test_distribution_primary_1383.py so the test exercises this exact SQL
# rather than a paraphrase of it.
_REPAIR_SQL = """
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY record_id
               ORDER BY
                   auto_generated,
                   CASE
                       WHEN distribution_type = 'download' AND format = 'gpkg'
                           THEN 0
                       WHEN distribution_type = 'download' AND format = 'csv'
                           THEN 1
                       ELSE 2
                   END,
                   id
           ) AS rn
    FROM catalog.record_distributions
    WHERE is_primary
)
UPDATE catalog.record_distributions AS d
SET is_primary = false
FROM ranked
WHERE d.id = ranked.id
  AND ranked.rn > 1
"""

_CREATE_INDEX_SQL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME}
ON catalog.record_distributions (record_id)
WHERE is_primary
"""


def upgrade() -> None:
    # Repair first: the index cannot be built over a record that still has two.
    op.execute(_REPAIR_SQL)
    op.execute(_CREATE_INDEX_SQL)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS catalog.{_INDEX_NAME}")
