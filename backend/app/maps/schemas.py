import uuid
from enum import Enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MapVisibility(str, Enum):
    private = "private"
    internal = "internal"
    public = "public"


class MapLayerInput(BaseModel):
    dataset_id: uuid.UUID
    sort_order: int = 0
    visible: bool = True
    opacity: float = 1.0
    paint: dict | None = None
    layout: dict | None = None
    display_name: str | None = None
    filter: list | dict | None = None
    label_config: dict | None = None
    style_config: dict | None = None
    layer_type: str | None = None  # auto-detected from record_type if omitted
    show_in_legend: bool = True


class MapCreate(BaseModel):
    name: str
    description: str | None = None


class MapUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    center_lng: float | None = None
    center_lat: float | None = None
    zoom: float | None = None
    bearing: float | None = None
    pitch: float | None = None
    basemap_style: str | None = None
    visibility: MapVisibility | None = None
    layers: list[MapLayerInput] | None = None


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
    visibility: str
    thumbnail_url: str | None = None
    forked_from_id: uuid.UUID | None = None
    forked_from_name: str | None = None
    created_by: uuid.UUID | None
    created_by_username: str | None = None
    created_at: datetime
    updated_at: datetime
    layers: list[MapLayerResponse]
    layer_count: int

    model_config = ConfigDict(from_attributes=True)


class DuplicateMapResponse(MapResponse):
    excluded_layer_count: int = 0


class MapSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    visibility: str
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
    has_non_public_layers: bool = False
    layers: list[SharedLayerResponse]


class ShareTokenRequest(BaseModel):
    expires_at: datetime | None = None  # None = never expires


class ShareTokenResponse(BaseModel):
    token: str
    share_url: str
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
