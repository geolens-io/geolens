import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Map(Base):
    __tablename__ = "maps"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'public', 'unlisted')",
            name="chk_maps_visibility",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Viewport state
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    zoom: Mapped[float | None] = mapped_column(Float, nullable=True)
    bearing: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    pitch: Mapped[float] = mapped_column(Float, default=0, server_default="0")

    # Basemap
    basemap_style: Mapped[str] = mapped_column(
        String(30), default="openfreemap-positron", server_default="openfreemap-positron"
    )

    # Visibility
    visibility: Mapped[str] = mapped_column(
        String(20), default="private", server_default="private"
    )

    # Preview thumbnail (base64 data URI)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
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
    filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    label_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    style_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    show_in_legend: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MapShareToken(Base):
    __tablename__ = "map_share_tokens"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    map_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.maps.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
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
