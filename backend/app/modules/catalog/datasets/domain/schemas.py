import math
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.core.url_redaction import has_url_credentials
from app.core.text import normalize_nfc as _nfc
from app.core.text import reject_html_markup as _reject_markup
from app.modules.catalog.sources.origin_probe import DETAIL_CODES
from app.modules.catalog.sources.schemas import (
    DEPRECATED_TOKEN_SUFFIX,
    SERVICE_AUTH_FIELD_DESCRIPTION,
    ServiceAuthRequest,
    reject_service_auth_conflict,
)
from app.platform.analysis_sql import MAX_SPATIAL_JOIN_FIELDS
from app.platform.dataset_origin import OriginKind


# feat(#1222): built from the probe's own closed vocabulary rather than
# retyped, so the two cannot drift. The wording matters as much as the list:
# this field is served on every dataset read, so a client author has to be
# told it is an enumerated code and not a message to show verbatim, or the
# next person to touch the probe will "improve" it into a sentence carrying
# provider text.
SOURCE_HEALTH_DETAIL_DESCRIPTION = (
    "Why the origin is not healthy, as one of a fixed set of GeoLens codes: "
    + ", ".join(sorted(DETAIL_CODES))
    + ". Null when healthy or never probed. Never provider text, a URL, or a "
    "response body — nothing the origin sent is stored here."
)

_COLUMN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _normalize_language_tag(value: str) -> str:
    tag = value.strip().replace("_", "-")
    if not _LANGUAGE_TAG_RE.fullmatch(tag):
        raise ValueError("language must be a BCP 47 tag such as en, fr, or pt-BR")
    parts = tag.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            canonical.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            canonical.append(part.upper())
        else:
            canonical.append(part.lower())
    return "-".join(canonical)


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


def _validate_http_url_without_credentials(v: str) -> str:
    HttpUrl(v)
    if has_url_credentials(v):
        raise ValueError(
            "url must not include credential query parameters; use the token field instead"
        )
    return v


def _validate_safe_service_token(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.isprintable():
        raise ValueError("token contains control characters")
    if any(c.isspace() for c in v):
        raise ValueError("token contains whitespace")
    return v


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
    crs_is_geographic: bool | None = Field(
        default=None,
        description=(
            "True when the raster CRS is geographic (res_x/res_y are degrees, "
            "not meters); None when the CRS class is unknown."
        ),
    )
    res_x: float | None = Field(
        default=None, description="Pixel resolution in X (CRS units)"
    )
    res_y: float | None = Field(
        default=None, description="Pixel resolution in Y (CRS units)"
    )
    band_count: int | None = None
    is_dem: bool | None = Field(
        default=None,
        description="True if this raster is a DEM (single-band float) usable for 3D terrain/hillshade",
    )
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


class DerivedFromResponse(BaseModel):
    """Provenance for an analysis output: what it came from, and how.

    fix(#765 review): declared as a model rather than ``dict[str, Any]``. The
    dict spelled itself into the checked-in OpenAPI as bare
    ``additionalProperties: true``, so both generated SDKs lost the shape — the
    TypeScript one degraded to an index signature and the Python one to an
    empty additional-properties container. The stable shape was documented in
    prose and mirrored by hand in the frontend types while the SDKs, which is
    where most consumers actually meet it, could not use it type-safely.

    ``params`` stays untyped on purpose: it is the operation's own parameter
    dict, so its keys differ per operation (``distance_meters`` for a buffer,
    ``mask_source``/``mask_dataset_id`` for a clip), and it is additionally
    REDACTED per requester — ``visible_derived_from`` drops any embedded
    dataset id the caller cannot see. A union of per-operation models would
    describe a shape the redaction is free to punch holes in.
    """

    dataset_id: uuid.UUID = Field(description="The dataset this one was derived from")
    operation: str = Field(description="Analysis operation that produced it")
    params: dict[str, Any] = Field(
        description=(
            "Operation parameters, minus any dataset reference the requester "
            "cannot access"
        )
    )
    created_at: datetime


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
    has_generic_geometry: bool = Field(
        default=False,
        description=(
            "True when the underlying column is generic GEOMETRY (created "
            "sketch datasets): the dataset accepts ANY geometry subtype on "
            "write regardless of the display geometry_type above. Computed "
            "on the detail endpoint only (fix #430 codex r18); list "
            "endpoints always report false."
        ),
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
        default=None,
        description=(
            "Bounding box [west, south, east, north] per RFC 7946 §5.2. "
            "west > east on an antimeridian-crossing extent."
        ),
    )
    column_info: list[ColumnInfo] | None = Field(
        default=None, description="Column names, types, and stats"
    )
    license: str | None = None
    attribution: str | None = Field(
        default=None,
        description=(
            "Credit line the source's terms require to be displayed wherever "
            "the data is rendered. Shown verbatim in the map viewer's "
            "attribution control."
        ),
    )
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
    tile_columns: list[str] | None = Field(
        default=None,
        description=(
            "Ordered vector-tile property allowlist; null uses zoom defaults, "
            "[] emits geometry-only tiles, list emits those properties at any zoom."
        ),
    )
    original_srid: int | None = Field(
        default=None, description="EPSG SRID of the uploaded source file"
    )
    current_version: int = Field(default=1, description="Monotonic version counter")
    source_url: str | None = Field(
        default=None,
        max_length=2000,
        description="URL the data was originally fetched from",
    )
    # feat(#1218): read-only source-origin & refresh state. Every field below
    # is system-managed — none is accepted by PATCH /datasets/{id}/metadata.
    origin: str | None = Field(
        default=None,
        description=(
            "How the data entered the catalog: upload, postgis, service, "
            "stac, or created. Computed from source_format and record_type, "
            "not stored; null for collections and VRTs, which have no origin "
            "of their own."
        ),
    )
    origin_uri: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Machine-readable pointer back to the origin, written only by "
            "ingest and refresh. Distinct from source_url, which is editable "
            "descriptive metadata. Null for uploads and created datasets. "
            "feat(#1316): also null for any reader who is neither the "
            "dataset's owner nor an admin — origin (above) and the "
            "freshness/health fields below are not gated and still describe "
            "the dataset's capabilities."
        ),
    )
    origin_ref: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Typed per-origin payload with a `kind` discriminator, e.g. "
            '{"kind": "service", "service_type": "wfs", "url": "...", '
            '"layer_id": "0"}. Never contains credentials. feat(#1316): '
            "owner-or-admin only, same redaction as origin_uri."
        ),
    )
    last_refreshed_at: datetime | None = Field(
        default=None,
        description="Last committed successful refresh — not the last attempt",
    )
    last_checked_at: datetime | None = Field(
        default=None,
        description=(
            "Last time GeoLens contacted the origin at all, whether the "
            "attempt succeeded or failed"
        ),
    )
    source_health: str = Field(
        default="unknown",
        description=(
            "healthy, missing, inaccessible, or unknown. 'unknown' means "
            "never probed, or an origin kind with nothing to probe."
        ),
    )
    source_health_detail: str | None = Field(
        default=None, description=SOURCE_HEALTH_DETAIL_DESCRIPTION
    )
    schema_drift_status: str = Field(
        default="unknown",
        description=(
            "none, drifted, or unknown. Set at refresh commit from the "
            "schema diff; 'unknown' until a refresh has run."
        ),
    )
    # feat(#1224): computed at read time from last_refreshed_at, the record's
    # update_frequency, and origin. Not stored — see domain/source_freshness.py.
    source_freshness: str = Field(
        default="unknown",
        description=(
            "fresh, due, overdue, or unknown, computed from last_refreshed_at "
            "against the declared update_frequency: due past one declared "
            "period, overdue past two. 'unknown' when the origin cannot be "
            "refreshed at all (created), when no cadence is declared "
            "(asNeeded, irregular, notPlanned, unknown), or when nothing has "
            "been refreshed yet. Advisory only; never blocks an operation. "
            "Distinct from the quality score's own freshness, which measures "
            "quality_detail.computed_at rather than the source."
        ),
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
        default="draft",
        description=(
            "Lifecycle status. Deliberately not pinned to an enum: the values "
            "come from the workflow extension's status_order(), so an overlay "
            "may define its own. Community default order: draft, ready, "
            "internal, published."
        ),
    )
    lineage_summary: str | None = Field(
        default=None, description="Free-text provenance / lineage statement"
    )
    derived_from: DerivedFromResponse | None = Field(
        default=None,
        description=(
            "Provenance for an analysis output. Null for a dataset that was not "
            "derived, and also for a requester who cannot access the source "
            "dataset — the two are deliberately indistinguishable."
        ),
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
    metadata_warnings: list[str] | None = Field(
        default=None,
        description=(
            "Advisory warnings produced by a metadata update — e.g. a "
            "visibility or status change exposing keywords inherited from an "
            "analysis source the new audience cannot open (feat #1070). Only "
            "ever set on the PATCH response; the change has already applied."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class StatusUpdateResponse(BaseModel):
    id: str
    record_status: str
    metadata_warnings: list[str] | None = Field(
        default=None,
        description=(
            "Advisory warnings from the status change — the same "
            "inherited-keyword disclosure check the metadata PATCH runs "
            "(feat #1070, fix #1178 review). The transition has already "
            "applied."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "0190f4c8-8c6a-7a21-9a34-13bc2f31dc02",
                    "record_status": "published",
                }
            ]
        }
    )


class StatusUpdate(BaseModel):
    status: str = Field(max_length=20)

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "published"}]})

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
    """Partial-update payload for dataset metadata.

    The class name remains ``DatasetMeta`` for generated-SDK compatibility;
    new backend call sites use the ``DatasetMetaUpdate`` alias below.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "Updated flood zones",
                    "summary": "Revised from the 2026 authoritative release.",
                    "visibility": "public",
                }
            ]
        },
    )

    title: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=5000)
    visibility: Visibility | None = Field(
        default=None,
        description="Access level: private, restricted, internal, or public",
    )
    license: str | None = Field(default=None, max_length=1000)
    # feat(#1472): 5000, not the 1000 its neighbours use, because
    # ManifestMetadata.attribution is NonEmptyString5000 and the ingest tail
    # writes it straight to the column. A 1000-char bound here would accept a
    # manifest value the dataset PATCH then refuses to round-trip.
    attribution: str | None = Field(
        default=None,
        max_length=5000,
        description=(
            "Credit line displayed with the data. Null clears it; the ingest "
            "tail seeds it from a manifest's metadata.attribution."
        ),
    )
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
        description=(
            "Lifecycle status. Deliberately not pinned to an enum: the values "
            "come from the workflow extension's status_order(), so an overlay "
            "may define its own. Community default order: draft, ready, "
            "internal, published."
        ),
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
        max_length=35,
        description="BCP 47 primary language tag, e.g. en, fr, or pt-BR",
    )
    is_dem: bool | None = Field(
        default=None,
        description="Flag raster as a Digital Elevation Model for terrain rendering",
    )
    tile_columns: list[str] | None = Field(
        default=None,
        max_length=100,
        description=(
            "Ordered vector-tile property allowlist; null restores zoom defaults, "
            "[] emits geometry-only tiles, list emits those properties at any zoom."
        ),
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        return _normalize_language_tag(value) if value is not None else None

    @field_validator("tile_columns")
    @classmethod
    def validate_tile_columns(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(set(v)) != len(v):
            raise ValueError("tile_columns entries must be unique")
        invalid = [name for name in v if not _COLUMN_NAME_RE.match(name)]
        if invalid:
            raise ValueError(f"Invalid tile column names: {invalid}")
        return v

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_http_url_without_credentials(v)

    @field_validator(
        "title",
        "summary",
        "lineage_summary",
        "quality_statement",
        "source_organization",
        "attribution",
        mode="before",
    )
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)

    # fix(#1472 review): attribution is the one field here that reaches an
    # HTML render context (MapLibre's attribution control assigns it to
    # innerHTML), so it is the one that must stay markup-free. See
    # reject_html_markup for why MapLibre's own sanitizer is not a defense.
    @field_validator("attribution")
    @classmethod
    def attribution_is_not_markup(cls, v: str | None) -> str | None:
        return _reject_markup(v)


# Prefer the semantically precise name in new Python call sites while retaining
# the public ``DatasetMeta`` component and generated-SDK class for compatibility.
DatasetMetaUpdate = DatasetMeta


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
    # GPKG-01 Phase 1058: multi-layer support fields
    all_layers: list[dict[str, Any]] | None = None
    previous_source_layer: str | None = None


class ReuploadServicePreviewRequest(BaseModel):
    url: str = Field(max_length=2048)
    _validate_url = field_validator("url")(_validate_http_url_without_credentials)
    service_type: str = Field(max_length=50)
    layer_name: str = Field(max_length=500)
    layer_title: str | None = Field(default=None, max_length=500)
    layer_id: int | str | None = None
    token: str | None = Field(
        default=None, max_length=1000, description=DEPRECATED_TOKEN_SUFFIX.strip()
    )
    _validate_token = field_validator("token")(_validate_safe_service_token)
    object_id_field: str | None = Field(default=None, max_length=200)
    # feat(#1746): the fifth model to carry the structured credential. #1760
    # left it out because nothing composed a header for the methods it adds;
    # with the transport in place, leaving it out would mean a basic-protected
    # service could be re-uploaded but not previewed first.
    #
    # LAST, like every other model that gained this field. The generated Python
    # SDK gives each model field a positional slot in declaration order, so
    # inserting `auth` ahead of `object_id_field` would move that slot and an
    # existing positional caller would send its OID string as `auth` and
    # collect a 422. Appending cannot move a slot that already exists. Pinned
    # by test_service_auth_contract_1746.
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


class ReuploadPreviewRequest(BaseModel):
    # GPKG-01 Phase 1058: optional layer_name for multi-layer file sources
    layer_name: str | None = Field(default=None, max_length=500)


class ReuploadCommitRequest(BaseModel):
    srid_override: int | None = Field(default=None, ge=1, le=998999)
    expected_origin_kind: OriginKind | None = Field(
        default=None,
        description=(
            "The dataset origin the client saw when it staged this "
            "replacement. When set, the commit is refused with 409 "
            "`origin_changed` if the dataset's origin no longer matches, so a "
            "service, STAC or registered-table binding established after the "
            "upload is not silently rebound to an upload. Optional: a client "
            "that omits it keeps the pre-#1768 behaviour."
        ),
    )
    token: str | None = Field(
        default=None, max_length=1000, description=DEPRECATED_TOKEN_SUFFIX.strip()
    )
    # GPKG-01 Phase 1058: user-chosen layer for multi-layer GPKG files
    layer_name: str | None = Field(default=None, max_length=500)
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


class ReuploadCommitResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    message: str


class DatasetRefreshRequest(BaseModel):
    """Body of a one-request refresh (#1220). Carries no source pointer.

    Everything about WHERE the data comes from is read server-side from the
    dataset's stored origin binding — that is the whole feature. A client
    cannot re-point a dataset through this door, and a client that has been
    shown the wrong URL cannot refresh from it.
    """

    token: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "Transient credential for a protected service. Used for this "
            "refresh only and never persisted: it is handed to the worker "
            "through a single-use, short-lived reference and is gone once "
            "claimed. A retry needs a new token." + DEPRECATED_TOKEN_SUFFIX
        ),
    )
    _validate_token = field_validator("token")(_validate_safe_service_token)
    auth: ServiceAuthRequest | None = Field(
        default=None, description=SERVICE_AUTH_FIELD_DESCRIPTION
    )
    _reject_auth_conflict = model_validator(mode="after")(reject_service_auth_conflict)


class DatasetRefreshResponse(BaseModel):
    """Accepted dispatch of a refresh run.

    Returns the run id as well as the job id: the run is the durable history
    row (``GET /datasets/{id}/refresh-runs``) and outlives the job, which the
    retention purge eventually removes.
    """

    run_id: uuid.UUID
    job_id: uuid.UUID
    dataset_id: uuid.UUID
    origin_kind: str = Field(description="The origin this refresh re-pulled from")
    trigger: str = Field(description="api for this endpoint; cli for the CLI door")
    status: str = "pending"
    message: str


class DatasetVersionResponse(BaseModel):
    """One version in a dataset's history.

    feat(#1316): ``file_hash`` and ``uploaded_by`` are null for any caller who
    is neither the dataset's owner nor an admin — the same predicate that
    gates ``origin_uri``/``origin_ref`` on the dataset itself and
    ``triggered_by`` on refresh-runs (ADR-002 Decision 4e). Unredacted, a
    public dataset's version history enumerates its editors.
    """

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
    stddev: float | None = None
    data_type: str | None = Field(
        default=None,
        description="'categorical' for non-numeric columns; null for numeric.",
    )
    distinct_count: int | None = Field(
        default=None,
        description="Distinct non-null value count (categorical columns only).",
    )


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
    # feat(#1221): `stale` means the member's own raster was replaced after the
    # parent VRT was last built. The member is fine — it is the parent's stored
    # VRT that still names the superseded COG, so the fix is a regenerate, not
    # anything done to the source. Distinct from `inaccessible`, which is about
    # the member itself and sends the reader somewhere else entirely.
    status: Literal["healthy", "missing", "inaccessible", "stale"]


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


class SourceHealthResponse(BaseModel):
    """Result of one on-demand origin probe (ADR-002, #1222).

    Shares its first three words with ``VrtSourceHealth.status``, so the UI
    renders one legend across VRT members and standalone origins.
    ``VrtSourceHealth`` carries a fourth, VRT-specific value, ``stale``
    (fix(#1221)): it means a member's raster was replaced after the parent
    VRT was last built, and it does not apply to a single-origin probe. This
    endpoint always probes, so it also never returns the OTHER fourth value,
    ``unknown`` — the response-boundary projection of a never-determined NULL
    column, which reaches clients through ``DatasetResponse``, not through
    here.
    """

    dataset_id: uuid.UUID
    origin: str | None = Field(
        description="Origin kind that was probed: service or stac."
    )
    source_health: Literal["healthy", "missing", "inaccessible"] = Field(
        description=(
            "healthy — the origin answered and the resource is there. "
            "missing — the origin answered authoritatively that it is gone "
            "(404/410). inaccessible — GeoLens could not determine either "
            "way, which includes 401/403: access was lost, the data may be "
            "intact."
        )
    )
    source_health_detail: str | None = Field(
        default=None,
        description=SOURCE_HEALTH_DETAIL_DESCRIPTION,
    )
    last_checked_at: datetime | None = Field(
        default=None,
        description="When GeoLens last contacted this origin, success or failure.",
    )


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


class DatasetRelationshipListResponse(BaseModel):
    """Paginated list envelope for dataset FK relationships (GAP-033).

    Mirrors the ``{<entity>: [...], total: int}`` convention used by every other
    paginated list endpoint (e.g. AttributeMetadataListResponse,
    VrtGenerationListResponse) so callers can detect whether more pages exist.
    ``total`` is the count of *visible* relationships before skip/limit.
    """

    relationships: list[DatasetRelationshipResponse]
    total: int


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


# ---------------------------------------------------------------------------
# Analysis (M4) — parameterized PostGIS operations
# ---------------------------------------------------------------------------

# Operation-scoped request fields → the only operation that reads them.
# Documented as "<op> only; ignored otherwise", and actually dropped by the
# request validators (fix(#682): a stray mask_dataset_id sent alongside
# buffer/centroid would otherwise be loaded — and could 404/422 the request
# or fail the job — and distance's gt/le bounds fire on placeholder values).
# fix(#955): values are tuples because a param can belong to more than one
# operation — select_by_location takes its selection geometry from the same
# `mask`/`mask_dataset_id` pair clip does, rather than a second spelling of the
# same two fields.
_ANALYSIS_PARAM_OWNERS = {
    "distance_meters": ("buffer",),
    "mask": ("clip", "select_by_location"),
    "mask_dataset_id": ("clip", "select_by_location", "intersect"),
    "by_field": ("dissolve",),
    "join_dataset_id": ("spatial_join",),
    "join_fields": ("spatial_join",),
}

# Operations whose geometry comes from a drawn mask or a mask layer, exactly
# one of the two. fix(#956): intersect is deliberately NOT here — it takes a
# LAYER only, because a drawn polygon carries no attributes to overlay with,
# which would make it an expensive clip.
MASK_OPERATIONS = ("clip", "select_by_location")


def _drop_params_for_other_operations(data: Any) -> Any:
    if isinstance(data, dict):
        op = data.get("operation")
        data = {
            k: v for k, v in data.items() if op in _ANALYSIS_PARAM_OWNERS.get(k, (op,))
        }
    return data


def _require_analysis_params(request: Any) -> None:
    """Per-operation requiredness, shared by preview and materialize.

    The two request models carry the same rules for every operation they have
    in common, and drifting them apart is how a param ends up required on one
    endpoint and optional on the other. ``dissolve``'s ``by_field`` is
    genuinely optional and materialize-only, so it has nothing here.
    """
    if request.operation == "buffer" and request.distance_meters is None:
        raise ValueError("buffer requires distance_meters")
    if request.operation in MASK_OPERATIONS and (request.mask is None) == (
        request.mask_dataset_id is None
    ):
        raise ValueError(
            f"{request.operation} requires exactly one of mask or mask_dataset_id"
        )
    # fix(#956): layer only, and required. `mask` is not an intersect param, so
    # _drop_params_for_other_operations has already discarded any drawn one by
    # the time this runs — this just insists on the layer that replaces it.
    if request.operation == "intersect" and request.mask_dataset_id is None:
        raise ValueError("intersect requires mask_dataset_id")
    if request.operation == "spatial_join":
        if request.join_dataset_id is None:
            raise ValueError("spatial_join requires join_dataset_id")
        fields = request.join_fields or []
        if len(fields) != len(set(fields)):
            raise ValueError("join_fields must not repeat a column")


class AnalysisPreviewRequest(BaseModel):
    """Parameters for a synchronous analysis preview.

    Deliberately flat (no discriminated union) so SDK generators keep the
    endpoint; per-operation requiredness is enforced by the validator.
    """

    operation: Literal[
        "buffer",
        "centroid",
        "clip",
        "spatial_join",
        "measure",
        "select_by_location",
        "intersect",
    ]
    distance_meters: float | None = Field(
        default=None,
        gt=0,
        le=100_000,
        description="Buffer distance in meters (buffer only)",
    )
    mask: dict[str, Any] | None = Field(
        default=None,
        description=(
            "GeoJSON Polygon or MultiPolygon geometry in EPSG:4326 "
            "(clip and select_by_location)"
        ),
    )
    mask_dataset_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Polygon dataset supplying the second layer: the area clipped to, "
            "selected against, or overlaid with. For clip and "
            "select_by_location it is the alternative to `mask`; for intersect "
            "it is REQUIRED and `mask` is rejected, because an overlay carries "
            "the second layer's attributes onto its output and a drawn polygon "
            "has none."
        ),
    )
    join_dataset_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Dataset to join against; each source feature gains a count of the "
            "features from it that intersect (spatial_join only)"
        ),
    )
    join_fields: list[str] | None = Field(
        default=None,
        max_length=MAX_SPATIAL_JOIN_FIELDS,
        description=(
            "Columns to copy from the intersecting join feature, prefixed "
            "'join_' in the output. Ties break on the lowest join-layer gid "
            "(spatial_join only)"
        ),
    )
    bbox: list[float] | None = Field(
        default=None,
        description=(
            "[minx, miny, maxx, maxy] in EPSG:4326, typically the map's "
            "current viewport. When present, only source features "
            "intersecting the envelope are considered before the preview's "
            "row cap applies, so a capped result reflects what is on screen "
            "rather than an arbitrary sample in ingest order (fix(#727)). "
            "Applies to every operation, not just one, so it is deliberately "
            "absent from _ANALYSIS_PARAM_OWNERS — omit it to preview the "
            "whole dataset, unchanged from before this field existed."
        ),
    )

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError(
                "bbox must have exactly 4 coordinates [minx, miny, maxx, maxy]"
            )
        if not all(math.isfinite(v) for v in value):
            raise ValueError("bbox coordinates must be finite numbers")
        minx, miny, maxx, maxy = value
        # No antimeridian-crossing support here, unlike the OGC bbox parsers
        # elsewhere in this codebase — this field feeds ST_MakeEnvelope
        # directly (see render_bbox_predicate), which has no wraparound
        # semantics of its own, so a minx > maxx envelope would silently
        # render as an empty or nonsensical box rather than the two-envelope
        # split the OGC paths use. Reject it instead of guessing.
        if minx > maxx:
            raise ValueError("bbox minx is greater than maxx")
        if miny > maxy:
            raise ValueError("bbox miny is greater than maxy")
        return value

    @model_validator(mode="before")
    @classmethod
    def _drop_ignored_params(cls, data: Any) -> Any:
        return _drop_params_for_other_operations(data)

    @model_validator(mode="after")
    def _require_operation_params(self) -> "AnalysisPreviewRequest":
        _require_analysis_params(self)
        return self


class AnalysisPreviewResponse(BaseModel):
    """GeoJSON FeatureCollection preview of an analysis operation."""

    geojson: dict[str, Any]
    feature_count: int
    truncated: bool
    bbox: list[float] | None = None
    source_feature_count: int | None = Field(
        default=None,
        description=(
            "Total feature count of the source dataset (1:1 operations only; "
            "null when the operation filters rows, e.g. clip). When the "
            "request carried a bbox this is a LIVE count of rows intersecting "
            "it rather than the dataset's cached whole-table total (fix(#727)) "
            "— also null, same as match_count, when that live count could not "
            "be computed within the query budget"
        ),
    )
    match_count: int | None = Field(
        default=None,
        description=(
            "Exact total across the WHOLE source, not just the previewed "
            "features — WHOLE meaning the request's bbox when one was sent, "
            "the same sense source_feature_count uses that word. What it "
            "counts is per-operation, so read it against the operation you "
            "sent rather than as one number: select_by_location gives the "
            "selected source features and intersect gives the output "
            "pieces, and for both of those it IS the output total; "
            "spatial_join gives intersecting source/join PAIRS, which is "
            "NOT the output total, because the join keeps every source row "
            "(use source_feature_count for that operation). intersect and "
            "spatial_join both scope this total to a bbox on the request; "
            "select_by_location's count is a separate uncapped query the "
            "request's bbox does not reach, so it stays unscoped even "
            "though its preview rows are viewport-limited too. Null for "
            "operations that report no such total, and when the count "
            "could not be computed within the query budget"
        ),
    )


class AnalysisMaterializeRequest(BaseModel):
    """Parameters for materializing an analysis result as a new dataset."""

    operation: Literal[
        "buffer",
        "centroid",
        "clip",
        "dissolve",
        "spatial_join",
        "measure",
        "select_by_location",
        "intersect",
    ]
    title: str = Field(min_length=1, max_length=500)
    distance_meters: float | None = Field(
        default=None,
        gt=0,
        le=100_000,
        description="Buffer distance in meters (buffer only)",
    )
    mask: dict[str, Any] | None = Field(
        default=None,
        description=(
            "GeoJSON Polygon or MultiPolygon geometry in EPSG:4326 "
            "(clip and select_by_location)"
        ),
    )
    mask_dataset_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Polygon dataset supplying the second layer: the area clipped to, "
            "selected against, or overlaid with. For clip and "
            "select_by_location it is the alternative to `mask`; for intersect "
            "it is REQUIRED and `mask` is rejected, because an overlay carries "
            "the second layer's attributes onto its output and a drawn polygon "
            "has none."
        ),
    )
    by_field: str | None = Field(
        default=None,
        max_length=63,
        description="Optional group-by column for dissolve",
    )
    join_dataset_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Dataset to join against; each source feature gains a count of the "
            "features from it that intersect (spatial_join only)"
        ),
    )
    join_fields: list[str] | None = Field(
        default=None,
        max_length=MAX_SPATIAL_JOIN_FIELDS,
        description=(
            "Columns to copy from the intersecting join feature, prefixed "
            "'join_' in the output. Ties break on the lowest join-layer gid "
            "(spatial_join only)"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_ignored_params(cls, data: Any) -> Any:
        return _drop_params_for_other_operations(data)

    @model_validator(mode="after")
    def _require_operation_params(self) -> "AnalysisMaterializeRequest":
        _require_analysis_params(self)
        return self


class AnalysisMaterializeResponse(BaseModel):
    """Async materialize job handle; poll GET /jobs/{job_id} for progress."""

    job_id: uuid.UUID
    status: str


class DatasetRefreshRunResponse(BaseModel):
    """One refresh attempt, success or failure (ADR-002 Decision 4).

    Five fields are redacted for callers who are neither the dataset owner nor
    an admin: ``triggered_by``, ``triggered_by_username``, ``error_code``,
    ``error_message`` and ``schema_diff``. A public dataset's refresh history
    otherwise enumerates who edits it, and failure text leaks internal origin
    detail. The redaction is enumerated against NAMED third-party readers as
    well as anonymous ones — a signed-in stranger is the case that gets
    missed.
    """

    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The version this run produced. Null for a run that never committed a swap."
        ),
    )
    ingest_job_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The ingest job that carried out the work. Nulls out when the job "
            "row is purged by retention; the run itself survives."
        ),
    )
    origin_kind: str = Field(
        description=(
            "The run's execution door, not the dataset's origin: upload, "
            "postgis, service, stac, or raster. The two can visibly "
            "diverge; for example a STAC-imported raster's pending or "
            "failed replace run is recorded 'upload' while the dataset's "
            "origin stays 'stac' until the replace succeeds. 'raster' "
            "itself is reserved for a future, distinct raster-replace door "
            "label, with today's raster-replace runs recorded 'upload'."
        )
    )
    trigger: str = Field(description="manual, api, or cli")
    status: str = Field(description="pending, running, succeeded, failed, or cancelled")
    triggered_by: uuid.UUID | None = None
    triggered_by_username: str | None = None
    started_at: datetime = Field(
        description="Dispatch time, not claim time — queue wait is visible"
    )
    claimed_at: datetime | None = Field(
        default=None,
        description=(
            "When a worker began executing the run. Queue wait is this minus "
            "started_at; null while the run is still queued."
        ),
    )
    finished_at: datetime | None = None
    feature_count_before: int | None = None
    feature_count_after: int | None = None
    schema_diff: SchemaDiff | None = Field(
        default=None,
        description=(
            "Schema drift measured against the incoming data at swap time. "
            "Null for a run that never reached the swap."
        ),
    )
    error_code: str | None = None
    error_message: str | None = Field(
        default=None, description="Short redacted failure reason"
    )


class DatasetRefreshRunListResponse(BaseModel):
    runs: list[DatasetRefreshRunResponse]
    total: int
