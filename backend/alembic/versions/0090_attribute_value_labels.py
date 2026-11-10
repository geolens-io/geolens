"""Value labels for coded attributes.

``attribute_metadata.value_labels`` maps a stored code to the label a source
published for it, such as an ArcGIS coded-value domain. NULL means the column
has no labels.

Revision ID: 0090_attribute_value_labels
Revises: 0089_sharing_groups
Create Date: 2026-10-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0090_attribute_value_labels"
down_revision: Union[str, None] = "0089_sharing_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attribute_metadata",
        sa.Column("value_labels", JSONB(), nullable=True),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_column("attribute_metadata", "value_labels", schema="catalog")
