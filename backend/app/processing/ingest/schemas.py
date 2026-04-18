"""Pydantic request/response models for ingestion endpoints."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

Visibility = Literal["private", "restricted", "internal", "public"]


class UploadResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Unique identifier for the ingestion job. Use this to poll status and to commit the upload."
    )
    status: str = Field(
        default="pending",
        description="Initial job status. Always 'pending' on creation.",
    )
    message: str = Field(
        description="Human-readable message describing the upload result."
    )


class PreviewResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the ingestion job being previewed."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded file, if known."
    )
    columns: list[dict] = Field(
        description="Detected attribute columns. Each entry includes name, type, and nullability."
    )
    crs: int | None = Field(
        description="Detected coordinate reference system EPSG code, or null if undetermined."
    )
    geometry_type: str | None = Field(
        description="Detected geometry type (Point, LineString, Polygon, MultiPolygon, etc.), or null for non-spatial data."
    )
    feature_count: int | None = Field(
        description="Total number of features in the source file, if known."
    )
    sample_rows: list[dict] = Field(
        description="Up to 5 sample rows from the source file for preview purposes."
    )
    layer_name: str = Field(
        description="Name of the layer being previewed. Defaults to the source filename for single-layer files."
    )
    layers: list[dict] | None = Field(
        default=None,
        description="List of all layers in multi-layer sources (e.g. GeoPackage). Null for single-layer files.",
    )
    detected_geometry_columns: dict | None = Field(
        default=None,
        description="Auto-detected lat/lon or geometry columns for CSV/Excel sources. Null for native geospatial formats.",
    )


class RasterPreviewResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the raster ingestion job being previewed."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded raster file."
    )
    crs_epsg: int | None = Field(
        description="Detected EPSG code for the raster's CRS, if available."
    )
    crs_wkt: str | None = Field(
        description="Full WKT representation of the raster's CRS."
    )
    band_count: int = Field(description="Number of raster bands.")
    width: int = Field(description="Raster width in pixels.")
    height: int = Field(description="Raster height in pixels.")
    dtype: str = Field(description="Pixel data type (e.g. 'uint8', 'float32').")
    nodata: float | str | None = Field(
        description="Nodata value for the raster, if defined."
    )
    res_x: float = Field(description="Pixel resolution along the X axis in CRS units.")
    res_y: float = Field(description="Pixel resolution along the Y axis in CRS units.")
    compression: str | None = Field(
        description="Existing compression method (e.g. 'LZW', 'DEFLATE'), or null for uncompressed."
    )
    file_size_bytes: int | None = Field(description="Source file size in bytes.")
    is_cog_compliant: bool = Field(
        description="Whether the source file is already a Cloud-Optimized GeoTIFF."
    )
    compliance_reason: str = Field(
        description="Explanation of COG compliance status. Lists missing requirements when not compliant."
    )
    temporal_start: str | None = Field(
        default=None,
        description="ISO 8601 acquisition timestamp parsed from raster metadata, if present.",
    )


class BaseCommitRequest(BaseModel):
    """Fields common to every commit request type.

    Not meant to be instantiated directly — the router always selects
    one of VectorCommitRequest, RasterCommitRequest, or
    ServiceCommitRequest based on server-side job state.
    """

    title: str = Field(
        min_length=1, max_length=500, description="Human-readable dataset title."
    )
    summary: str | None = Field(
        default=None, max_length=5000, description="Optional dataset description shown in the catalog."
    )
    visibility: Visibility = Field(
        default="private",
        description="Dataset visibility level: 'private' (owner-only), 'restricted' (RBAC-controlled), 'internal' (all users), 'public' (anonymous access).",
    )
    temporal_start: str | None = Field(
        default=None, description="ISO 8601 start of the dataset's temporal extent."
    )
    temporal_end: str | None = Field(
        default=None, description="ISO 8601 end of the dataset's temporal extent."
    )


class VectorCommitRequest(BaseCommitRequest):
    """Commit request for vector file uploads (GeoJSON, Shapefile, GPKG, CSV, etc.)."""

    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when source CRS is missing or incorrect. Forces reprojection during ingestion.",
    )
    layer_name: str | None = Field(
        default=None,
        description="Multi-layer source only: name of the specific layer to ingest.",
    )
    x_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the longitude/X coordinate column.",
    )
    y_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the latitude/Y coordinate column.",
    )
    geom_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the WKT geometry column (alternative to x_column/y_column).",
    )


class RasterCommitRequest(BaseCommitRequest):
    """Commit request for raster file uploads (GeoTIFF, VRT)."""

    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when source CRS is missing or incorrect. Forces reprojection during ingestion.",
    )
    compression: str | None = Field(
        default=None,
        description="Raster only: target compression for COG output (e.g. 'LZW', 'DEFLATE').",
    )
    resampling: str | None = Field(
        default=None,
        description="Raster only: resampling method for COG conversion (e.g. 'nearest', 'bilinear', 'cubic').",
    )
    nodata_override: float | str | None = Field(
        default=None,
        description="Raster only: nodata value to use when source has none defined.",
    )


class ServiceCommitRequest(BaseCommitRequest):
    """Commit request for remote service layers (WFS, ArcGIS FeatureServer)."""

    token: str | None = Field(
        default=None,
        description="Optional auth token for protected services. Never persisted to the database.",
    )


class CommitRequest(BaseModel):
    """Wire-level schema for ``POST /ingest/commit/{job_id}``.

    Preserved as a flat union of all possible commit fields so that the
    FastAPI route signature renders correctly in OpenAPI and so that the
    frontend's ``CommitImportRequest`` TypeScript type stays unchanged.

    The route handler re-validates the body against a subclass chosen by
    ``_pick_commit_subclass(job)`` (see ``app.ingest.router``):

      - ``VectorCommitRequest`` — default for file uploads
      - ``RasterCommitRequest`` — when ``job.user_metadata['file_type'] == 'raster'``
      - ``ServiceCommitRequest`` — when ``job.source_url`` is set and ``job.file_path`` is None

    For new internal code that constructs a commit view, prefer importing
    the appropriate subclass directly. This flat class is the wire contract,
    not an implementation detail.
    """

    title: str = Field(
        min_length=1, max_length=500, description="Human-readable dataset title."
    )
    summary: str | None = Field(
        default=None, max_length=5000, description="Optional dataset description shown in the catalog."
    )
    visibility: Visibility = Field(
        default="private",
        description="Dataset visibility level: 'private' (owner-only), 'restricted' (RBAC-controlled), 'internal' (all users), 'public' (anonymous access).",
    )
    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when source CRS is missing or incorrect. Forces reprojection during ingestion.",
    )
    token: str | None = Field(
        default=None,
        description="Optional confirmation token returned by the preview step. Required for some workflows.",
    )
    temporal_start: str | None = Field(
        default=None, description="ISO 8601 start of the dataset's temporal extent."
    )
    temporal_end: str | None = Field(
        default=None, description="ISO 8601 end of the dataset's temporal extent."
    )
    compression: str | None = Field(
        default=None,
        description="Raster only: target compression for COG output (e.g. 'LZW', 'DEFLATE').",
    )
    resampling: str | None = Field(
        default=None,
        description="Raster only: resampling method for COG conversion (e.g. 'nearest', 'bilinear', 'cubic').",
    )
    nodata_override: float | str | None = Field(
        default=None,
        description="Raster only: nodata value to use when source has none defined.",
    )
    layer_name: str | None = Field(
        default=None,
        description="Multi-layer source only: name of the specific layer to ingest.",
    )
    x_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the longitude/X coordinate column.",
    )
    y_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the latitude/Y coordinate column.",
    )
    geom_column: str | None = Field(
        default=None,
        description="CSV/Excel only: name of the WKT geometry column (alternative to x_column/y_column).",
    )


class CommitResponse(BaseModel):
    job_id: uuid.UUID = Field(description="Identifier of the committed ingestion job.")
    status: str = Field(description="Updated job status after commit.")
    message: str = Field(description="Human-readable commit result.")


class RegisterRequest(BaseModel):
    table_name: str = Field(
        min_length=1,
        max_length=63,
        description="PostgreSQL table name in the `data` schema (max 63 chars per PostgreSQL identifier limit).",
    )
    title: str = Field(
        max_length=500, description="Human-readable dataset title shown in the catalog."
    )
    summary: str | None = Field(
        default=None, max_length=5000, description="Optional dataset description."
    )
    visibility: Visibility = Field(
        default="private", description="Dataset visibility level."
    )


class TableRegisterResponse(BaseModel):
    dataset_id: uuid.UUID = Field(
        description="Identifier of the newly registered dataset."
    )
    title: str = Field(description="Title of the registered dataset.")
    table_name: str = Field(description="Source PostgreSQL table that was registered.")


class DiscoveredTable(BaseModel):
    table_name: str = Field(description="PostgreSQL table name in the `data` schema.")
    geometry_type: str | None = Field(
        description="Detected geometry type, or null for non-spatial tables."
    )
    srid: int | None = Field(
        description="Coordinate reference system EPSG code, if defined."
    )
    estimated_rows: int | None = Field(
        description="PostgreSQL row count estimate from `pg_class.reltuples`."
    )


class DiscoverResponse(BaseModel):
    tables: list[DiscoveredTable] = Field(
        description="Tables in the `data` schema that are eligible for registration as datasets."
    )


class BulkRegisterItem(BaseModel):
    table_name: str = Field(
        max_length=63, description="PostgreSQL table name to register."
    )
    title: str = Field(max_length=500, description="Human-readable dataset title.")
    summary: str | None = Field(
        default=None, max_length=5000, description="Optional dataset description."
    )
    visibility: Visibility = Field(
        default="private", description="Dataset visibility level."
    )


class BulkRegisterRequest(BaseModel):
    tables: list[BulkRegisterItem] = Field(
        description="List of tables to register as datasets in a single request."
    )


class BulkRegisterResult(BaseModel):
    table_name: str = Field(description="Source table that was processed.")
    status: str = Field(
        description="Per-row outcome: 'success', 'skipped', or 'error'."
    )
    dataset_id: uuid.UUID | None = Field(
        default=None, description="ID of the created dataset on success."
    )
    title: str | None = Field(
        default=None, description="Title of the created dataset on success."
    )
    error: str | None = Field(default=None, description="Error message on failure.")


class BulkRegisterResponse(BaseModel):
    results: list[BulkRegisterResult] = Field(
        description="Per-table registration results, in the same order as the request."
    )


# ---------------------------------------------------------------------------
# Presigned S3 upload schemas
# ---------------------------------------------------------------------------


class PresignedUploadRequest(BaseModel):
    filename: str = Field(
        min_length=1,
        max_length=255,  # filesystem + S3 object-key practical limit
        description="Original filename being uploaded. Used to determine the file extension and content disposition.",
    )
    file_size: int = Field(
        ge=1,
        description="Total file size in bytes. Used to decide between single-part and multipart upload.",
    )
    content_type: str = Field(
        default="application/octet-stream",
        max_length=255,  # RFC 6838 practical upper bound
        description="MIME type to associate with the uploaded object.",
    )


class PresignedPartInfo(BaseModel):
    etag: str = Field(description="ETag returned by S3 for an uploaded multipart part.")
    part_number: int = Field(description="1-indexed part number of the uploaded part.")


class PresignedCompleteRequest(BaseModel):
    parts: list[PresignedPartInfo] = Field(
        default=[],
        description="Ordered list of uploaded parts (etag + part_number) used to complete a multipart upload.",
    )


class PresignedUploadResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the ingestion job created for this upload."
    )
    urls: list[str] = Field(
        description="One presigned PUT URL per part. Single-element list for single-part uploads."
    )
    s3_key: str = Field(
        description="Object key in the S3 bucket where the file will be stored."
    )
    upload_id: str | None = Field(
        default=None,
        description="S3 multipart upload ID, set only for multipart uploads.",
    )
    part_size: int | None = Field(
        default=None, description="Byte size of each part in a multipart upload."
    )


class UploadConfigResponse(BaseModel):
    presigned_uploads: bool = Field(
        description="Whether presigned S3 uploads are enabled (requires `STORAGE_PROVIDER=s3`)."
    )
    presigned_threshold_bytes: int = Field(
        description="File size threshold (bytes) above which multipart presigned URLs are used."
    )
    max_file_size_bytes: int = Field(
        description="Maximum allowed upload size in bytes."
    )
    allowed_extensions: str = Field(
        description="Comma-separated list of allowed file extensions."
    )


# ---------------------------------------------------------------------------
# VRT creation schemas
# ---------------------------------------------------------------------------


class VrtCreateRequest(BaseModel):
    source_dataset_ids: list[uuid.UUID] = Field(
        description="Source raster dataset IDs to include in the VRT mosaic or band stack."
    )
    vrt_type: Literal["mosaic", "band_stack"] = Field(
        description="Type of VRT to create. 'mosaic' tiles sources spatially; 'band_stack' aligns same-extent sources as multi-band output."
    )
    resolution_strategy: Literal["finest", "coarsest", "average"] = Field(
        description="How to resolve mismatched source resolutions: 'finest' uses the highest, 'coarsest' uses the lowest, 'average' computes the mean."
    )
    title: str = Field(
        max_length=500,
        description="Human-readable title for the resulting VRT dataset.",
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional description for the VRT dataset.",
    )
    visibility: Visibility = Field(
        default="private", description="Visibility level for the resulting VRT dataset."
    )


class VrtCreateResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the asynchronous VRT creation job."
    )
    status: str = Field(
        default="accepted",
        description="Initial job status. Always 'accepted' on creation.",
    )
    message: str = Field(description="Human-readable acceptance message.")


class VrtAddSourceRequest(BaseModel):
    source_dataset_id: uuid.UUID = Field(
        description="Raster dataset ID to add as an additional source to the existing VRT."
    )


class VrtMutationResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the asynchronous VRT mutation job."
    )
    status: str = Field(default="accepted", description="Initial job status.")
    message: str = Field(description="Human-readable acceptance message.")
