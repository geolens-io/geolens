import unicodedata
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SEMANTIC_ROLES = Literal[
    "geometry",
    "identifier",
    "measure",
    "temporal",
    "categorical",
    "category",
    "label",
    "foreign_key",
    "other",
]
DOMAIN_TYPES = Literal[
    "continuous",
    "discrete",
    "categorical",
    "coded",
    "codedValue",
    "boolean",
    "text",
    "date",
    "temporal",
    "geometry",
    "range",
]


class ColumnDefinition(BaseModel):
    name: str
    type: Literal["text", "integer", "float", "date", "boolean"]


class CreateEmptyDatasetRequest(BaseModel):
    title: str
    columns: list[ColumnDefinition]


Visibility = Literal["private", "restricted", "internal", "public"]


def _nfc(v: str | None) -> str | None:
    """Normalize a string to Unicode NFC form."""
    if v is None:
        return v
    return unicodedata.normalize("NFC", v)


class DatasetCreate(BaseModel):
    title: str
    summary: str | None = None
    visibility: Visibility = "private"

    @field_validator("title", "summary", mode="before")
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)


class RasterBandInfo(BaseModel):
    index: int
    dtype: str
    nodata: str | None = None
    color_interp: str | None = None


class RasterConnect(BaseModel):
    download_url: str | None = None
    tile_url: str
    s3_uri: str | None = None


class RasterMetadata(BaseModel):
    epsg: int | None = None
    res_x: float | None = None
    res_y: float | None = None
    band_count: int | None = None
    nodata: str | None = None
    compression: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    quicklook_url: str | None = None
    tile_url: str | None = None
    bands: list[RasterBandInfo] = []
    connect: RasterConnect | None = None
    status: str | None = None
    vrt_type: str | None = None
    source_count: int | None = None
    resolution_strategy: str | None = None


class StacAsset(BaseModel):
    href: str
    type: str | None = None
    title: str | None = None
    description: str | None = None
    roles: list[str] | None = None
    size_bytes: int | None = None


class DatasetResponse(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    table_name: str
    title: str
    summary: str | None
    srid: int | None
    geometry_type: str | None
    feature_count: int | None
    extent_bbox: list[float] | None = None
    column_info: list[dict] | None
    license: str | None = None
    source_organization: str | None = None
    data_vintage_start: date | None = None
    data_vintage_end: date | None = None
    quality_detail: dict | None = None
    source_format: str | None
    source_filename: str | None
    original_srid: int | None
    current_version: int = 1
    source_url: str | None = None
    quality_statement: str | None = None
    visibility: str
    created_by: uuid.UUID | None
    created_by_display: str
    created_at: datetime
    updated_at: datetime
    last_edited_by_display: str | None = None
    last_edited_at: datetime | None = None
    collections: list[dict] | None = None
    # ISO governance fields
    record_status: str | None = None
    lineage_summary: str | None = None
    update_frequency: str | None = None
    usage_constraints: str | None = None
    access_constraints: str | None = None
    sensitivity_classification: str | None = None
    theme_category: list[str] | None = None
    owner_org: str | None = None
    published_at: datetime | None = None
    updated_by: uuid.UUID | None = None
    record_type: str = "vector_dataset"
    raster: RasterMetadata | None = None
    stac_assets: dict[str, StacAsset] | None = None
    stac_extensions: list[str] | None = None
    language: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StatusUpdateResponse(BaseModel):
    id: str
    record_status: str


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"draft", "ready", "internal", "published"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class DatasetDeleteRequest(BaseModel):
    confirm_title: str


class BulkDeleteItem(BaseModel):
    dataset_id: uuid.UUID
    confirm_title: str


class BulkDeleteRequest(BaseModel):
    datasets: list[BulkDeleteItem] = Field(..., min_length=1, max_length=100)


class BulkDeleteResultItem(BaseModel):
    dataset_id: uuid.UUID
    status: str  # "deleted" | "error"
    detail: str | None = None


class BulkDeleteResponse(BaseModel):
    deleted: int
    errors: int
    results: list[BulkDeleteResultItem]


class DatasetMeta(BaseModel):
    title: str | None = None
    summary: str | None = None
    visibility: Visibility | None = None
    license: str | None = None
    source_organization: str | None = None
    data_vintage_start: date | None = None
    data_vintage_end: date | None = None
    # ISO governance fields
    lineage_summary: str | None = None
    update_frequency: str | None = None
    usage_constraints: str | None = None
    access_constraints: str | None = None
    sensitivity_classification: str | None = None
    theme_category: list[str] | None = None
    record_status: str | None = None
    owner_org: str | None = None
    quality_statement: str | None = None
    source_url: str | None = None
    language: str | None = None

    @field_validator(
        "title", "summary", "lineage_summary", "quality_statement", "source_organization",
        mode="before",
    )
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)


class DatasetListResponse(BaseModel):
    datasets: list[DatasetResponse]
    total: int


class SchemaDiff(BaseModel):
    columns_added: list[dict]
    columns_removed: list[dict]
    type_changes: list[dict]
    row_count_old: int | None
    row_count_new: int | None
    row_count_delta: int


class ReuploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "pending"
    message: str


class ReuploadPreviewResponse(BaseModel):
    job_id: uuid.UUID
    source_filename: str | None
    columns: list[dict]
    crs: int | None
    geometry_type: str | None
    feature_count: int | None
    sample_rows: list[dict]
    layer_name: str
    schema_diff: SchemaDiff


class ReuploadServicePreviewRequest(BaseModel):
    url: str
    service_type: str
    layer_name: str
    layer_title: str | None = None
    layer_id: int | str | None = None
    token: str | None = None
    object_id_field: str | None = None


class ReuploadCommitRequest(BaseModel):
    srid_override: int | None = None
    token: str | None = None


class ReuploadCommitResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    message: str


class DatasetVersionResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_number: int
    source_filename: str | None
    source_format: str | None
    feature_count: int | None
    srid: int | None
    geometry_type: str | None
    file_hash: str | None
    uploaded_by: uuid.UUID | None
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetVersionListResponse(BaseModel):
    versions: list[DatasetVersionResponse]
    total: int


class DatasetRowsResponse(BaseModel):
    columns: list[dict]
    rows: list[dict]
    approximate_total: int
    next_cursor: int | None = None


class ColumnValuesResponse(BaseModel):
    values: list
    count: int


class ColumnStatsResponse(BaseModel):
    min: float | None = None
    max: float | None = None
    count: int = 0
    mean: float | None = None
    quantiles: list[float] = []


class AttributeMetadataResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    field_name: str
    title: str | None
    description: str | None
    data_type: str | None
    units: str | None
    domain_type: str | None
    semantic_role: str | None
    example_values: list | None
    ordinal_position: int | None
    is_nullable: bool | None
    is_current: bool
    user_modified_fields: list[str]

    model_config = ConfigDict(from_attributes=True)


class VrtSourceItem(BaseModel):
    dataset_id: uuid.UUID
    title: str
    position: int
    band_count: int | None = None
    resolution_x: float | None = None
    resolution_y: float | None = None
    crs_epsg: int | None = None
    extent_bbox: list[float] | None = None


class VrtSourceListResponse(BaseModel):
    sources: list[VrtSourceItem]


class VrtSourceHealth(BaseModel):
    dataset_id: uuid.UUID
    title: str
    status: Literal["healthy", "missing", "inaccessible"]


class VrtActiveGeneration(BaseModel):
    generation_id: uuid.UUID
    started_at: datetime
    elapsed_seconds: float


class VrtStatusResponse(BaseModel):
    status: Literal["ready", "regenerating", "failed"]
    last_generation_at: datetime | None = None
    source_count: int
    active_generation: VrtActiveGeneration | None = None
    source_health: list[VrtSourceHealth]


class VrtGenerationItem(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    source_count: int | None = None
    triggered_by: str | None = None


class VrtGenerationListResponse(BaseModel):
    generations: list[VrtGenerationItem]
    total: int


class AttributeMetadataUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    units: str | None = None
    semantic_role: SEMANTIC_ROLES | None = None
    domain_type: DOMAIN_TYPES | None = None


class RelatedDatasetItem(BaseModel):
    id: str
    name: str
    geometry_type: str | None
    similarity: float
    record_type: str | None = None
    feature_count: int | None = None
    band_count: int | None = None


class RelatedDatasetsResponse(BaseModel):
    items: list[RelatedDatasetItem]
    total: int


class AttributeMetadataListResponse(BaseModel):
    attributes: list[AttributeMetadataResponse]
    total: int


class DatasetRelationshipCreate(BaseModel):
    target_dataset_id: uuid.UUID
    source_column: str
    target_column: str = "gid"
    label: str | None = None


class DatasetRelationshipResponse(BaseModel):
    id: uuid.UUID
    source_dataset_id: uuid.UUID
    target_dataset_id: uuid.UUID
    source_column: str
    target_column: str
    relationship_type: str
    label: str | None
    target_dataset_title: str | None = None

    model_config = ConfigDict(from_attributes=True)
