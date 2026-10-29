"""Story images: uploaded assets and a story cover.

``story_assets`` takes its ``tenant_id`` from its story, as ``story_maps``
does, with a stamped tenant and a fail-closed policy that stay dormant until
``apply_tenancy_rls()`` enables them in multi-tenant mode. ``stories`` gains a
nullable ``cover_asset_id``. The migration only adds, so the previous release
runs unaffected during a rolling upgrade.

Revision ID: 0097_story_assets
Revises: 0096_map_dashboard_config
Create Date: 2026-10-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0097_story_assets"
down_revision: Union[str, None] = "0096_map_dashboard_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order, so the validator sees
# the tenant the stamp trigger set.
_ASSET_TRIGGER = "trg_validate_story_asset_tenant"
_ASSET_FUNCTION = "catalog.enforce_story_asset_tenant"
_COVER_FK = "fk_stories_cover_asset_id"
_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.create_table(
        "story_assets",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "story_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.stories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_story_assets_story_id", "story_assets", ["story_id"], schema="catalog"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_story_assets ON catalog.story_assets "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
    op.execute(
        f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.story_assets "
        f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
    )
    # SECURITY INVOKER: under hosted RLS another tenant's story is invisible
    # here and reads as missing; the explicit comparison covers a role that
    # bypasses RLS.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_ASSET_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            story_tenant uuid;
        BEGIN
            SELECT tenant_id INTO story_tenant
            FROM catalog.stories
            WHERE id = NEW.story_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Story % does not exist', NEW.story_id
                    USING ERRCODE = '23503';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := story_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM story_tenant THEN
                RAISE EXCEPTION 'Story asset tenant does not match story tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_ASSET_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF story_id, tenant_id "
        "ON catalog.story_assets "
        f"FOR EACH ROW EXECUTE FUNCTION {_ASSET_FUNCTION}()"
    )

    op.add_column(
        "stories",
        sa.Column("cover_asset_id", UUID(as_uuid=True), nullable=True),
        schema="catalog",
    )
    op.create_foreign_key(
        _COVER_FK,
        "stories",
        "story_assets",
        ["cover_asset_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_stories_cover_asset_id", "stories", ["cover_asset_id"], schema="catalog"
    )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.drop_index("ix_stories_cover_asset_id", table_name="stories", schema="catalog")
    op.drop_constraint(_COVER_FK, "stories", schema="catalog", type_="foreignkey")
    op.drop_column("stories", "cover_asset_id", schema="catalog")
    op.execute(f"DROP TRIGGER IF EXISTS {_ASSET_TRIGGER} ON catalog.story_assets")
    op.execute(f"DROP FUNCTION IF EXISTS {_ASSET_FUNCTION}()")
    op.drop_index(
        "ix_story_assets_story_id", table_name="story_assets", schema="catalog"
    )
    op.drop_table("story_assets", schema="catalog")
