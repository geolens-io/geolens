"""Stamp each stored embedding with the configuration that produced it.

fix(#1546): ``catalog.record_embeddings`` recorded ``model_name`` and nothing
else about how the vector was made. The vector space is a function of the
model, the declared dimensions AND the endpoint that served the model, so one
model behind two endpoints is two spaces under one label. Semantic search
embeds the query with the configuration live at query time and filtered stored
rows by model name alone, which lets it compare across spaces and return
well-formed nonsense.

``config_fingerprint`` is the SHA-256 of that triple (see
``embedding_config_fingerprint`` in ``app/processing/embeddings/helpers.py``).

Deliberately NULLABLE and deliberately NOT backfilled. What configuration
produced a row already in the table is not recoverable from the row, and
stamping every existing row with today's configuration would invent provenance
that happens to be right only on the instances that never changed anything.
NULL means "unknown, written before this column existed", and every reader
grandfathers it: an unstamped row is matched on model name alone, exactly as
before. So an upgrade changes nothing an operator can see — semantic search
keeps working on day one — and rows earn a stamp as they are regenerated.

No index. The fingerprint is never a search predicate on its own: it always
rides alongside ``model_name`` (itself unindexed since 0001_baseline) inside a
query whose cost is the HNSW vector scan, and it is evaluated as a filter over
the rows that scan already produced.

Revision ID: 0052_record_embedding_config_fingerprint
Revises: 0051_one_terminal_backfill_audit
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052_record_embedding_config_fingerprint"
down_revision: Union[str, None] = "0051_one_terminal_backfill_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "record_embeddings",
        sa.Column("config_fingerprint", sa.String(length=64), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("record_embeddings", "config_fingerprint", schema="catalog")
