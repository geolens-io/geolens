"""Add missing FK indexes on map_share_tokens, saved_searches, audit_logs,
ingest_jobs, and dataset_relationships.

Identified by db-audit-20260407: these foreign key columns lacked indexes,
causing sequential scans on lookups and cascade deletes.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-07
"""

from typing import Union

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_catalog_map_share_tokens_map_id"),
        "map_share_tokens",
        ["map_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_saved_searches_user_id"),
        "saved_searches",
        ["user_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_audit_logs_user_id"),
        "audit_logs",
        ["user_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_ingest_jobs_dataset_id"),
        "ingest_jobs",
        ["dataset_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_dataset_relationships_target_dataset_id"),
        "dataset_relationships",
        ["target_dataset_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_catalog_dataset_relationships_target_dataset_id"),
        table_name="dataset_relationships",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_ingest_jobs_dataset_id"),
        table_name="ingest_jobs",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_audit_logs_user_id"),
        table_name="audit_logs",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_saved_searches_user_id"),
        table_name="saved_searches",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_map_share_tokens_map_id"),
        table_name="map_share_tokens",
        schema="catalog",
    )
