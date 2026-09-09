"""Add datasets.publication_version — the counter a tile signature binds.

A signed tile template carried only a scope and an expiry, so it kept serving
tiles after the owner unpublished the dataset or made it private (#1963). The
scope now folds in this counter, which rolls on publication-status and
visibility transitions only, so an outstanding signature stops verifying
without a database read on the tile path.

Deliberately not `tile_cache_version`: that one also rolls on feature edits,
column DDL and reupload, and binding the signature to it would kill every live
tile template on an ordinary edit.

Revision ID: 0060_dataset_publication_version
Revises: 0059_arcgis_signin_settle_index
Create Date: 2026-09-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_dataset_publication_version"
down_revision: Union[str, None] = "0059_arcgis_signin_settle_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "publication_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("datasets", "publication_version", schema="catalog")
