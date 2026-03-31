"""Add missing FK indexes on high-traffic join/cascade tables.

btree indexes on: map_layers.map_id, map_layers.dataset_id,
record_contacts.record_id, record_distributions.record_id.

Note: record_embeddings HNSW index is intentionally NOT managed here.
The embedding column is dimensionless (configurable at runtime), so
the HNSW index is created/rebuilt dynamically by the backfill service
and the settings router when embedding dimensions change.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30
"""

from typing import Union

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_catalog_map_layers_map_id"),
        "map_layers",
        ["map_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_map_layers_dataset_id"),
        "map_layers",
        ["dataset_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_record_contacts_record_id"),
        "record_contacts",
        ["record_id"],
        schema="catalog",
    )
    op.create_index(
        op.f("ix_catalog_record_distributions_record_id"),
        "record_distributions",
        ["record_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_catalog_record_distributions_record_id"),
        table_name="record_distributions",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_record_contacts_record_id"),
        table_name="record_contacts",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_map_layers_dataset_id"),
        table_name="map_layers",
        schema="catalog",
    )
    op.drop_index(
        op.f("ix_catalog_map_layers_map_id"),
        table_name="map_layers",
        schema="catalog",
    )
