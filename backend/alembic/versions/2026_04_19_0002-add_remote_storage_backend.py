"""Add remote to raster_assets storage_backend CHECK constraint.

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-04-19 01:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "j7k8l9m0n1o2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.raster_assets "
        "DROP CONSTRAINT IF EXISTS chk_raster_assets_storage_backend"
    )
    op.execute(
        "ALTER TABLE catalog.raster_assets ADD CONSTRAINT chk_raster_assets_storage_backend "
        "CHECK (storage_backend IN ('local', 's3', 'remote'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.raster_assets "
        "DROP CONSTRAINT IF EXISTS chk_raster_assets_storage_backend"
    )
    op.execute(
        "ALTER TABLE catalog.raster_assets ADD CONSTRAINT chk_raster_assets_storage_backend "
        "CHECK (storage_backend IN ('local', 's3'))"
    )
