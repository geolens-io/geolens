import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.text import normalize_nfc as _nfc


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


class ColumnInfo(BaseModel):
    """Describes a single column in a dataset's attribute table."""

    name: str
    type: str
    semantic_role: str | None = None
    domain_type: str | None = None
    sample_values: list | None = None
    stats: dict | None = None


class QualityDetail(BaseModel):
    """Automated quality assessment results."""

    overall: float = Field(ge=0.0, le=100.0)
    metadata_completeness: float = Field(ge=0.0, le=100.0)
    geometry_validity: float | None = Field(default=None, ge=0.0, le=100.0)
    attribute_completeness: float = Field(ge=0.0, le=100.0)
    crs_defined: float | None = Field(default=None, ge=0.0, le=100.0)
    computed_at: datetime | None = None


class ColumnDefinition(BaseModel):
    name: str
    type: Literal["text", "integer", "float", "date", "boolean"]


class CreateEmptyDatasetRequest(BaseModel):
    title: str = Field(max_length=500)
    columns: list[ColumnDefinition]


Visibility = Literal["private", "restricted", "internal", "public"]


class DatasetCreate(BaseModel):
    title: str = Field(max_length=500)
    summary: str | None = Field(
        default=None, max_length=5000, description="Brief abstract of the dataset"
    )
    visibility: Visibility = Field(
        default="private",
        description="Access level: private, restricted, internal, or public",
    )

    @field_validator("title", "summary", mode="before")
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)


class RasterBandInfo(BaseModel):
    index: int = Field(description="1-based band index")
    dtype: str = Field(description="Pixel data type, e.g. uint8, float32")
    nodata: str | None = Field(
        default=None, description="Nodata sentinel value for this band"
    )
    color_interp: str | None = Field(
        default=None, description="Color interpretation, e.g. Red, Green, Gray"
    )


class RasterConnect(BaseModel):
    download_url: str | None = Field(
        default=None, description="Direct file download URL"
    )
    tile_url: str = Field(description="Titiler tile endpoint for this raster")
    s3_uri: str | None = Field(
        default=None, description="S3 object URI, e.g. s3://bucket/key.tif"
    )


class RasterMetadata(BaseModel):
    epsg: int | None = Field(default=None, description="EPSG code of the raster CRS")
    res_x: float | None = Field(
        default=None, description="Pixel resolution in X (CRS units)"
    )
    res_y: float | None = Field(
        default=None, description="Pixel resolution in Y (CRS units)"
    )
    band_count: int | None = None
    nodata: str | None = Field(default=None, description="Global nodata sentinel value")
    compression: str | None = Field(
        default=None, description="Internal compression, e.g. DEFLATE, LZW"
    )
    width: int | None = Field(default=None, description="Raster width in pixels")
    height: int | None = Field(default=None, description="Raster height in pixels")
    size_bytes: int | None = Field(
        default=None, description="File size on disk in bytes"
    )
    tile_url: str | None = Field(default=None, description="Titiler XYZ tile endpoint")
    bands: list[RasterBandInfo] = []
    connect: RasterConnect | None = None
    status: str | None = Field(
        default=None, description="Processing status, e.g. ready, failed"
    )
    vrt_type: str | None = Field(
        default=None, description="VRT variant: mosaic or timeseries"
    )
    source_count: int | None = Field(
        default=None, description="Number of source rasters in a VRT mosaic"
    )
    resolution_strategy: str | None = Field(
        default=None, description="VRT resolution strategy, e.g. highest, average"
    )


class StacAsset(BaseModel):
    href: str
    type: str | None = None
    title: str | None = None
    description: str | None = None
    roles: list[str] | None = None
    size_bytes: int | None = None


class CollectionRef(BaseModel):
    """Minimal reference to a collection a dataset belongs to."""

    id: uuid.UUID
    name: str


class DatasetResponse(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID = Field(description="Parent catalog record UUID")
    table_name: str = Field(description="Internal PostGIS table name")
    title: str
    summary: str | None
    srid: int | None = Field(
        default=None, description="Current EPSG SRID of stored geometry"
    )
    geometry_type: str | None = Field(
        default=None, description="OGC geometry type, e.g. MultiPolygon"
    )
    is_3d: bool | None = Field(
        default=None, description="True if geometry has Z dimension"
    )
    n_dims: int | None = Field(
        default=None, description="Number of coordinate dimensions (2, 3, or 4)"
    )
    z_min: float | None = Field(
        default=None, description="Minimum Z value across all features"
    )
    z_max: float | None = Field(
        default=None, description="Maximum Z value across all features"
    )
    feature_count: int | None
    extent_bbox: list[float] | None = Field(
        default=None, description="Bounding box [minx, miny, maxx, maxy]"
    )
    column_info: list[ColumnInfo] | None = Field(
        default=None, description="Column names, types, and stats"
    )
    license: str | None = None
    source_organization: str | None = None
    data_vintage_start: date | None = Field(
        default=None, description="Start of temporal coverage"
    )
    data_vintage_end: date | None = Field(
        default=None, description="End of temporal coverage"
    )
    quality_detail: QualityDetail | None = Field(
        default=None, description="Automated quality assessment results"
    )
    source_format: str | None = Field(
        default=None, description="Original file format, e.g. GPKG, SHP"
    )
    source_filename: str | None
    original_srid: int | None = Field(
        default=None, description="EPSG SRID of the uploaded source file"
    )
    current_version: int = Field(default=1, description="Monotonic version counter")
    source_url: str | None = Field(
        default=None,
        max_length=2000,
        description="URL the data was originally fetched from",
    )
    quality_statement: str | None = None
    visibility: str = Field(
        description="Access level: private, restricted, internal, public"
    )
    created_by: uuid.UUID | None
    created_by_display: str
    created_at: datetime
    updated_at: datetime
    last_edited_by_display: str | None = None
    last_edited_at: datetime | None = None
    collections: list["CollectionRef"] | None = None
    # ISO governance fields
    record_status: str = Field(
        default="draft", description="Lifecycle status: draft, ready, published"
    )
    lineage_summary: str | None = Field(
        default=None, description="Free-text provenance / lineage statement"
    )
    update_frequency: str | None = Field(
        default=None, description="ISO maintenance frequency code"
    )
    usage_constraints: str | None = None
    access_constraints: str | None = None
    sensitivity_classification: str | None = Field(
        default=None, description="e.g. public, confidential, restricted"
    )
    theme_category: list[str] | None = Field(
        default=None, description="ISO topic category codes"
    )
    owner_org: str | None = Field(default=None, description="Owning organization name")
    published_at: datetime | None = None
    updated_by: uuid.UUID | None = None
    record_type: str = Field(
        default="vector_dataset",
        description=(
            "Record type: 'vector_dataset' (spatial features), "
            "'raster_dataset' (single COG), 'vrt_dataset' (VRT mosaic), "
            "'table' (non-spatial tabular), 'map' (saved map), "
            "'service' (catalogued remote service), 'collection' (flat dataset group)."
        ),
    )
    raster: RasterMetadata | None = Field(
        default=None, description="Raster-specific metadata (null for vectors)"
    )
    stac_assets: dict[str, StacAsset] | None = Field(
        default=None, description="STAC-style asset dictionary"
    )
    stac_extensions: list[str] | None = None
    language: str | None = Field(
        default=None, description="ISO 639-1 language code, e.g. en, fr"
    )

    model_config = ConfigDict(from_attributes=True)


class StatusUpdateResponse(BaseModel):
    id: str
    record_status: str


class StatusUpdate(BaseModel):
    status: str = Field(max_length=20)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        status = v.strip()
        if not status:
            raise ValueError("status must not be blank")
        return status


class DatasetDeleteRequest(BaseModel):
    confirm_title: str = Field(
        max_length=500, description="Must match the dataset title to confirm deletion"
    )


class BulkDeleteItem(BaseModel):
    dataset_id: uuid.UUID
    confirm_title: str = Field(max_length=500)


class BulkDeleteRequest(BaseModel):
    datasets: list[BulkDeleteItem] = Field(
        ..., min_length=1, max_length=100, description="1-100 datasets to delete"
    )


class BulkDeleteResultItem(BaseModel):
    dataset_id: uuid.UUID
    status: str  # "deleted" | "error"
    detail: str | None = None


class BulkDeleteResponse(BaseModel):
    deleted: int
    errors: int
    results: list[BulkDeleteResultItem]


class DatasetMeta(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=5000)
    visibility: Visibility | None = Field(
        default=None,
        description="Access level: private, restricted, internal, or public",
    )
    license: str | None = Field(default=None, max_length=1000)
    source_organization: str | None = Field(default=None, max_length=1000)
    data_vintage_start: date | None = Field(
        default=None, description="Start of temporal coverage"
    )
    data_vintage_end: date | None = Field(
        default=None, description="End of temporal coverage"
    )
    # ISO governance fields
    lineage_summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Free-text provenance / lineage statement",
    )
    update_frequency: str | None = Field(
        default=None, max_length=30, description="ISO maintenance frequency code"
    )
    usage_constraints: str | None = Field(default=None, max_length=1000)
    access_constraints: str | None = Field(default=None, max_length=1000)
    sensitivity_classification: str | None = Field(
        default=None,
        max_length=20,
        description="e.g. public, confidential, restricted",
    )
    theme_category: list[str] | None = Field(
        default=None, description="ISO topic category codes"
    )
    record_status: str | None = Field(
        default=None,
        max_length=20,
        description="Lifecycle status: draft, ready, published",
    )
    owner_org: str | None = Field(
        default=None, max_length=1000, description="Owning organization name"
    )
    quality_statement: str | None = Field(default=None, max_length=5000)
    source_url: str | None = Field(
        default=None,
        max_length=2000,
        description="URL the data was originally fetched from",
    )
    language: str | None = Field(
        default=None,
        max_length=10,
        description="ISO 639-1 language code, e.g. en, fr",
    )
    is_dem: bool | None = Field(
        default=None,
        description="Flag raster as a Digital Elevation Model for terrain rendering",
    )

    @field_validator(
        "title",
        "summary",
        "lineage_summary",
        "quality_statement",
        "source_organization",
        mode="before",
    )
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)


class DatasetListResponse(BaseModel):
    datasets: list[DatasetResponse]
    total: int


class ColumnChange(BaseModel):
    name: str
    type: str


class TypeChange(BaseModel):
    name: str
    old_type: str
    new_type: str


class SchemaDiff(BaseModel):
    columns_added: list[ColumnChange] = Field(
        description="Columns present in new but not old schema"
    )
    columns_removed: list[ColumnChange] = Field(
        description="Columns present in old but not new schema"
    )
    type_changes: list[TypeChange] = Field(
        description="Columns whose data type changed"
    )
    row_count_old: int | None
    row_count_new: int | None
    row_count_delta: int = Field(description="row_count_new minus row_count_old")


class ReuploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str = "pending"
    message: str


class ReuploadPreviewResponse(BaseModel):
    job_id: uuid.UUID
    source_filename: str | None
    columns: list[ColumnChange]
    crs: int | None
    geometry_type: str | None
    feature_count: int | None
    sample_rows: list[dict[str, Any]]
    layer_name: str
    schema_diff: SchemaDiff


class ReuploadServicePreviewRequest(BaseModel):
    url: str = Field(max_length=2048)
    service_type: str = Field(max_length=50)
    layer_name: str = Field(max_length=500)
    layer_title: str | None = Field(default=None, max_length=500)
    layer_id: int | str | None = None
    token: str | None = Field(default=None, max_length=1000)
    object_id_field: str | None = Field(default=None, max_length=200)


class ReuploadCommitRequest(BaseModel):
    srid_override: int | None = Field(default=None, ge=1, le=998999)
    token: str | None = Field(default=None, max_length=1000)


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
    columns: list[ColumnChange]
    rows: list[dict[str, Any]]
    approximate_total: int = Field(
        description="Estimated total row count (may use pg stats)"
    )
    next_cursor: int | None = Field(
        default=None, description="Cursor value for the next page, null if last"
    )


class ColumnValuesResponse(BaseModel):
    values: list[str | int | float | None]
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
    semantic_role: str | None = Field(
        default=None, description="Inferred role: geometry, identifier, measure, etc."
    )
    example_values: list | None = Field(
        default=None, description="Sample values from the column"
    )
    ordinal_position: int | None = Field(
        default=None, description="Column position in the table (1-based)"
    )
    is_nullable: bool | None = None
    is_current: bool = Field(
        description="False if column was removed in a later version"
    )
    user_modified_fields: list[str] = Field(
        description="Field names manually edited by a user"
    )

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
    title: str | None = Field(
        default=None, max_length=500, description="Human-friendly column display name"
    )
    description: str | None = Field(default=None, max_length=2000)
    units: str | None = Field(
        default=None, max_length=50, description="Measurement units, e.g. meters, kg"
    )
    semantic_role: SEMANTIC_ROLES | None = Field(
        default=None, description="Column role: geometry, identifier, measure, etc."
    )
    domain_type: DOMAIN_TYPES | None = Field(
        default=None, description="Value domain: continuous, categorical, coded, etc."
    )


class RelatedDatasetItem(BaseModel):
    id: str
    name: str
    geometry_type: str | None
    similarity: float = Field(description="Cosine similarity score (0-1)")
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
    target_dataset_id: uuid.UUID = Field(description="UUID of the dataset to link to")
    source_column: str = Field(
        max_length=63, description="Join column in the source dataset"
    )
    target_column: str = Field(
        default="gid", max_length=63, description="Join column in the target dataset"
    )
    label: str | None = Field(
        default=None,
        max_length=500,
        description="Optional display label for this relationship",
    )


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


class IngestionResult(BaseModel):
    """Parameter object for ``create_dataset`` ingestion-side fields.

    Bundles the 14 fields that describe the result of running an ingestion
    (ogr2ogr / raster / VRT / layer-creation) so call sites pass one named
    argument instead of 14 keywords. All fields are optional — non-spatial
    tables omit the spatial fields, and ad-hoc creations (empty layers)
    provide minimal info.

    Constructed from the metadata dict produced by the ingestion pipeline:
    ``IngestionResult.model_validate({**metadata, "sample_values": sample_vals})``.
    """

    srid: int | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    extent_wkt: str | None = None
    column_info: list[dict] | None = None
    sample_values: dict | None = None
    source_format: str | None = None
    source_filename: str | None = None
    original_srid: int | None = None
    source_url: str | None = None
    is_3d: bool | None = None
    n_dims: int | None = None
    z_min: float | None = None
    z_max: float | None = None

    model_config = ConfigDict(frozen=True, extra="ignore")
