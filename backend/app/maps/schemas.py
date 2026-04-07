import uuid
from enum import Enum
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MapVisibility(str, Enum):
    private = "private"
    internal = "internal"
    public = "public"


class MapLayerInput(BaseModel):
    dataset_id: uuid.UUID
    sort_order: int = Field(
        default=0, ge=0, description="Draw order (lower draws first)"
    )
    visible: bool = True
    opacity: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Layer opacity 0.0-1.0"
    )
    paint: dict | None = Field(
        default=None, description="MapLibre paint properties override"
    )
    layout: dict | None = Field(
        default=None, description="MapLibre layout properties override"
    )
    display_name: str | None = Field(
        default=None, max_length=255, description="Label shown in the layer list"
    )
    filter: list | dict | None = Field(
        default=None, description="MapLibre filter expression"
    )
    label_config: dict | None = Field(
        default=None, description="Text label configuration"
    )
    style_config: dict | None = Field(
        default=None, description="Data-driven style configuration"
    )
    layer_type: str | None = Field(
        default=None, description="Auto-detected from record_type if omitted"
    )
    show_in_legend: bool = Field(
        default=True, description="Whether to include in the map legend"
    )


class MapCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class MapUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    center_lng: float | None = Field(default=None, description="Map center longitude")
    center_lat: float | None = Field(default=None, description="Map center latitude")
    zoom: float | None = Field(default=None, ge=0, le=24, description="Map zoom level")
    bearing: float | None = Field(
        default=None, ge=-180, le=180, description="Map rotation in degrees"
    )
    pitch: float | None = Field(
        default=None, ge=0, le=85, description="Map tilt in degrees (0-85)"
    )
    basemap_style: str | None = Field(
        default=None, description="Basemap style ID or URL"
    )
    show_basemap_labels: bool | None = None
    visibility: MapVisibility | None = Field(
        default=None, description="private, internal, or public"
    )
    layers: list[MapLayerInput] | None = Field(
        default=None, description="Full replacement layer list"
    )
    widgets: list[str] | None = Field(
        default=None, description="Enabled widget IDs, e.g. ['measurement']"
    )


class MapLayerResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    dataset_geometry_type: str | None
    dataset_table_name: str
    dataset_extent_bbox: list[float] | None
    dataset_column_info: list[dict] | None = None
    dataset_feature_count: int | None = None
    dataset_sample_values: dict | None = None
    display_name: str | None = None
    sort_order: int
    visible: bool
    opacity: float
    paint: dict
    layout: dict
    layer_type: str = "vector_geolens"
    dataset_record_type: str | None = None
    filter: list | dict | None = None
    label_config: dict | None = None
    style_config: dict | None = None
    show_in_legend: bool = True

    model_config = ConfigDict(from_attributes=True)


class MapResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    center_lng: float | None
    center_lat: float | None
    zoom: float | None
    bearing: float
    pitch: float
    basemap_style: str
    show_basemap_labels: bool
    visibility: MapVisibility
    thumbnail_url: str | None = None
    forked_from_id: uuid.UUID | None = Field(
        default=None, description="Source map UUID if this is a fork"
    )
    forked_from_name: str | None = None
    created_by: uuid.UUID | None
    created_by_username: str | None = None
    created_at: datetime
    updated_at: datetime
    layers: list[MapLayerResponse]
    layer_count: int
    widgets: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class DuplicateMapResponse(MapResponse):
    excluded_layer_count: int = Field(
        default=0, description="Layers skipped due to access restrictions"
    )


class MapSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    visibility: MapVisibility
    thumbnail_url: str | None = None
    layer_count: int
    created_by_username: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MapListResponse(BaseModel):
    maps: list[MapSummaryResponse]
    total: int


class SharedLayerResponse(BaseModel):
    dataset_id: str
    dataset_name: str
    display_name: str | None = None
    table_name: str
    geometry_type: str | None
    column_info: list[dict] | None = None
    sort_order: int
    visible: bool
    opacity: float
    paint: dict
    layout: dict
    layer_type: str = "vector_geolens"
    dataset_record_type: str | None = None
    filter: list | dict | None = None
    label_config: dict | None = None
    style_config: dict | None = None
    show_in_legend: bool = True
    tile_url: str


class SharedMapResponse(BaseModel):
    name: str
    description: str | None
    center_lng: float
    center_lat: float
    zoom: float
    bearing: float
    pitch: float
    basemap_style: str
    show_basemap_labels: bool = True
    has_non_public_layers: bool = False
    layers: list[SharedLayerResponse]


class ShareTokenRequest(BaseModel):
    expires_at: datetime | None = Field(
        default=None, description="Expiration timestamp; null = never expires"
    )

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, v):
        if v is not None and v < datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v


class ShareTokenResponse(BaseModel):
    token: str = Field(description="Opaque share token")
    share_url: str = Field(description="Full shareable URL including token")
    expires_at: datetime | None = None
    is_active: bool = True


class AdminShareTokenResponse(BaseModel):
    id: uuid.UUID
    map_id: uuid.UUID
    map_name: str
    token: str
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
    created_by: str | None
    embed_token_count: int = 0


class AdminShareTokenListResponse(BaseModel):
    tokens: list[AdminShareTokenResponse]
    total: int


class VisibilityCheckResponse(BaseModel):
    non_public_datasets: list[str] = Field(
        description="Titles of datasets not publicly visible"
    )
    has_non_public: bool = Field(
        description="True if any layer references a non-public dataset"
    )
