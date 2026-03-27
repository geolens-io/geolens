"""Address database model review findings: indexes, CHECK constraints, FK constraint.

Adds missing indexes on frequently queried FK/sort columns (H1-H5, L2),
new CHECK constraints for enum-like string columns (M1-M7, M13-M15),
updates record_type CHECK to include 'table' (H9), narrows Map.basemap_style
and Map.visibility from Text to String(N) (M10), and adds FK from
RasterAsset.current_generation_id to vrt_generations (L6).

Model-only changes (H6-H8, M8-M9, L4, L7) reflect existing DB constraints
into SQLAlchemy models and require no DB migration.

Revision ID: 0011_model_review_fixes
Revises: 0010_add_saml_provider_columns
Create Date: 2026-03-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_model_review_fixes"
down_revision = "0010_add_saml_provider_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Tier 1: Missing indexes (H1-H5, L2) ──────────────────────────────
    op.create_index(
        "idx_api_keys_user_id", "api_keys", ["user_id"], schema="catalog"
    )
    op.create_index(
        "idx_ingest_jobs_created_by", "ingest_jobs", ["created_by"], schema="catalog"
    )
    op.create_index(
        "idx_maps_created_by", "maps", ["created_by"], schema="catalog"
    )
    op.create_index(
        "idx_records_created_at_desc",
        "records",
        [sa.text("created_at DESC")],
        schema="catalog",
    )
    op.create_index(
        "idx_records_source_organization",
        "records",
        ["source_organization"],
        schema="catalog",
        postgresql_where=sa.text("source_organization IS NOT NULL"),
    )
    op.create_index(
        "idx_oauth_accounts_user_id", "oauth_accounts", ["user_id"], schema="catalog"
    )

    # ── H9: Fix record_type CHECK to include 'table' ─────────────────────
    op.execute(
        "ALTER TABLE catalog.records DROP CONSTRAINT IF EXISTS chk_records_record_type"
    )
    op.execute("""
        ALTER TABLE catalog.records ADD CONSTRAINT chk_records_record_type
            CHECK (record_type IN (
                'vector_dataset', 'raster_dataset', 'vrt_dataset',
                'map', 'service', 'collection', 'table'
            ))
    """)

    # ── Tier 3: New CHECK constraints (M1-M7, M13-M15) ───────────────────
    op.execute("""
        ALTER TABLE catalog.maps ADD CONSTRAINT chk_maps_visibility
            CHECK (visibility IN ('private', 'public', 'unlisted'))
    """)
    op.execute("""
        ALTER TABLE catalog.ingest_jobs ADD CONSTRAINT chk_ingest_jobs_status
            CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
    """)
    op.execute("""
        ALTER TABLE catalog.users ADD CONSTRAINT chk_users_status
            CHECK (status IN ('active', 'pending', 'suspended', 'deactivated'))
    """)
    op.execute("""
        ALTER TABLE catalog.users ADD CONSTRAINT chk_users_auth_provider
            CHECK (auth_provider IN ('local', 'oidc', 'saml'))
    """)
    op.execute("""
        ALTER TABLE catalog.raster_assets ADD CONSTRAINT chk_raster_assets_cog_status
            CHECK (cog_status IS NULL OR cog_status IN ('compliant', 'non_compliant', 'unknown'))
    """)
    op.execute("""
        ALTER TABLE catalog.vrt_generations ADD CONSTRAINT chk_vrt_generations_status
            CHECK (status IN ('pending', 'running', 'completed', 'failed'))
    """)
    op.execute("""
        ALTER TABLE catalog.oauth_providers ADD CONSTRAINT chk_oauth_providers_type
            CHECK (provider_type IN ('oidc', 'google', 'microsoft', 'saml'))
    """)
    op.execute("""
        ALTER TABLE catalog.map_layers ADD CONSTRAINT chk_map_layers_layer_type
            CHECK (layer_type IN ('vector_geolens', 'raster_geolens', 'geojson'))
    """)
    op.execute("""
        ALTER TABLE catalog.raster_assets ADD CONSTRAINT chk_raster_assets_storage_backend
            CHECK (storage_backend IN ('local', 's3'))
    """)
    op.execute("""
        ALTER TABLE catalog.dataset_assets ADD CONSTRAINT chk_dataset_assets_key
            CHECK (key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata'))
    """)

    # ── M10: Narrow Map.basemap_style Text->String(30), visibility Text->String(20) ──
    op.alter_column(
        "maps",
        "basemap_style",
        type_=sa.String(30),
        existing_type=sa.Text(),
        schema="catalog",
    )
    op.alter_column(
        "maps",
        "visibility",
        type_=sa.String(20),
        existing_type=sa.Text(),
        schema="catalog",
    )

    # ── L6: Add FK from RasterAsset.current_generation_id to vrt_generations ──
    op.create_foreign_key(
        "fk_raster_assets_current_generation",
        "raster_assets",
        "vrt_generations",
        ["current_generation_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # L6
    op.drop_constraint(
        "fk_raster_assets_current_generation", "raster_assets", schema="catalog"
    )

    # M10
    op.alter_column(
        "maps",
        "visibility",
        type_=sa.Text(),
        existing_type=sa.String(20),
        schema="catalog",
    )
    op.alter_column(
        "maps",
        "basemap_style",
        type_=sa.Text(),
        existing_type=sa.String(30),
        schema="catalog",
    )

    # CHECK constraints (M1-M7, M13-M15)
    op.execute("ALTER TABLE catalog.dataset_assets DROP CONSTRAINT IF EXISTS chk_dataset_assets_key")
    op.execute("ALTER TABLE catalog.raster_assets DROP CONSTRAINT IF EXISTS chk_raster_assets_storage_backend")
    op.execute("ALTER TABLE catalog.map_layers DROP CONSTRAINT IF EXISTS chk_map_layers_layer_type")
    op.execute("ALTER TABLE catalog.oauth_providers DROP CONSTRAINT IF EXISTS chk_oauth_providers_type")
    op.execute("ALTER TABLE catalog.vrt_generations DROP CONSTRAINT IF EXISTS chk_vrt_generations_status")
    op.execute("ALTER TABLE catalog.raster_assets DROP CONSTRAINT IF EXISTS chk_raster_assets_cog_status")
    op.execute("ALTER TABLE catalog.users DROP CONSTRAINT IF EXISTS chk_users_auth_provider")
    op.execute("ALTER TABLE catalog.users DROP CONSTRAINT IF EXISTS chk_users_status")
    op.execute("ALTER TABLE catalog.ingest_jobs DROP CONSTRAINT IF EXISTS chk_ingest_jobs_status")
    op.execute("ALTER TABLE catalog.maps DROP CONSTRAINT IF EXISTS chk_maps_visibility")

    # H9 — restore original record_type CHECK without 'table'
    op.execute("ALTER TABLE catalog.records DROP CONSTRAINT IF EXISTS chk_records_record_type")
    op.execute("""
        ALTER TABLE catalog.records ADD CONSTRAINT chk_records_record_type
            CHECK (record_type IN (
                'vector_dataset', 'raster_dataset', 'vrt_dataset',
                'map', 'service', 'collection'
            ))
    """)

    # Indexes (H1-H5, L2)
    op.drop_index("idx_oauth_accounts_user_id", "oauth_accounts", schema="catalog")
    op.drop_index("idx_records_source_organization", "records", schema="catalog")
    op.drop_index("idx_records_created_at_desc", "records", schema="catalog")
    op.drop_index("idx_maps_created_by", "maps", schema="catalog")
    op.drop_index("idx_ingest_jobs_created_by", "ingest_jobs", schema="catalog")
    op.drop_index("idx_api_keys_user_id", "api_keys", schema="catalog")
