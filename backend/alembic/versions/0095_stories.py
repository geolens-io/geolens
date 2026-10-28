"""Stories and the maps their scenes use.

``stories`` is a tenant root like ``maps``: a stamped ``tenant_id`` and a
fail-closed policy. ``story_maps`` takes its ``tenant_id`` from its story, and
a validator refuses a map from another tenant, including for privileged
maintenance SQL. Both policies stay dormant until ``apply_tenancy_rls()``
enables them in multi-tenant mode. The migration only adds tables, so the
previous release runs unaffected during a rolling upgrade.

Revision ID: 0095_stories
Revises: 0094_dataset_version_columns
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0095_stories"
down_revision: Union[str, None] = "0094_dataset_version_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STAMP_TRIGGER = "trg_stamp_current_tenant_on_insert"
_STAMP_FUNCTION = "catalog.stamp_current_tenant_on_insert"
# PostgreSQL fires same-event triggers in name order, so the validator sees
# the tenant the stamp trigger set.
_MAP_TRIGGER = "trg_validate_story_map_tenant"
_MAP_FUNCTION = "catalog.enforce_story_map_tenant"


def _tenant_boundary(table: str) -> None:
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON catalog.{table} "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)"
    )
    op.execute(
        f"CREATE TRIGGER {_STAMP_TRIGGER} BEFORE INSERT ON catalog.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION {_STAMP_FUNCTION}()"
    )


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="private"
        ),
        sa.Column("draft", JSONB(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published", JSONB(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public', 'internal', 'restricted')",
            name="chk_stories_visibility",
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_stories_created_by", "stories", ["created_by"], schema="catalog"
    )
    op.create_table(
        "story_maps",
        sa.Column(
            "story_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.stories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "map_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog.maps.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        schema="catalog",
    )
    op.create_index("ix_story_maps_map_id", "story_maps", ["map_id"], schema="catalog")

    _tenant_boundary("stories")
    _tenant_boundary("story_maps")

    # SECURITY INVOKER: under hosted RLS another tenant's story or map is
    # invisible here and reads as missing; the explicit comparison covers a
    # role that bypasses RLS.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_MAP_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, catalog
        AS $$
        DECLARE
            story_tenant uuid;
            map_tenant uuid;
        BEGIN
            SELECT tenant_id INTO story_tenant
            FROM catalog.stories
            WHERE id = NEW.story_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Story % does not exist', NEW.story_id
                    USING ERRCODE = '23503';
            END IF;

            SELECT tenant_id INTO map_tenant
            FROM catalog.maps
            WHERE id = NEW.map_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Map % does not exist', NEW.map_id
                    USING ERRCODE = '23503';
            END IF;

            IF map_tenant IS DISTINCT FROM story_tenant THEN
                RAISE EXCEPTION 'Story map tenant does not match story tenant'
                    USING ERRCODE = '42501';
            END IF;

            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := story_tenant;
            ELSIF NEW.tenant_id IS DISTINCT FROM story_tenant THEN
                RAISE EXCEPTION 'Story map tenant does not match story tenant'
                    USING ERRCODE = '42501';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {_MAP_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF story_id, map_id, tenant_id "
        "ON catalog.story_maps "
        f"FOR EACH ROW EXECUTE FUNCTION {_MAP_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_MAP_TRIGGER} ON catalog.story_maps")
    op.execute(f"DROP FUNCTION IF EXISTS {_MAP_FUNCTION}()")
    op.drop_index("ix_story_maps_map_id", table_name="story_maps", schema="catalog")
    op.drop_table("story_maps", schema="catalog")
    op.drop_index("ix_stories_created_by", table_name="stories", schema="catalog")
    op.drop_table("stories", schema="catalog")
