"""Pydantic request/response models for ingestion endpoints."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.platform.service_auth import (
    DEPRECATED_TOKEN_SUFFIX,
    SERVICE_AUTH_FIELD_DESCRIPTION,
    ServiceAuthRequest,
    _validate_safe_token,
    reject_service_auth_conflict,
)

Visibility = Literal["private", "restricted", "internal", "public"]

TILESET_KIND_DESCRIPTION = (
    "'tiles3d' uploads a 3D Tiles tileset as a .zip or .3tz archive holding "
    "tileset.json. Omit it for any other file; a .zip without it is read as "
    "geospatial data, and a .3tz without it is refused."
)
UPLOAD_KIND_DESCRIPTION = (
    f"{TILESET_KIND_DESCRIPTION} 'pointcloud' uploads a COPC point cloud as a "
    ".laz file; a .laz without it is refused."
)


class UrlUploadRequest(BaseModel):
    """Request body for importing a file from a URL.

    The server validates the URL for SSRF, enforces the size limit, and stages
    the file through the same preview and commit flow as a direct upload.
    """

    url: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "HTTP(S) URL of the file to import. The server validates the URL "
            "against SSRF, downloads it with the configured size cap, and "
            "stages it like a direct upload."
        ),
    )
    filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description=(
            "Filename override for URLs whose path does not end in the "
            "actual file name (e.g. download links keyed by query id). "
            "Must carry an allowed extension. Defaults to the URL path's "
            "basename."
        ),
    )
    kind: Literal["tiles3d"] | None = Field(
        default=None, description=TILESET_KIND_DESCRIPTION
    )


class UploadResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Unique identifier for the ingestion job. Use this to poll status and to commit the upload."
    )
    status: str = Field(
        default="pending",
        description=(
            "Initial job status. 'pending' means the file is staged and "
            "ready to preview; 'running' means the server is still fetching "
            "it, as it is for a URL import."
        ),
    )
    message: str = Field(
        description="Human-readable message describing the upload result."
    )


class ColumnPreview(BaseModel):
    name: str
    type: str


class LayerPreview(BaseModel):
    name: str
    feature_count: int | None = None
    field_count: int | None = None


class PreviewResponse(BaseModel):
    job_id: uuid.UUID = Field(
        description="Identifier of the ingestion job being previewed."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded file, if known."
    )
    columns: list[ColumnPreview] = Field(
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
    sample_rows: list[dict[str, Any]] = Field(
        description="Up to 5 sample rows from the source file for preview purposes."
    )
    layer_name: str = Field(
        description="Name of the layer being previewed. Defaults to the source filename for single-layer files."
    )
    layers: list[LayerPreview] | None = Field(
        default=None,
        description="List of all layers in multi-layer sources (e.g. GeoPackage). Null for single-layer files.",
    )
    detected_geometry_columns: dict[str, Any] | None = Field(
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
    temporal_start: datetime | None = Field(
        default=None,
        description="ISO 8601 acquisition timestamp parsed from raster metadata, if present.",
    )


class TilesetPreviewResponse(BaseModel):
    """What a staged 3D Tiles tileset archive holds, read without unpacking it."""

    job_id: uuid.UUID = Field(
        description="Identifier of the tileset ingestion job being previewed."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded tileset archive."
    )
    version: Literal["1.0", "1.1"] = Field(
        description="The tileset's asset.version from its tileset.json."
    )
    geometric_error: float | None = Field(
        description="The root tile's geometricError, or null when tileset.json gives none."
    )
    bounding_volume: Literal["region", "box", "sphere"] = Field(
        description="The kind of the root tile's bounding volume."
    )
    extent_bbox: list[float] | None = Field(
        description=(
            "The root region as [west, south, east, north] in degrees; west > "
            "east when it crosses the antimeridian. Null for a box or sphere."
        )
    )
    unpacked_bytes: int = Field(
        description="Total size of the archive's files once unpacked."
    )
    entry_count: int = Field(
        description="Number of entries, files and folders, in the archive."
    )


class PointCloudPreviewResponse(BaseModel):
    """What a staged COPC point cloud holds, read from its header and hierarchy."""

    job_id: uuid.UUID = Field(
        description="Identifier of the point cloud ingestion job being previewed."
    )
    source_filename: str | None = Field(
        description="Original filename of the uploaded point cloud."
    )
    point_count: int = Field(description="Number of points in the file.")
    point_format: Literal[6, 7, 8] = Field(
        description="The file's LAS point data record format."
    )
    srid: int = Field(
        description="EPSG code of the horizontal coordinate reference system."
    )
    vertical_crs: str | None = Field(
        description="Name of the vertical coordinate reference system, if any."
    )
    extent_bbox: list[float] = Field(
        description=(
            "The extent as [west, south, east, north] in degrees; west > east "
            "when it crosses the antimeridian."
        )
    )
    z_min: float = Field(description="Lowest elevation, in the file's units.")
    z_max: float = Field(description="Highest elevation, in the file's units.")
    size_bytes: int = Field(description="Size of the file in bytes.")


StagedPreviewResponse = (
    PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | PointCloudPreviewResponse
)


class BaseCommitRequest(BaseModel):
    """Fields common to every commit request type.

    Not meant to be instantiated directly — the router always selects
    one of VectorCommitRequest, RasterCommitRequest, ServiceCommitRequest,
    TilesetCommitRequest or PointCloudCommitRequest based on server-side job
    state.
    """

    title: str = Field(
        min_length=1, max_length=500, description="Human-readable dataset title."
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional dataset description shown in the catalog.",
    )
    visibility: Visibility = Field(
        default="private",
        description="Dataset visibility level: 'private' (owner-only), 'restricted' (RBAC-controlled), 'internal' (all users), 'public' (anonymous access).",
    )
    temporal_start: datetime | None = Field(
        default=None, description="ISO 8601 start of the dataset's temporal extent."
    )
    temporal_end: datetime | None = Field(
        default=None, description="ISO 8601 end of the dataset's temporal extent."
    )


class VectorCommitRequest(BaseCommitRequest):
    """Commit request for vector file uploads (GeoJSON, Shapefile, GPKG, CSV, etc.)."""

    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when the source CRS is missing or incorrect. Assigns (relabels) the CRS the source coordinates are read under; ingest then reprojects to EPSG:4326 as it does for every vector source.",
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


# fix(#1961): each of these reaches a conversion argument, which is the
# rewrite strict mode exists to refuse. Mirrors ``check_and_prepare_cog``'s
# own predicate, case-sensitive DEFLATE default included.
def reject_strict_cog_conflict(model: Any) -> Any:
    """Refuse a strict-COG commit that also asks for a rewrite.

    An ``@model_validator(mode="after")`` on ``RasterCommitRequest``, which
    the handler re-validates the body against, so a vector or service job
    sending a kitchen-sink body still commits. Passing the strict gate and
    then converting anyway would break the flag's contract, so for a raster
    job the combination is a 422.
    """
    if not model.strict_cog:
        return model
    offenders = [
        name
        for name, conflicts in (
            ("compression", (model.compression or "DEFLATE") != "DEFLATE"),
            ("resampling", bool(model.resampling)),
            ("nodata_override", model.nodata_override is not None),
            ("srid_override", model.srid_override is not None),
        )
        if conflicts
    ]
    if offenders:
        raise ValueError(
            "strict_cog cannot be combined with options that require a "
            f"rewrite: {', '.join(offenders)}. Drop the option or set "
            "strict_cog to false."
        )
    return model


class RasterCommitRequest(BaseCommitRequest):
    """Commit request for raster file uploads (GeoTIFF, VRT)."""

    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when the source CRS is missing or incorrect. Assigns (relabels) the CRS without resampling; pixel values are unchanged.",
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
    strict_cog: bool = Field(
        default=False,
        description=(
            "Raster only: reject a non-COG TIFF instead of converting it. "
            "False (the default) converts the source to a COG during ingest. "
            "True fails the job when the source is not already a compliant "
            "COG, and cannot be combined with resampling, nodata_override, "
            "srid_override or a compression other than the default DEFLATE: "
            "each of those is applied by a conversion, so the commit is "
            "refused with a 422 naming the fields that clash."
        ),
    )
    _reject_strict_cog_conflict = model_validator(mode="after")(
        reject_strict_cog_conflict
    )


class ServiceCommitRequest(BaseCommitRequest):
    """Commit request for remote service layers (WFS, OGC API Features, or ArcGIS)."""

    token: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "Optional auth token for protected services. Never persisted to "
            "the database. Deprecated: use the auth object with method bearer."
        ),
    )
    # fix(#1755): the deprecated flat spelling of a credential is held
    # to the same rule as the `auth` object beside it on this door.
    _validate_token = field_validator("token")(_validate_safe_token)
    # feat(#1746): declared LAST — the generated Python SDK gives each field
    # a positional slot in declaration order, and appending cannot move a
    # slot that already exists. Pinned by test_service_auth_contract_1746.
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


class TilesetCommitRequest(BaseCommitRequest):
    """Commit request for a 3D Tiles tileset archive: the common fields only."""


class PointCloudCommitRequest(BaseCommitRequest):
    """Commit request for a COPC point cloud: the common fields only."""


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
      - ``TilesetCommitRequest`` — when ``job.user_metadata['file_type'] == 'tiles3d'``

    For new internal code that constructs a commit view, prefer importing
    the appropriate subclass directly. This flat class is the wire contract,
    not an implementation detail.
    """

    title: str = Field(
        min_length=1, max_length=500, description="Human-readable dataset title."
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional dataset description shown in the catalog.",
    )
    visibility: Visibility = Field(
        default="private",
        description="Dataset visibility level: 'private' (owner-only), 'restricted' (RBAC-controlled), 'internal' (all users), 'public' (anonymous access).",
    )
    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description="EPSG code to use when the source CRS is missing or incorrect. Assigns (relabels) the CRS the source is read under rather than reprojecting from it: raster pixel values are unchanged, and vector geometries are reprojected to EPSG:4326 from the assigned CRS as usual.",
    )
    # fix(#1931): the cap is declared here as well as on ServiceCommitRequest
    # because only this model's schema is published, and a constraint a caller
    # cannot read is not part of the contract.
    token: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "Optional auth token for a protected remote service, read only "
            "when the job imports a service layer (WFS, OGC API Features, or ArcGIS). "
            "At most 1000 characters. Never persisted to the database. "
            "Ignored on file-upload jobs." + DEPRECATED_TOKEN_SUFFIX
        ),
    )
    temporal_start: datetime | None = Field(
        default=None, description="ISO 8601 start of the dataset's temporal extent."
    )
    temporal_end: datetime | None = Field(
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
    # feat(#1746): the handler re-validates ServiceCommitRequest from THIS
    # model's dump, so a field absent here is dropped before the subclass
    # ever sees it. Appended, never inserted, for the positional-slot reason above.
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    # fix(#1949): appended for that same reason rather than placed beside the
    # other raster fields, which would move five existing positional slots.
    strict_cog: bool = Field(
        default=False,
        description=(
            "Raster only: reject a non-COG TIFF instead of converting it. "
            "False (the default) converts the source to a COG during ingest. "
            "True fails the job when the source is not already a compliant "
            "COG, and cannot be combined with resampling, nodata_override, "
            "srid_override or a compression other than the default DEFLATE: "
            "each of those is applied by a conversion, so the commit is "
            "refused with a 422 naming the fields that clash."
        ),
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


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


# Discovery's refusal for a geom column that declares no SRID. A refresh that
# finds one fails its run with the same code.
UNDECLARED_SRID_CODE = "source_srid_undeclared"


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
    refusal_reason: str | None = Field(
        default=None,
        description=(
            "Why registration would refuse this table, as one of a fixed set "
            f"of GeoLens codes: {UNDECLARED_SRID_CODE}. Null when discovery finds "
            "none, though registration can still refuse a table for a reason "
            "discovery does not check."
        ),
    )


class DiscoverResponse(BaseModel):
    tables: list[DiscoveredTable] = Field(
        description="Tables in the `data` schema not yet registered as datasets. `refusal_reason` marks those discovery knows registration would refuse."
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
    kind: Literal["tiles3d", "pointcloud"] | None = Field(
        default=None, description=UPLOAD_KIND_DESCRIPTION
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
    remaining_dataset_quota: int | None = Field(
        default=None,
        description=(
            "Datasets the caller may still create before hitting the per-user "
            "count cap, or null when no count cap is configured (unlimited). "
            "Advisory UX hint only — the cap is enforced server-side at upload."
        ),
    )


class VrtCreateRequest(BaseModel):
    source_dataset_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=500,
        description="Source raster dataset IDs to include in the VRT mosaic or band stack (1-500).",
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


# Fan-out schemas (GPKG-03, Phase 1058-04)
class FanOutLayerRequest(BaseModel):
    """One layer to ingest as a separate dataset from a multi-layer source."""

    layer_name: str = Field(
        min_length=1,
        max_length=500,
        description="Name of the layer within the source file (e.g. GeoPackage layer name).",
    )
    title: str | None = Field(
        default=None,
        max_length=500,
        description="Optional human-readable title override. Defaults to '{filename}: {layer_name}'.",
    )


class FanOutCommitRequest(BaseModel):
    """Request body for POST /ingest/commit-fan-out/{job_id}.

    Converts one pending IngestJob (multi-layer file) into N independent
    ingest tasks — one per requested layer. Maximum 50 layers per request.
    """

    layers: list[FanOutLayerRequest] = Field(
        min_length=1,
        max_length=50,
        description="Layers to ingest as separate datasets. Maximum 50 per request.",
    )


class FanOutLayerResult(BaseModel):
    """Per-layer outcome from the fan-out commit operation."""

    layer_name: str = Field(description="Layer name from the request.")
    new_job_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the cloned IngestJob queued for this layer. Null on failure.",
    )
    dataset_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the new Dataset record created for this layer. Null on failure.",
    )
    status: Literal["queued", "failed"] = Field(
        description="'queued' if the task was dispatched; 'failed' if an error occurred."
    )
    error: str | None = Field(
        default=None,
        description="User-safe error description when status='failed'. Never contains internal file paths.",
    )


class FanOutCommitResponse(BaseModel):
    """Response from POST /ingest/commit-fan-out/{job_id}."""

    fan_out_id: uuid.UUID = Field(
        description="The original job_id (parent). Use for client-side correlation."
    )
    results: list[FanOutLayerResult] = Field(
        description="Per-layer outcomes in the same order as the request layers."
    )
