"""Search and OGC API Records response schemas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

from app.modules.catalog.features.service import parse_bbox


class SearchParams(BaseModel):
    """Query parameters for dataset search."""

    q: str | None = Field(
        default=None,
        description="Free-text search query (supports full-text + semantic)",
    )
    bbox: str | None = Field(
        default=None, description="Spatial filter as minx,miny,maxx,maxy (EPSG:4326)"
    )
    keywords: list[str] | None = Field(
        default=None, description="Filter by one or more keyword tags"
    )
    geometry_type: str | None = Field(
        default=None, description="Filter by OGC geometry type, e.g. Point"
    )
    srid: int | None = Field(default=None, description="Filter by EPSG SRID")
    source_organization: str | None = None
    date_from: date | None = Field(
        default=None, description="Include records created on or after this date"
    )
    date_to: date | None = Field(
        default=None, description="Include records created on or before this date"
    )
    vintage_start: date | None = Field(
        default=None, description="Minimum data vintage start date"
    )
    vintage_end: date | None = Field(
        default=None, description="Maximum data vintage end date"
    )
    sort_by: str = Field(
        default="relevance",
        description="Sort order: relevance, title, created, updated",
    )
    offset: int = Field(default=0, description="Number of results to skip (pagination)")
    limit: int = Field(
        default=10, ge=1, le=1000, description="Max results to return (1-1000)"
    )
    exclude_synthetic: bool = Field(
        default=True, description="Exclude VRT mosaics and derived records"
    )

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: str | None) -> str | None:
        # Validate through the shared parser rather than a third copy of the
        # split/collapse/compare logic: the copies drifted before, and the one
        # here was also missing the SEC-FU-06 non-finite guard.
        if v is not None:
            parse_bbox(v)
        return v


class OGCRasterBand(BaseModel):
    """One entry in the raster:bands STAC extension array.

    fix(#1805 review round 3 P2): matches the shape service_records.py
    actually serializes per band. `statistics` matches the normalized
    band_info shape core/raster_bands.py (introduced by #1803, the raster
    lifecycle PR) produces on read; keep this in sync if that PR changes
    the per-band keys.
    """

    name: str | None = None
    data_type: str | None = None
    # fix(#1805 review round 3 P2, discovered while adding the pinned test):
    # band_info is a raw JSONB column (RasterAsset.band_info) not schema-
    # constrained at the DB layer, and service_records.py passes bi["nodata"]
    # through verbatim (no str() coercion) -- a band's nodata sentinel can be
    # an int or float as easily as a string, unlike the TOP-LEVEL
    # RasterAsset.nodata column, which IS Text. str-only here 422'd on a real
    # int nodata value the first time this schema was exercised end-to-end.
    nodata: str | int | float | None = None
    statistics: dict | None = None
    description: str | None = None

    # fix(#1805 review round 4 P2): /search/datasets validates through
    # OGCFeatureCollectionResponse, and FastAPI's default response
    # serialization fills in every declared field's default (None) for
    # this nested model regardless of whether the raw dict provided the
    # key -- so "band lacks a nodata key" (genuinely unavailable) and
    # "band has nodata: null" (confirmed absent, per service_records.py's
    # explicit None above) collapsed into the SAME wire shape (nodata:
    # null) the moment round 3 declared this field. That defeated the
    # tri-state distinction the client relies on (defined / absent /
    # unknown). model_fields_set still reflects whether `nodata` was in
    # the input dict; drop the key from the dump when it was not, so
    # "unknown" stays genuinely absent from the response.
    @model_serializer(mode="wrap")
    def _serialize_nodata_presence(self, handler):  # noqa: ANN001
        data = handler(self)
        if "nodata" not in self.model_fields_set:
            data.pop("nodata", None)
        return data


class OGCRecordProperties(BaseModel):
    """Properties block of an OGC API Records Feature."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = "dataset"
    title: str
    description: str
    keywords: list[str]
    created: datetime | None = None
    updated: datetime | None = None
    updated_by_display: str | None = None
    never_edited: bool = False
    crs: str | None = None
    record_type: str = "vector_dataset"
    band_count: int | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    row_count: int | None = Field(
        default=None,
        description="Row count for tabular records (alias for feature_count when record_type='table').",
    )
    column_count: int | None = Field(
        default=None,
        description="Number of columns in the dataset (populated from column_info length).",
    )
    license: str
    source_organization: str | None = None
    source_format: str | None = Field(
        default=None,
        description=(
            "Ingest source format ('geojson', 'shapefile', 'geotiff', 'wfs', "
            "'stac', 'created', ...). Null for datasets registered from "
            "existing PostGIS tables and for composed VRT datasets."
        ),
    )
    quality_detail: dict | None = None
    quality_statement: str | None = None
    formats: list[str] | None = None
    language: str | None = None
    externalIds: list[str] = Field(
        default_factory=list,
        description="Identifiers assigned by the described resource's source system.",
    )
    themes: list[dict]
    rights: str | None = None
    contacts: list[dict]
    time: dict
    lineage: str | None = None
    update_frequency: str | None = None
    # feat(#1224): computed from the dataset's last_refreshed_at against
    # update_frequency above, gated on origin; never stored. See
    # datasets/domain/source_freshness.py.
    source_freshness: str = Field(
        default="unknown",
        description=(
            "fresh, due, overdue, or unknown — how the dataset's last refresh "
            "compares to its declared update_frequency. 'unknown' for origins "
            "nothing can refresh. Advisory only, and distinct from the quality "
            "score's own freshness."
        ),
    )
    source_health: str = Field(
        default="unknown",
        description=(
            "healthy, missing, inaccessible, or unknown. 'unknown' means "
            "never probed, or an origin kind with nothing to probe."
        ),
    )
    last_checked_at: datetime | None = Field(
        default=None,
        description=(
            "Last time GeoLens contacted the origin, whether the attempt "
            "succeeded or failed."
        ),
    )
    last_refreshed_at: datetime | None = Field(
        default=None,
        description="Last committed successful refresh — not the last attempt.",
    )
    constraints: dict | None = None
    distributions: list[dict] | None = None
    record_status: str | None = None
    has_quicklook: bool = False
    gsd: float | None = None
    crs_is_geographic: bool | None = Field(
        default=None,
        description=(
            "True when the raster CRS is geographic (gsd/res are degrees, "
            "not meters); None when the CRS class is unknown."
        ),
    )
    vrt_type: str | None = None
    source_count: int | None = None
    dataset_count: int | None = None
    # fix(#1805 review round 3 P2): these three were emitted by
    # service_records.py but never declared here, so /search/datasets
    # (which validates through OGCFeatureCollectionResponse, unlike the OGC
    # Records / STAC routers which return a raw dict) silently stripped
    # them -- every VrtCreatorForm compatibility check that reads them was
    # dead against the real search endpoint.
    proj_code: str | None = Field(default=None, alias="proj:code")
    proj_shape: tuple[int, int] | None = Field(
        default=None,
        alias="proj:shape",
        description="[height, width] in pixels.",
    )
    raster_bands: list[OGCRasterBand] | None = Field(default=None, alias="raster:bands")


class OGCRecordLink(BaseModel):
    """Link object in OGC API Records."""

    rel: str
    href: str
    type: str


class OGCAsset(BaseModel):
    """STAC-style asset entry for an OGC Record."""

    href: str
    type: str
    title: str | None = None
    roles: list[str] | None = None


class OGCRecordResponse(BaseModel):
    """Single OGC API Records Feature."""

    type: str = "Feature"
    id: str
    conformsTo: list[str] | None = None
    time: dict  # OGC Records temporal extent at record root
    geometry: dict | None = None  # GeoJSON bbox polygon — built dynamically
    properties: OGCRecordProperties
    links: list[OGCRecordLink]
    assets: dict[str, OGCAsset] | None = None
    bbox: list[float] | None = None


class OGCFeatureCollectionResponse(BaseModel):
    """OGC API Records FeatureCollection with match counts."""

    type: str = "FeatureCollection"
    timeStamp: str | None = None
    numberMatched: int = Field(description="Total records matching the query")
    numberReturned: int = Field(description="Number of records in this response page")
    features: list[OGCRecordResponse]
    links: list[OGCRecordLink] | None = Field(
        default=None, description="Pagination and self links"
    )


# ---------------------------------------------------------------------------
# Saved search schemas
# ---------------------------------------------------------------------------


class SavedSearchCreate(BaseModel):
    """Request body for creating a saved search."""

    name: str = Field(min_length=1, max_length=255)
    params: dict = Field(description="Serialized SearchParams filters to replay")


class SavedSearchResponse(BaseModel):
    """Response for a single saved search."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    params: dict
    created_at: datetime
    updated_at: datetime


class SavedSearchListResponse(BaseModel):
    """Response wrapping a list of saved searches."""

    searches: list[SavedSearchResponse]
    total: int


class FacetValueCount(BaseModel):
    """A single facet value with count."""

    value: str
    count: int


class CollectionFacetItem(BaseModel):
    """A collection facet entry."""

    id: str
    name: str
    dataset_count: int


class FacetCountResponse(BaseModel):
    """Multi-group facet counts for the search sidebar."""

    record_type: dict[str, int] = Field(description="Hit counts keyed by record type")
    keywords: list[FacetValueCount] = Field(
        default=[], description="Top keyword tags with counts"
    )
    source_organization: list[FacetValueCount] = Field(
        default=[], description="Top organizations with counts"
    )
    srid: list[FacetValueCount] = Field(default=[], description="Top SRIDs with counts")
    collections: list[CollectionFacetItem] = Field(
        default=[], description="Collections containing matched records"
    )


class OGCCollectionsResponse(BaseModel):
    """Response for /collections listing all available OGC collections."""

    collections: list[dict]
    links: list[OGCRecordLink] = []


class OGCCollectionMetadataResponse(BaseModel):
    """Response for /collections/datasets single collection metadata."""

    id: str
    title: str
    description: str
    itemType: str = "record"
    links: list[dict]
    extent: dict | None = None
    summaries: dict | None = None
