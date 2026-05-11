import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Map(Base):
    __tablename__ = "maps"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'public', 'internal')",
            name="chk_maps_visibility",
        ),
        # Trigram GIN indexes added in migration 0010 (H-07) — declared on the
        # model so alembic check sees them; the migration is the source of truth.
        # `postgresql_ops` puts the operator class outside the expression so
        # alembic's index compare can match the indexed expression.
        Index(
            "ix_maps_name_trgm",
            text("lower(name)"),
            postgresql_using="gin",
            postgresql_ops={"lower(name)": "gin_trgm_ops"},
        ),
        Index(
            "ix_maps_description_trgm",
            text("lower(coalesce(description, ''))"),
            postgresql_using="gin",
            postgresql_ops={
                "lower(coalesce(description, ''))": "gin_trgm_ops"
            },
        ),
        # DBM-06 (Phase 271): Map.visibility composite index intentionally
        # NOT created. The RBAC list-public-maps query uses
        # `WHERE visibility = 'public' AND created_by = ?` and similar combos.
        # db-audit M-18 recommended adding `Index('ix_maps_visibility_creator',
        # 'visibility', 'created_by')` once a real-world metric warranted it.
        # Revisit trigger: EXPLAIN (ANALYZE) on the public-maps list query
        # shows a sequential scan against catalog.maps when row count exceeds
        # ~10k. Until then, the cost of an extra index (write maintenance +
        # disk) outweighs the latency benefit. See docs/db-index-deferrals.md.
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Viewport state
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    zoom: Mapped[float | None] = mapped_column(Float, nullable=True)
    bearing: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    pitch: Mapped[float] = mapped_column(Float, default=0, server_default="0")

    # Basemap
    basemap_style: Mapped[str] = mapped_column(
        String(2000),
        default="openfreemap-positron",
        server_default="openfreemap-positron",
    )
    show_basemap_labels: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    basemap_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Active widget IDs (null = use client defaults, [] = no widgets)
    widgets: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

    # Map-level terrain configuration (null = terrain disabled/unconfigured)
    terrain_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Visibility
    visibility: Mapped[str] = mapped_column(
        String(20), default="private", server_default="private"
    )

    # Preview thumbnail — storage key (e.g. "maps/thumbnails/{id}.jpg")
    thumbnail_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lineage (fork tracking)
    forked_from: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="SET NULL"), nullable=True
    )

    # Ownership
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MapLayer(Base):
    __tablename__ = "map_layers"
    __table_args__ = (
        CheckConstraint(
            "layer_type IN ('vector_geolens', 'raster_geolens', 'geojson')",
            name="chk_map_layers_layer_type",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    opacity: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    paint: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    layout: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    layer_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="vector_geolens"
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    filter: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    label_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    popup_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    style_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    show_in_legend: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MapEditHistoryEvent(Base):
    __tablename__ = "map_edit_history_events"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('map', 'layer')",
            name="chk_map_edit_history_events_target_type",
        ),
        Index(
            "ix_catalog_map_edit_history_events_map_created_at",
            "map_id",
            "created_at",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MapShareToken(Base):
    __tablename__ = "map_share_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_map_share_tokens_token_hash"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_hint: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MapIconAsset(Base):
    __tablename__ = "map_icon_assets"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_map_icon_assets_slug"),
        CheckConstraint(
            "media_type IN ('image/svg+xml', 'image/png')",
            name="chk_map_icon_assets_media_type",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog.users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
