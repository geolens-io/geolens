"""Add map edit history events."""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_map_edit_history"
down_revision: Union[str, None] = "0006_map_icon_assets"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "map_edit_history_events",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("map_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_username", sa.String(length=150), nullable=True),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("target_name", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_type IN ('map', 'layer')",
            name="chk_map_edit_history_events_target_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["catalog.users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["map_id"], ["catalog.maps.id"], ondelete="CASCADE"),
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_edit_history_events_action",
        "map_edit_history_events",
        ["action"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_edit_history_events_actor_id",
        "map_edit_history_events",
        ["actor_id"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_edit_history_events_map_created_at",
        "map_edit_history_events",
        ["map_id", "created_at"],
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_map_edit_history_events_map_id",
        "map_edit_history_events",
        ["map_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_map_edit_history_events_map_id",
        table_name="map_edit_history_events",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_map_edit_history_events_map_created_at",
        table_name="map_edit_history_events",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_map_edit_history_events_actor_id",
        table_name="map_edit_history_events",
        schema="catalog",
    )
    op.drop_index(
        "ix_catalog_map_edit_history_events_action",
        table_name="map_edit_history_events",
        schema="catalog",
    )
    op.drop_table("map_edit_history_events", schema="catalog")
