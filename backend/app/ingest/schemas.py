"""Pydantic request/response models for ingestion endpoints."""

import uuid
from typing import Literal

from pydantic import BaseModel


class UploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "pending"
    message: str


class PreviewResponse(BaseModel):
    job_id: uuid.UUID
    source_filename: str | None
    columns: list[dict]
    crs: int | None
    geometry_type: str | None
    feature_count: int | None
    sample_rows: list[dict]
    layer_name: str


class RasterPreviewResponse(BaseModel):
    job_id: uuid.UUID
    source_filename: str | None
    crs_epsg: int | None
    crs_wkt: str | None
    band_count: int
    width: int
    height: int
    dtype: str
    nodata: float | str | None
    res_x: float
    res_y: float
    compression: str | None
    file_size_bytes: int | None
    is_cog_compliant: bool
    compliance_reason: str
    temporal_start: str | None = None


class CommitRequest(BaseModel):
    title: str
    summary: str | None = None
    visibility: str = "private"
    srid_override: int | None = None
    token: str | None = None
    temporal_start: str | None = None
    temporal_end: str | None = None
    compression: str | None = None
    resampling: str | None = None
    nodata_override: float | str | None = None


class CommitResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    message: str


class RegisterRequest(BaseModel):
    table_name: str
    title: str
    summary: str | None = None
    visibility: str = "private"


class TableRegisterResponse(BaseModel):
    dataset_id: uuid.UUID
    title: str
    table_name: str


class DiscoveredTable(BaseModel):
    table_name: str
    geometry_type: str | None
    srid: int | None
    estimated_rows: int | None


class DiscoverResponse(BaseModel):
    tables: list[DiscoveredTable]


class BulkRegisterItem(BaseModel):
    table_name: str
    title: str
    summary: str | None = None
    visibility: str = "private"


class BulkRegisterRequest(BaseModel):
    tables: list[BulkRegisterItem]


class BulkRegisterResult(BaseModel):
    table_name: str
    status: str
    dataset_id: uuid.UUID | None = None
    title: str | None = None
    error: str | None = None


class BulkRegisterResponse(BaseModel):
    results: list[BulkRegisterResult]


# ---------------------------------------------------------------------------
# Presigned S3 upload schemas
# ---------------------------------------------------------------------------


class PresignedUploadRequest(BaseModel):
    filename: str
    file_size: int  # bytes
    content_type: str = "application/octet-stream"


class PresignedPartInfo(BaseModel):
    etag: str
    part_number: int


class PresignedCompleteRequest(BaseModel):
    parts: list[PresignedPartInfo] = []


class PresignedUploadResponse(BaseModel):
    job_id: uuid.UUID
    urls: list[str]
    s3_key: str
    upload_id: str | None = None
    part_size: int | None = None


class UploadConfigResponse(BaseModel):
    presigned_uploads: bool
    presigned_threshold_bytes: int
    max_file_size_bytes: int


# ---------------------------------------------------------------------------
# VRT creation schemas
# ---------------------------------------------------------------------------


class VrtCreateRequest(BaseModel):
    source_dataset_ids: list[uuid.UUID]
    vrt_type: Literal["mosaic", "band_stack"]
    resolution_strategy: Literal["finest", "coarsest", "average"]
    title: str
    summary: str | None = None
    visibility: str = "private"


class VrtCreateResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "accepted"
    message: str


class VrtAddSourceRequest(BaseModel):
    source_dataset_id: uuid.UUID


class VrtMutationResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "accepted"
    message: str
