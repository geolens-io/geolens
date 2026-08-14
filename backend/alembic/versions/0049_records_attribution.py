"""Add the display-credit column to catalog.records.

feat(#1472): ``ManifestMetadata.attribution`` was validated at manifest apply
and written to ``ingest_jobs.user_metadata['manifest_attribution']``, where it
stopped. No record column carried it, so the credit line an operator supplied
to satisfy a source's terms (swisstopo swissALTI3D, NOAA ETOPO) was never shown
anywhere. This is the column the ingest tail, the dataset PATCH, and the
map-layer read models now write and read.

Deliberately its own column rather than a reuse of ``license`` or
``source_organization``: ``license`` names the terms, ``source_organization``
is a search facet whose values are grouped and counted, and attribution is
verbatim prose that has to be rendered unchanged. Folding it into either would
either corrupt a facet or lose the distinction the terms require.

``Text`` and nullable with no default and no backfill. NULL means "no credit
required", which is the correct value for every existing row. Historical
``user_metadata['manifest_attribution']`` values are intentionally NOT
backfilled: the job ledger is per-ingest and a dataset may have been reuploaded
or edited since, so a blanket copy would resurrect a credit line for a dataset
whose data no longer comes from that source. Operators who want the old values
can PATCH them. No index: the column is only ever read through a record row the
query already joins, never filtered or grouped on.

Revision ID: 0049_records_attribution
Revises: 0048_vector_tiles_protocol_xyz
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_records_attribution"
down_revision: Union[str, None] = "0048_vector_tiles_protocol_xyz"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "records",
        sa.Column("attribution", sa.Text(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("records", "attribution", schema="catalog")
