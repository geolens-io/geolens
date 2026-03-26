"""normalize outline paint props in map_layers

Revision ID: 0008_normalize_outline_paint
Revises: 0007_add_user_last_login_at
Create Date: 2026-03-26
"""

from alembic import op

revision = "0008_normalize_outline_paint"
down_revision = "0007_add_user_last_login_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename non-prefixed -> prefixed where prefixed doesn't already exist
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - 'outline-width') || jsonb_build_object('_outline-width', paint->'outline-width')
        WHERE paint ? 'outline-width' AND NOT (paint ? '_outline-width')
    """)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - 'outline-color') || jsonb_build_object('_outline-color', paint->'outline-color')
        WHERE paint ? 'outline-color' AND NOT (paint ? '_outline-color')
    """)
    # Remove non-prefixed where both exist (prefixed takes precedence)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = paint - 'outline-width'
        WHERE paint ? 'outline-width' AND paint ? '_outline-width'
    """)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = paint - 'outline-color'
        WHERE paint ? 'outline-color' AND paint ? '_outline-color'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - '_outline-width') || jsonb_build_object('outline-width', paint->'_outline-width')
        WHERE paint ? '_outline-width'
    """)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - '_outline-color') || jsonb_build_object('outline-color', paint->'_outline-color')
        WHERE paint ? '_outline-color'
    """)
