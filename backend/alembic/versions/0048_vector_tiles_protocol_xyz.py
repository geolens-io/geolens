"""Relabel auto-generated vector-tile distributions from OGC:WMTS to XYZ.

fix(#1463): the generated "Vector Tiles" row advertised ``protocol='OGC:WMTS'``
against ``/tiles/data.{table}/{z}/{x}/{y}.pbf`` — a plain XYZ template with no
capabilities document and no TileMatrixSet negotiation. A client that believed
the label failed against a healthy instance, which reads as a broken deployment
rather than a wrong string. ``records/service.py`` now stamps ``XYZ`` on new
rows; this rewrites the ones already in the database.

A migration is required rather than a reconcile-side correction, because
neither generated-distribution write path ever updates a surviving row.
``generate_distributions`` probes ``(distribution_type, format)`` pairs and
SKIPS one it already owns, and ``reconcile_distributions`` only deletes pairs
the record's new modality excludes and normalizes ``is_primary``. Nothing
rewrites ``protocol``, so without this statement every record created before
the deploy keeps the wrong value for good.

The WHERE clause is deliberately four-way:

- ``auto_generated = true`` — rows a user authored through
  ``create_distribution`` are their text in a free-text field. Someone who
  typed ``OGC:WMTS`` for their own WMTS service is correct, and a migration has
  no standing to overwrite it.
- ``distribution_type = 'vector_tiles' AND format = 'pbf'`` — the exact pair
  ``generate_distributions`` owns. The raster and VRT ingest tails write their
  own auto-generated ``download`` rows, which this must not touch.
- ``protocol = 'OGC:WMTS'`` — only rows still carrying the wrong value, so a
  re-run is a no-op and an auto-generated row already corrected by hand is left
  as it is.

Downgrade is a no-op, like the other data-only normalizations here (0003,
0028, 0034). The mirror-image UPDATE looks symmetric and is not: ``XYZ`` is
also what an operator who corrected a row by hand before this deploy already
has, and the upgrade deliberately leaves those alone, so a reverse statement
scoped to ``protocol = 'XYZ'`` would rewrite rows this migration never touched
and hand them a value that was wrong when they fixed it. Recording the row ids
to make the reverse exact is not worth it either, because no revision needs
``OGC:WMTS`` back: ``protocol`` is metadata, nothing reads it for behaviour at
any version (not the frontend, not the DCAT/GeoDCAT-AP/DCAT-US serializers,
not STAC), so leaving the honest label in place downgrades cleanly.

Revision ID: 0048_vector_tiles_protocol_xyz
Revises: 0047_users_sessions_revoked_at
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0048_vector_tiles_protocol_xyz"
down_revision: Union[str, None] = "0047_users_sessions_revoked_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE catalog.record_distributions
        SET protocol = 'XYZ'
        WHERE auto_generated = true
          AND distribution_type = 'vector_tiles'
          AND format = 'pbf'
          AND protocol = 'OGC:WMTS'
        """
    )


def downgrade() -> None:
    # fix(#1463, codex round 1): data-only relabel, intentionally not reversed.
    # See the module docstring — the reverse statement cannot tell a row this
    # migration rewrote from one an operator had already corrected, and no
    # revision needs the WMTS label back.
    pass
