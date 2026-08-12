"""Stage a VRT generation's intended member set on the generation row.

fix(#1327). ``add_vrt_source``/``remove_vrt_source`` committed their
``vrt_source_links`` mutation in the same transaction that flipped the asset to
``'regenerating'`` — before the regeneration that would make the served artifact
match. The two steps were separate, non-compensable transactions, so a worker
death between them left the catalog's declared composition permanently ahead of
the served bytes; #1322's sweep could detect that drift and refuse to hide it,
but not repair it.

``staged_source_ids`` holds the FULL intended post-mutation member set as an
ordered array of source dataset ids. The link table is left alone at request
time and the staged set is applied to it in the same transaction that swaps the
artifact and writes ``built_from`` (the #1290 commit-time pattern). Death before
that swap now leaves the links untouched, so catalog and artifact agree with no
compensation to run.

Nullable with no backfill, deliberately. NULL means the generation changes no
membership — a plain regenerate, or anything queued before this column existed —
and the task builds from the live links and applies nothing for it.

Revision ID: 0043_vrt_generations_staged_source_ids
Revises: 0042_record_distribution_single_primary
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_vrt_generations_staged_source_ids"
down_revision: Union[str, None] = "0042_record_distribution_single_primary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vrt_generations",
        sa.Column("staged_source_ids", postgresql.JSONB(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("vrt_generations", "staged_source_ids", schema="catalog")
