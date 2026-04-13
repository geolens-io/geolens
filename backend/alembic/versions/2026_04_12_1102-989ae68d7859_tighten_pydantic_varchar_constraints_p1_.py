"""tighten_pydantic_varchar_constraints_p1_6_p1_7_p1_8

Revision ID: 989ae68d7859
Revises: f3a4b5c6d7e8
Create Date: 2026-04-12 11:02:20.067957

Audit findings P1-6, P1-7, P1-8: Pydantic max_length fields were wider than
the underlying SQL VARCHAR columns. The SQL column widths already match the
intended constraints (set in prior migrations), so no ALTER COLUMN statements
are required. This migration documents the Pydantic schema tightening:

  DatasetMeta.update_frequency:          max_length 1000 -> 30  (SQL: VARCHAR(30))
  DatasetMeta.record_status:             max_length 1000 -> 20  (SQL: VARCHAR(20))
  DatasetMeta.sensitivity_classification: max_length 1000 -> 20 (SQL: VARCHAR(20))
  DatasetMeta.language:                  max_length 1000 -> 10  (SQL: VARCHAR(10))
  ContactCreate/Update.role:             max_length 100  -> Literal (SQL: VARCHAR(30))
  KeywordCreate.keyword_type:            max_length 100  -> Literal (SQL: VARCHAR(20))
  DistributionCreate/Update.distribution_type: max_length 200 -> 30 (SQL: VARCHAR(30))
  DistributionCreate/Update.format:      max_length 200  -> 50  (SQL: VARCHAR(50))
  DistributionCreate/Update.media_type:  max_length 255  -> 100 (SQL: VARCHAR(100))
  UserCreate.email:                      max_length 320  -> 255 (SQL: VARCHAR(255))
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "989ae68d7859"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQL columns already have the correct VARCHAR widths — no ALTER needed.
    # This migration documents the corresponding Pydantic schema tightening
    # applied in audit remediation phase 224 (P1-6, P1-7, P1-8).
    pass


def downgrade() -> None:
    pass
