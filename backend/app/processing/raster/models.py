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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.geo import wkt_metres_per_unit

# fix(#1778): shared with the OGC Records serializer, which cannot import from
# `app.processing` (CATPORT-02/04). See the module docstring for the two
# producer shapes these two functions reconcile.
from app.core.raster_bands import band_display_name, stac_band_nodata


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
    # fix(#1290 review): what the published VRT was assembled FROM, as
    # {dataset_id: asset_uri}. Member staleness is a state comparison against
    # this — what a member IS versus what the artifact was built from — because
    # no timestamp can express "committed after my snapshot" (Postgres has no
    # commit-time stamp available inside the transaction). NULL means the VRT
    # predates this column and the health endpoint falls back to the legacy
    # timestamp comparison for it.
    built_from: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def to_stac_properties(self) -> dict:
        """Extract STAC-compatible properties from raster metadata."""
        props: dict = {}
        if self.epsg is not None:
            props["proj:code"] = f"EPSG:{self.epsg}"
        if self.crs_wkt:
            props["proj:wkt2"] = self.crs_wkt
        if self.width is not None and self.height is not None:
            props["proj:shape"] = [self.height, self.width]
        if self.res_x is not None and self.res_y is not None:
            # fix(#1375 review): STAC defines `gsd` in METRES, while
            # `res_x`/`res_y` are in whatever unit the raster's CRS measures.
            # Publishing them raw made a 0.0001-degree EPSG:4326 pixel — an
            # ~11 m one, and 4326 is ordinary in the STAC catalogs #1375 now
            # reads resolutions from — export as `gsd: 0.0001`, which a
            # conforming consumer reads as a tenth of a millimetre. PROJ's
            # metres-per-unit converts every projected CRS, including the
            # foot-based state-plane systems this used to overstate by 3.28x.
            #
            # A geographic CRS yields None and the field is OMITTED, because
            # an angular resolution has no fixed length without a latitude
            # and `gsd` carries no unit of its own to qualify it. Omitting an
            # optional field is always conformant; a wrong number is not.
            # The OGC Records serializer deliberately keeps the CRS-unit
            # value (`service_records.py`, fix(#569)) — it ships a
            # `crs_is_geographic` flag beside it so its one consumer, the
            # GeoLens UI, can format the number. STAC has no such companion.
            metres_per_unit = wkt_metres_per_unit(self.crs_wkt)
            if metres_per_unit is not None:
                props["gsd"] = min(abs(self.res_x), abs(self.res_y)) * metres_per_unit

        # Bands (STAC Raster Extension v1.1 format)
        if self.band_info:
            bands = []
            for b in self.band_info:
                if not isinstance(b, dict):
                    continue
                band: dict = {}
                if b.get("dtype"):
                    band["data_type"] = b["dtype"]
                nodata = stac_band_nodata(b.get("nodata"))
                if nodata is not None:
                    band["nodata"] = nodata
                name = band_display_name(b)
                if name:
                    band["name"] = name
                # fix(#1778): an empty entry is dropped rather than appended.
                # A Producer-B row carries none of the three keys above, so
                # this list used to come out as `[{}, {}, {}]` and `if bands:`
                # published it: structurally invalid, and worse than omitting
                # the field.
                if band:
                    bands.append(band)
            if bands:
                props["raster:bands"] = bands

        return props


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
    # fix(#1327): the FULL post-mutation member set this generation intends to
    # publish, as an ordered JSON array of source dataset ids (position implied
    # by order). `add_vrt_source`/`remove_vrt_source` stage it here instead of
    # mutating `vrt_source_links` up front, and the regeneration task applies it
    # to the link table in the SAME transaction as the artifact swap. A dead
    # attempt therefore leaves the catalog's declared composition exactly where
    # the served bytes are, with nothing to compensate.
    #
    # A full set, not a delta: apply is then a replace, which is idempotent on
    # retry and needs no knowledge of what the links held when it was staged.
    # NULL means "this generation changes no membership" — a plain regenerate,
    # or any generation queued before this column existed. Both build from the
    # live links and apply nothing, so the fallback is one behavior with two
    # producers rather than a special case.
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

    Each row represents a single asset (COG file, VRT, thumbnail, overview)
    associated with a dataset. Stable asset keys:
      - 'data': Cloud-Optimized GeoTIFF
      - 'vrt': GDAL Virtual Raster
      - 'thumbnail': 256px quicklook
      - 'overview': 512px quicklook
      - 'metadata': sidecar metadata JSON
      - 'archived_original:<hash>': one row per pre-conversion upload kept
        when the COG conversion was lossy (ADR-002 Decision 7). The hash suffix
        makes the key per-archive, so every kept original is counted rather
        than only the newest. INTERNAL — it exists so the per-user storage sum
        can see those bytes, and it is deliberately not published as a STAC
        asset; see ``app.platform.assets.keys``.
    """

    __tablename__ = "dataset_assets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "key", name="uq_dataset_assets_key"),
        CheckConstraint(
            "key IN ('data', 'vrt', 'thumbnail', 'overview', 'metadata') "
            "OR key LIKE 'archived_original:%'",
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
