"""add table record_type

Revision ID: 0002_add_table_type
Revises: 0001_initial
Create Date: 2026-03-22
"""

from alembic import op

revision = "0002_add_table_type"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.records DROP CONSTRAINT IF EXISTS chk_records_record_type"
    )
    op.execute(
        "ALTER TABLE catalog.records ADD CONSTRAINT chk_records_record_type "
        "CHECK (record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', "
        "'map', 'service', 'collection', 'table'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.records DROP CONSTRAINT IF EXISTS chk_records_record_type"
    )
    op.execute(
        "ALTER TABLE catalog.records ADD CONSTRAINT chk_records_record_type "
        "CHECK (record_type IN ('vector_dataset', 'raster_dataset', 'vrt_dataset', "
        "'map', 'service', 'collection'))"
    )
