import json
import uuid
from enum import Enum
from datetime import datetime, timezone
from typing import Annotated, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.text import normalize_nfc as _nfc

# MapLayer style overrides are open dicts (paint, layout, label_config, style_config)
# because MapLibre's property surface is large and dynamic. Bound the JSON-serialized
# size to prevent a single PUT from storing a megabytes-sized JSONB blob per layer.
_MAX_STYLE_DICT_BYTES = (
    64 * 1024
)  # 64 KB serialized — generous for any real style override
# MapUpdate.layers caps the per-map layer count. Real maps rarely exceed 50 layers.
_MAX_LAYERS_PER_MAP = 200


def _validate_style_dict(v: dict | None) -> dict | None:
    """Reject style-override dicts whose JSON serialization exceeds the cap."""
    if v is None:
        return v
    serialized = json.dumps(v, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > _MAX_STYLE_DICT_BYTES:
        raise ValueError(
            f"Style configuration too large (>{_MAX_STYLE_DICT_BYTES} bytes serialized)"
        )
    return v


class PopupConfig(BaseModel):
    """Per-layer popup configuration: enable/disable + custom title template
    + ordered visible-fields allowlist. Persisted as JSONB on map_layers."""

    enabled: bool
    expression: str | None = Field(
        default=None,
        max_length=500,
        description="Title template with {column_name} placeholders",
    )
    visible_fields: (
        list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] | None
    ) = Field(
        default=None,
        max_length=100,
        description=(
            "Ordered allowlist of property keys; null = all, [] = none, "
            "ordered list = those in order"
        ),
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("visible_fields")
    @classmethod
    def _no_duplicates(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if len(set(v)) != len(v):
            raise ValueError("visible_fields entries must be unique")
        return v


class MapVisibility(str, Enum):
    # Note: 'restricted' is intentionally omitted — maps don't support
    # restricted visibility; only datasets do.
    private = "private"
    internal = "internal"
    public = "public"


class MapLayerInput(BaseModel):
    dataset_id: uuid.UUID
    sort_order: int = Field(
        default=0,
        ge=0,
        le=32767,
        description="Draw order (lower draws first)",
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
    filter: list | None = Field(default=None, description="MapLibre filter expression")
    label_config: dict | None = Field(
        default=None, description="Text label configuration"
    )
    popup_config: PopupConfig | None = Field(
        default=None,
        description="Popup configuration: {enabled, expression, visible_fields}",
    )
    style_config: dict | None = Field(
        default=None, description="Data-driven style configuration"
    )

    _validate_paint = field_validator("paint")(_validate_style_dict)
    _validate_layout = field_validator("layout")(_validate_style_dict)
    _validate_label_config = field_validator("label_config")(_validate_style_dict)
    _validate_style_config = field_validator("style_config")(_validate_style_dict)
    layer_type: str | None = Field(
        default=None,
        pattern=r"^(vector_geolens|raster_geolens|geojson)$",
        description="Auto-detected from record_type if omitted",
    )
    show_in_legend: bool = Field(
        default=True, description="Whether to include in the map legend"
    )


class MapCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Map display name",
        example="NYC Infrastructure",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Short description for sharing",
        example="Buildings, parks, and transit routes in Manhattan",
    )
    notes: str | None = Field(
        default=None,
        max_length=50_000,
        description="Private notes (not shown publicly)",
    )

    @field_validator("name", "description", "notes", mode="before")
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)


class MapUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=50_000)

    @field_validator("name", "description", "notes", mode="before")
    @classmethod
    def normalize_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)

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
        default=None, max_length=2000, description="Basemap style ID or URL"
    )
    show_basemap_labels: bool | None = None
    visibility: MapVisibility | None = Field(
        default=None, description="private, internal, or public"
    )
    layers: list[MapLayerInput] | None = Field(
        default=None,
        max_length=_MAX_LAYERS_PER_MAP,
        description=f"Full replacement layer list (max {_MAX_LAYERS_PER_MAP} layers)",
    )
    widgets: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Enabled widget IDs, e.g. ['measurement']",
    )


class DatasetMetaKwargs(TypedDict, total=False):
    """Keyword arguments carrying dataset metadata into _build_layer_response."""

    dataset_name: str
    geometry_type: str | None
    table_name: str
    extent: object
    column_info: list | None
    feature_count: int | None
    sample_values: dict | None
    record_type: str | None
    is_3d: bool | None


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
    filter: list | None = None
    label_config: dict | None = None
    popup_config: PopupConfig | None = None
    style_config: dict | None = None
    show_in_legend: bool = True
    is_3d: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class MapResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    notes: str | None = None
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
    filter: list | None = None
    label_config: dict | None = None
    popup_config: PopupConfig | None = None
    style_config: dict | None = None
    show_in_legend: bool = True
    tile_url: str
    is_dem: bool | None = None
    is_3d: bool | None = None
    feature_count: int | None = None


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
    def expires_at_must_be_future(cls, v: datetime | None) -> datetime | None:
        if v is not None and v < datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v


class ShareTokenResponse(BaseModel):
    token: str = Field(description="Raw token on create, hint on retrieve")
    share_url: str | None = Field(
        default=None, description="Full shareable URL — only returned on create"
    )
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
