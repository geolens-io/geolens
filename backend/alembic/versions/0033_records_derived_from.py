"""Add catalog.records.derived_from for analysis provenance.

feat(#765): a materialized analysis output had no durable link to the dataset
it came from -- ``source_dataset_id`` lived only in ``ingest_jobs.user_metadata``,
which is purgeable. This column carries ``{dataset_id, operation, params,
created_at}`` written at materialize time.

Nullable with no backfill: the information needed to reconstruct provenance for
records created before this migration is exactly what the migration exists to
stop losing, so there is nothing to fill them with.

Revision ID: 0033_records_derived_from
Revises: 0032_api_key_scope
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_records_derived_from"
down_revision: Union[str, None] = "0032_api_key_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "records",
        sa.Column(
            "derived_from", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("records", "derived_from", schema="catalog")
