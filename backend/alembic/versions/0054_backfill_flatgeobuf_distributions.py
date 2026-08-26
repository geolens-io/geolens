"""Backfill FlatGeobuf download distributions for existing spatial datasets.

fix(#1681 codex review): _DISTRIBUTION_TEMPLATES now generates a FlatGeobuf
download distribution at dataset creation (records/service.py), but those rows
are materialized — existing spatial datasets created before this deploy would
never advertise the fgb download in DCAT feeds until an unrelated geometry-mode
flip happened to run reconcile. This backfills one row per spatial dataset that
lacks it, so DCAT distributions match what a fresh ingest produces. Mirrors
0013_backfill_geoparquet_distributions.py, the precedent for adding a format to
this materialized list.

Idempotent: the NOT EXISTS guard (plus ON CONFLICT DO NOTHING against
uq_record_distribution) makes re-running a no-op. Downgrade removes only the
auto-generated fgb download rows.

Non-spatial datasets are excluded (geometry_type IS NULL) — FlatGeobuf
requires geometry, matching generate_distributions' spatial-only filter.

fix(#1681 codex review round 2): the NOT EXISTS guard reads only
auto_generated rows, matching generate_distributions' own existence probe
(fix(#1370) there) — a user-authored download/fgb row must not suppress the
platform's own export row; the intended end state is both rows coexisting.
Narrowing the guard reopens the case that broad check was incidentally
absorbing: a user's row at the exact guessable URL this INSERT targets
(`/datasets/{id}/export?format=fgb`) collides on uq_record_distribution, so
the INSERT carries `ON CONFLICT DO NOTHING` — the same resolution
`reconcile_distributions` uses for the identical collision at runtime (see
`TestATemplateUrlCollisionDoesNotRaise` in
test_distribution_reconcile_1314.py).

Revises 0053_source_format_fgb (#1682, merged concurrently) rather than a
core revision authored alongside this one: that PR's own migration already
covers letting 'fgb' through chk_datasets_source_format, so this file is
scoped to the (unrelated) DCAT distribution gap only.

Revision ID: 0054_backfill_flatgeobuf_distributions
Revises: 0053_source_format_fgb
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0054_backfill_flatgeobuf_distributions"
down_revision: Union[str, None] = "0053_source_format_fgb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO catalog.record_distributions
            (record_id, distribution_type, format, url, title, protocol,
             media_type, is_primary, auto_generated)
        SELECT d.record_id, 'download', 'fgb',
               '/datasets/' || d.id::text || '/export?format=fgb',
               'FlatGeobuf Download', 'HTTP',
               'application/vnd.flatgeobuf', false, true
        FROM catalog.datasets d
        WHERE d.geometry_type IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM catalog.record_distributions rd
              WHERE rd.record_id = d.record_id
                AND rd.distribution_type = 'download'
                AND rd.format = 'fgb'
                AND rd.auto_generated = true
          )
        ON CONFLICT ON CONSTRAINT uq_record_distribution DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM catalog.record_distributions
        WHERE distribution_type = 'download'
          AND format = 'fgb'
          AND auto_generated = true
        """
    )
