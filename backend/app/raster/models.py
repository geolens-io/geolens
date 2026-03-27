import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Double, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


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
            "storage_backend IN ('local', 's3')",
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

    # -- STAC-facing descriptive metadata --
    crs_wkt: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ready")
    # NOTE: Not a FK — router code sets this to uuid.uuid4() as a placeholder before
    # the VRT regeneration task creates the actual VrtGeneration row.
    current_generation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_regenerated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_stac_properties(self) -> dict:
        """Extract STAC-compatible properties from raster metadata."""
        props: dict = {}
        if self.epsg is not None:
            props["proj:epsg"] = self.epsg
        if self.crs_wkt:
            props["proj:wkt2"] = self.crs_wkt
        if self.width is not None and self.height is not None:
            props["proj:shape"] = [self.height, self.width]
        if self.res_x is not None and self.res_y is not None:
            props["gsd"] = min(abs(self.res_x), abs(self.res_y))

        # Bands (STAC 1.1 common metadata format)
        if self.band_info:
            bands = []
            for b in self.band_info:
                band: dict = {}
                if b.get("dtype"):
                    band["data_type"] = b["dtype"]
                if b.get("nodata") is not None:
                    band["nodata"] = b["nodata"]
                if b.get("color_interp"):
                    band["name"] = b["color_interp"]
                bands.append(band)
            if bands:
                props["bands"] = bands

        return props


class VrtGeneration(Base):
    __tablename__ = "vrt_generations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="chk_vrt_generations_status",
        ),
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Double, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
        ForeignKey("catalog.datasets.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    source_dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog.datasets.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DatasetAsset(Base):
    """STAC-aligned asset reference table.

    Each row represents a single asset (COG file, VRT, thumbnail, overview)
    associated with a dataset. Stable asset keys:
      - 'data': Cloud-Optimized GeoTIFF
      - 'vrt': GDAL Virtual Raster
      - 'thumbnail': 256px quicklook
      - 'overview': 512px quicklook
      - 'metadata': sidecar metadata JSON
    """

    __tablename__ = "dataset_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key"),
        CheckConstraint(
            "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata')",
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
