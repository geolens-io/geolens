import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.geo import crs_columns


class RasterAsset(Base):
    __tablename__ = "raster_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_raster_assets_dataset"),
        CheckConstraint(
            "status IN ('ready', 'regenerating', 'failed')",
            name="chk_raster_assets_status",
        ),
        CheckConstraint(
            "vrt_type IS NULL OR vrt_type IN ('mosaic', 'band_stack')",
            name="chk_raster_assets_vrt_type",
        ),
        CheckConstraint(
            "cog_status IS NULL OR cog_status IN ('verified', 'converted', 'unknown')",
            name="chk_raster_assets_cog_status",
        ),
        CheckConstraint(
            "storage_backend IN ('local', 's3', 'remote')",
            name="chk_raster_assets_storage_backend",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )

    # -- Internal processing fields --
    asset_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    driver: Mapped[str | None] = mapped_column(String(50), nullable=True)
    storage_backend: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="local"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cog_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quicklook_256_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    quicklook_512_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_rotated: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    is_dem: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # -- STAC-facing descriptive metadata --
    crs_wkt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Derived from crs_wkt and written with it (crs_columns), so requests read
    # these instead of handing the stored text to PROJ. NULL is unknown.
    crs_is_geographic: Mapped[bool | None] = mapped_column(nullable=True)
    crs_has_degree_unit: Mapped[bool | None] = mapped_column(nullable=True)
    crs_metres_per_unit: Mapped[float | None] = mapped_column(Double, nullable=True)
    # SHA-256 of the crs_wkt those facts describe; see crs_columns.
    crs_facts_digest: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dtype: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nodata: Mapped[str | None] = mapped_column(Text, nullable=True)
    res_x: Mapped[float | None] = mapped_column(Double, nullable=True)
    res_y: Mapped[float | None] = mapped_column(Double, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compression: Mapped[str | None] = mapped_column(String(30), nullable=True)
    band_info: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # -- VRT tracking columns --
    vrt_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ready"
    )
    # NOTE: Not a FK — router code sets this to uuid.uuid4() as a placeholder before
    # the VRT regeneration task creates the actual VrtGeneration row.
    current_generation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_regenerated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # fix(#1290): what the published VRT was assembled FROM, as
    # {dataset_id: asset_uri}. Member staleness is a state comparison against
    # this — what a member IS versus what the artifact was built from — because
    # no timestamp can express "committed after my snapshot" (Postgres has no
    # commit-time stamp available inside the transaction). NULL means the VRT
    # predates this column and the health endpoint falls back to the legacy
    # timestamp comparison for it.
    built_from: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def set_crs(self, meta: dict) -> None:
        """Replace the stored CRS text and its facts together."""
        for column, value in crs_columns(meta).items():
            setattr(self, column, value)


class VrtGeneration(Base):
    __tablename__ = "vrt_generations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_vrt_generations_status",
        ),
        # DBM-10 covering index added in migration 0001_baseline — model declares it
        # so alembic check sees it; the migration is the source of truth.
        Index("ix_vrt_generations_vrt_dataset_id", "vrt_dataset_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    vrt_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Double, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # fix(#1327): the FULL post-mutation member set this generation intends
    # to publish (ordered dataset ids). Staged here, not applied to
    # `vrt_source_links` until the regeneration task's SAME transaction as
    # the artifact swap — a dead attempt leaves the catalog and served
    # bytes in agreement.
    #
    # A full set, not a delta: apply is a replace, idempotent on retry.
    # NULL means "no membership change" (plain regenerate, or pre-column
    # generations) — both build from the live links.
    staged_source_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VrtSourceLink(Base):
    """Tracks which COG datasets are sources for a VRT dataset."""

    __tablename__ = "vrt_source_links"
    __table_args__ = (
        UniqueConstraint(
            "vrt_dataset_id", "source_dataset_id", name="uq_vsl_vrt_source"
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    vrt_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DatasetAsset(Base):
    """STAC-aligned asset reference table.

    One row per asset (COG file, VRT, thumbnail, overview) for a dataset.
    Stable keys: 'data' (COG), 'vrt', 'thumbnail' (256px), 'overview'
    (512px), 'metadata' (sidecar JSON), 'archived_original:<hash>' (one row
    per pre-conversion upload kept when COG conversion was lossy, ADR-002
    Decision 7 — hash-suffixed so every kept original counts, not just the
    newest), 'tileset' (a 3D Tiles dataset's live unpack attempt, sized to
    the unpacked bytes), 'pointcloud' (a COPC point cloud's live file, sized
    to the file). The archived, tileset and pointcloud keys are INTERNAL:
    they feed the per-user storage sum but are never published as STAC
    assets (see ``app.platform.assets.keys``).
    """

    __tablename__ = "dataset_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key"),
        CheckConstraint(
            "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata', 'tileset', "
            "'pointcloud') OR key LIKE 'archived_original:%'",
            name="chk_dataset_assets_key",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    href: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    roles: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
