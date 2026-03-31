"""Search and OGC API Records response schemas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchParams(BaseModel):
    """Query parameters for dataset search."""

    q: str | None = None
    bbox: str | None = None
    keywords: list[str] | None = None
    geometry_type: str | None = None
    srid: int | None = None
    source_organization: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    vintage_start: date | None = None
    vintage_end: date | None = None
    sort_by: str = "relevance"
    offset: int = 0
    limit: int = 10
    exclude_synthetic: bool = True

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: str | None) -> str | None:
        if v is not None:
            parts = v.split(",")
            if len(parts) != 4:
                raise ValueError("bbox must have exactly 4 comma-separated values")
            floats = [float(p) for p in parts]
            # Allow antimeridian-crossing bboxes (minx > maxx)
            if floats[1] >= floats[3]:
                raise ValueError("bbox miny must be less than maxy")
        return v


class OGCRecordProperties(BaseModel):
    """Properties block of an OGC API Records Feature."""

    type: str = "dataset"
    title: str
    description: str | None = None
    keywords: list[str] | None = None
    created: datetime | None = None
    updated: datetime | None = None
    updated_by_display: str | None = None
    never_edited: bool = False
    crs: str | None = None
    record_type: str = "vector_dataset"
    band_count: int | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    license: str | None = None
    source_organization: str | None = None
    quality_detail: dict | None = None
    formats: list[str] | None = None
    language: str | None = None
    themes: list[dict] | None = None
    rights: str | None = None
    contacts: list[dict] | None = None
    time: dict | None = None
    lineage: str | None = None
    update_frequency: str | None = None
    constraints: dict | None = None
    distributions: list[dict] | None = None
    record_status: str | None = None
    has_quicklook: bool = False
    gsd: float | None = None
    vrt_type: str | None = None
    source_count: int | None = None
    dataset_count: int | None = None


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
    time: dict | None = None  # OGC Records temporal extent at record root
    geometry: dict | None = None  # GeoJSON bbox polygon — built dynamically
    properties: OGCRecordProperties
    links: list[OGCRecordLink]
    assets: dict[str, OGCAsset] | None = None
    bbox: list[float] | None = None


class OGCFeatureCollectionResponse(BaseModel):
    """OGC API Records FeatureCollection with match counts."""

    type: str = "FeatureCollection"
    timeStamp: str | None = None
    numberMatched: int
    numberReturned: int
    features: list[OGCRecordResponse]
    links: list[OGCRecordLink] | None = None


# ---------------------------------------------------------------------------
# Saved search schemas
# ---------------------------------------------------------------------------


class SavedSearchCreate(BaseModel):
    """Request body for creating a saved search."""

    name: str = Field(min_length=1, max_length=255)
    params: dict


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

    record_type: dict[str, int]
    keywords: list[FacetValueCount] = []
    source_organization: list[FacetValueCount] = []
    srid: list[FacetValueCount] = []
    collections: list[CollectionFacetItem] = []


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
