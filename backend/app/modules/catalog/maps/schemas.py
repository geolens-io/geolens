import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.edition import is_enterprise
from app.core.text import normalize_nfc as _nfc

ADVANCED_SHARING_ERROR = (
    "Advanced sharing controls require the GeoLens Enterprise overlay"
)
LEGACY_BUILDER_PAINT_KEYS = {
    "_outline-width": "outline_width",
    "outline-width": "outline_width",
    "_outline-color": "outline_color",
    "outline-color": "outline_color",
    "_fill-disabled": "fill_disabled",
    "_stroke-disabled": "stroke_disabled",
    "_fill-opacity-saved": "fill_opacity_saved",
    "_outline-width-saved": "outline_width_saved",
    "_heatmap-ramp": "heatmap_ramp",
    "_heatmap-weight-column": "heatmap_weight_column",
    "_height_column": "height_column",
}
_STYLE_CONFIG_BUILDER_KEY = "builder"

# Phase 1060 close-gate (G-x e2e fix): the frontend normalizes builder keys
# from snake_case (storage canonical) to camelCase on layer load via
# `frontend/src/lib/normalize-style-config.ts:normalizeBuilderStyleConfig`.
# When a layer is duplicated, the React state's camelCase keys are POSTed
# back, and without server-side normalization the new layer would persist
# camelCase while the original (created via default style) stays snake_case.
# This map inverts `style_json._BUILDER_KEY_ALIASES` so the validator can
# canonicalize incoming style_config.builder keys to snake_case before
# storage — keeping the DB schema consistent regardless of which client
# wrote the row.
_BUILDER_CAMEL_TO_SNAKE_KEYS = {
    "fillDisabled": "fill_disabled",
    "strokeDisabled": "stroke_disabled",
    "fillOpacitySaved": "fill_opacity_saved",
    "outlineWidthSaved": "outline_width_saved",
    "outlineColor": "outline_color",
    "outlineWidth": "outline_width",
    "heatmapRamp": "heatmap_ramp",
    "heatmapWeightColumn": "heatmap_weight_column",
    "heightColumn": "height_column",
    "heightScale": "height_scale",
    "extrusionMinZoom": "extrusion_min_zoom",
    "extrusionOpacity": "extrusion_opacity",
    "arrowColor": "arrow_color",
    "arrowSize": "arrow_size",
    "arrowSpacing": "arrow_spacing",
    "clusterRadius": "cluster_radius",
    "clusterMaxZoom": "cluster_max_zoom",
    "clusterColor": "cluster_color",
    "clusterTextColor": "cluster_text_color",
    "clusterTextSize": "cluster_text_size",
    "folderGroupId": "folder_group_id",
    "folderGroupName": "folder_group_name",
    "folderGroupExpanded": "folder_group_expanded",
}


def canonicalize_builder_style_config(
    style_config: dict | None,
) -> dict | None:
    """Normalize style_config.builder keys to snake_case for storage.

    Idempotent: snake_case keys pass through unchanged; camelCase keys
    are rewritten to their snake_case equivalent. If both forms appear
    on the same record (unlikely but possible during the rollout),
    snake_case wins (last-write order in the dict).
    """
    if not isinstance(style_config, dict):
        return style_config
    builder = style_config.get(_STYLE_CONFIG_BUILDER_KEY)
    if not isinstance(builder, dict):
        return style_config
    converted: dict = {}
    for key, value in builder.items():
        canonical = _BUILDER_CAMEL_TO_SNAKE_KEYS.get(key, key)
        # If both camelCase and snake_case appear, snake_case wins by
        # virtue of being written last (callers typically pass snake_case
        # as the default style; camelCase only shows up on duplicates).
        if canonical in converted and canonical != key:
            continue
        converted[canonical] = value
    if converted != builder:
        new_config = dict(style_config)
        new_config[_STYLE_CONFIG_BUILDER_KEY] = converted
        return new_config
    return style_config


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


def _merge_builder_style_config(
    style_config: dict | None,
    builder_values: dict,
) -> dict | None:
    if not builder_values:
        return style_config

    merged = dict(style_config or {})
    existing_builder = merged.get(_STYLE_CONFIG_BUILDER_KEY)
    builder = dict(existing_builder) if isinstance(existing_builder, dict) else {}
    for key, value in builder_values.items():
        if value is not None and builder.get(key) is None:
            builder[key] = value
    if builder:
        merged[_STYLE_CONFIG_BUILDER_KEY] = builder
    return merged


def split_legacy_builder_paint(
    paint: dict | None,
    style_config: dict | None,
) -> tuple[dict | None, dict | None]:
    """Move bounded legacy builder metadata from paint into style_config.

    ``paint`` is the MapLibre storage/output boundary. During the rollout, old
    clients may still submit the known legacy keys listed in
    ``LEGACY_BUILDER_PAINT_KEYS``; those keys are stripped from paint and merged
    into ``style_config.builder``. Unknown underscore-prefixed paint keys remain
    invalid so private client state cannot keep leaking into stored paint JSON.
    """
    if paint is None:
        return paint, style_config

    clean_paint = dict(paint)
    builder_values: dict = {}
    for legacy_key, builder_key in LEGACY_BUILDER_PAINT_KEYS.items():
        if legacy_key in clean_paint:
            builder_values[builder_key] = clean_paint.pop(legacy_key)

    unknown_private_keys = sorted(
        key for key in clean_paint if isinstance(key, str) and key.startswith("_")
    )
    if unknown_private_keys:
        keys = ", ".join(unknown_private_keys)
        raise ValueError(f"Unsupported private paint key(s): {keys}")

    return clean_paint, _merge_builder_style_config(style_config, builder_values)


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


class TerrainConfig(BaseModel):
    enabled: bool = Field(default=False)
    source_dataset_id: uuid.UUID | None = Field(default=None)
    exaggeration: float = Field(default=1.0, ge=0.0, le=10.0)

    model_config = ConfigDict(extra="forbid")


class BasemapLabelMode(str, Enum):
    full = "full"
    subtle = "subtle"
    hidden = "hidden"


class BasemapSublayerVisibility(str, Enum):
    full = "full"
    subtle = "subtle"
    hidden = "hidden"


class BasemapLandWaterTone(str, Enum):
    default = "default"
    muted = "muted"
    contrast = "contrast"
    monochrome = "monochrome"


class BasemapReliefContrast(str, Enum):
    soft = "soft"
    standard = "standard"
    strong = "strong"


# Regex for #RRGGBB color field validation.
# Accepts exactly #RRGGBB (6 hex digits, case-insensitive).
# Rejects raw names ("red"), short hex ("#abc"), long hex ("#1234567"),
# and URI schemes ("javascript:", "data:") — security: T-1059A-01.
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class SublayerOverride(BaseModel):
    """Per-sublayer style override for a single basemap sublayer.

    All fields are nullable — a ``None`` value means "use the basemap default".
    Only ``#RRGGBB`` hex strings are accepted for color fields; ``None`` means
    the basemap default color is preserved.  Numeric ranges are clamped at
    validation time (Pydantic ``ge``/``le`` constraints).

    The key set of ``BasemapConfig.sublayer_overrides`` is treated as opaque
    (forward-compatible with future sublayer IDs) — see CONTEXT.md D-01.

    Security:
        extra="forbid" locks the D-14 scope guardrail: unknown style axes such
        as dash patterns, line caps, halo blur, and text-font are rejected at
        validation time (T-1059A-03).
    """

    stroke_color: str | None = Field(
        default=None,
        description="Stroke color in #RRGGBB hex format, or null to use the basemap default.",
    )
    stroke_width: float | None = Field(
        default=None,
        ge=0.0,
        le=20.0,
        description="Stroke width in pixels (0-20), or null to use the basemap default.",
    )
    casing_color: str | None = Field(
        default=None,
        description="Casing color in #RRGGBB hex format, or null to use the basemap default.",
    )
    casing_width: float | None = Field(
        default=None,
        ge=0.0,
        le=20.0,
        description="Casing width in pixels (0-20), or null to use the basemap default.",
    )
    min_zoom: float | None = Field(
        default=None,
        ge=0.0,
        le=24.0,
        description="Minimum zoom level at which the sublayer is visible (0-24), or null for default.",
    )
    max_zoom: float | None = Field(
        default=None,
        ge=0.0,
        le=24.0,
        description="Maximum zoom level at which the sublayer is visible (0-24), or null for default.",
    )
    opacity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Per-sublayer opacity (0-1), or null to use the basemap default. "
            "Additive on top of BasemapConfig.opacity (the whole-basemap master opacity). "
            "IN-02 (Phase 1059 code review): this field is populated via API or a future "
            "Phase milestone. The current UI opacity slider in BasemapSublayerEditorScene "
            "routes through the legacy sublayerState path (MapBuilderPage.tsx "
            "handleSublayerOpacityChange) per D-09 ('OPACITY — existing slider untouched') "
            "and does not call updateSublayerOverride. See TODO(BUILDER-SUBLAYER-PERSIST) "
            "comment at MapBuilderPage.tsx for the deferral rationale."
        ),
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("stroke_color", "casing_color")
    @classmethod
    def _validate_hex_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _HEX_COLOR_RE.match(v):
            raise ValueError(
                "Color must be in #RRGGBB hex format (e.g. #ff0000). "
                "Raw color names, short hex, and URI schemes are not accepted."
            )
        return v

    @model_validator(mode="after")
    def _validate_zoom_order(self) -> "SublayerOverride":
        """WR-02: Ensure min_zoom <= max_zoom when both are specified.

        MapLibre's behavior with an inverted zoom range (min > max) is undefined
        and version-dependent; in practice the layer becomes permanently invisible
        until the user corrects the values and resaves. Rejecting the payload at
        validation time surfaces the error at the API boundary.
        """
        if self.min_zoom is not None and self.max_zoom is not None:
            if self.min_zoom > self.max_zoom:
                raise ValueError(
                    f"min_zoom ({self.min_zoom}) must be <= max_zoom ({self.max_zoom})"
                )
        return self


class BasemapConfig(BaseModel):
    label_mode: BasemapLabelMode = Field(
        default=BasemapLabelMode.full,
        description="Basemap label prominence.",
    )
    road_visibility: BasemapSublayerVisibility = Field(
        default=BasemapSublayerVisibility.full,
        description="Road and transit sublayer visibility where supported.",
    )
    boundary_visibility: BasemapSublayerVisibility = Field(
        default=BasemapSublayerVisibility.full,
        description="Administrative boundary sublayer visibility where supported.",
    )
    building_visibility: bool = Field(
        default=True,
        description="Whether supported building/3D building basemap layers are shown.",
    )
    land_water_tone: BasemapLandWaterTone = Field(
        default=BasemapLandWaterTone.default,
        description="Land and water color treatment where supported.",
    )
    relief_contrast: BasemapReliefContrast | None = Field(
        default=None,
        description="Optional contrast hint for relief-oriented basemap styling.",
    )
    opacity: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Master basemap opacity 0.0-1.0",
    )
    background_color: str | None = Field(
        default=None,
        description=(
            "Map canvas background color in #RRGGBB hex format, "
            "or null to use the basemap default."
        ),
    )
    sublayer_overrides: dict[str, SublayerOverride] | None = Field(
        default=None,
        description=(
            "Per-sublayer style overrides keyed by semantic sublayer ID "
            "(e.g. 'road', 'boundary', 'building'). Key set is opaque — "
            "unknown future sublayer IDs are accepted without rejection. "
            "See CONTEXT.md D-01."
        ),
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("background_color")
    @classmethod
    def _validate_background_color(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _HEX_COLOR_RE.match(v):
            raise ValueError(
                "background_color must be in #RRGGBB hex format (e.g. #f8fafc). "
                "Raw color names, short hex, and URI schemes are not accepted."
            )
        return v


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
        default=None,
        description=(
            "Data-driven and builder UI style configuration. Builder-only state "
            "lives under builder, e.g. fill_disabled, stroke_disabled, outline "
            "settings, heatmap metadata, and height_column."
        ),
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

    @model_validator(mode="after")
    def _normalize_paint_boundary(self) -> "MapLayerInput":
        self.paint, self.style_config = split_legacy_builder_paint(
            self.paint,
            self.style_config,
        )
        # Phase 1060: canonicalize builder keys to snake_case (storage shape)
        # so frontend-normalized camelCase keys don't persist as a separate
        # schema after layer duplication. See canonicalize_builder_style_config.
        self.style_config = canonicalize_builder_style_config(self.style_config)
        _validate_style_dict(self.paint)
        _validate_style_dict(self.style_config)
        return self


class MapLayerPatch(BaseModel):
    id: uuid.UUID
    sort_order: int | None = Field(default=None, ge=0, le=32767)
    visible: bool | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    paint: dict | None = Field(
        default=None, description="MapLibre paint properties override"
    )
    layout: dict | None = Field(
        default=None, description="MapLibre layout properties override"
    )
    display_name: str | None = Field(default=None, max_length=255)
    filter: list | None = Field(default=None, description="MapLibre filter expression")
    label_config: dict | None = Field(
        default=None, description="Text label configuration"
    )
    popup_config: PopupConfig | None = Field(default=None)
    style_config: dict | None = Field(default=None)
    layer_type: str | None = Field(
        default=None,
        pattern=r"^(vector_geolens|raster_geolens|geojson)$",
    )
    show_in_legend: bool | None = None

    _validate_paint = field_validator("paint")(_validate_style_dict)
    _validate_layout = field_validator("layout")(_validate_style_dict)
    _validate_label_config = field_validator("label_config")(_validate_style_dict)
    _validate_style_config = field_validator("style_config")(_validate_style_dict)

    @model_validator(mode="after")
    def _normalize_paint_boundary(self) -> "MapLayerPatch":
        self.paint, self.style_config = split_legacy_builder_paint(
            self.paint,
            self.style_config,
        )
        # Phase 1060: canonicalize builder keys to snake_case (storage shape)
        # so frontend-normalized camelCase keys don't persist as a separate
        # schema after layer duplication. See canonicalize_builder_style_config.
        self.style_config = canonicalize_builder_style_config(self.style_config)
        _validate_style_dict(self.paint)
        _validate_style_dict(self.style_config)
        return self


class MapLayerDiffRequest(BaseModel):
    added: list[MapLayerInput] = Field(
        default_factory=list,
        max_length=_MAX_LAYERS_PER_MAP,
        description=f"Layers to append (max {_MAX_LAYERS_PER_MAP})",
    )
    updated: list[MapLayerPatch] = Field(default_factory=list)
    removed: list[uuid.UUID] = Field(default_factory=list)
    order: list[uuid.UUID] | None = Field(
        default=None,
        description="Optional stable layer ID order for existing layers",
    )
    fallback_full_replace: bool = Field(
        default=False,
        description="Client hint only; PATCH never performs full replacement",
    )

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "MapLayerDiffRequest":
        updated_ids = [layer.id for layer in self.updated]
        if len(set(updated_ids)) != len(updated_ids):
            raise ValueError("updated layer ids must be unique")
        if len(set(self.removed)) != len(self.removed):
            raise ValueError("removed layer ids must be unique")
        if self.order is not None and len(set(self.order)) != len(self.order):
            raise ValueError("order layer ids must be unique")
        return self


class MapCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Map display name",
        json_schema_extra={"example": "NYC Infrastructure"},
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Short description for sharing",
        json_schema_extra={
            "example": "Buildings, parks, and transit routes in Manhattan"
        },
    )
    notes: str | None = Field(
        default=None,
        max_length=50_000,
        description="Private notes (not shown publicly)",
    )
    terrain_config: TerrainConfig | None = Field(
        default=None,
        description="Map-level terrain source and exaggeration preferences",
    )
    basemap_config: BasemapConfig | None = Field(
        default=None,
        description="Curated map-level basemap appearance preferences",
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
    basemap_config: BasemapConfig | None = Field(
        default=None,
        description="Curated map-level basemap appearance preferences",
    )
    terrain_config: TerrainConfig | None = Field(
        default=None,
        description="Map-level terrain source and exaggeration preferences",
    )
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
    is_dem: bool | None
    dem_vertical_units: str | None


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
    is_dem: bool | None = None
    dem_vertical_units: str | None = None

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
    basemap_config: BasemapConfig | None = None
    terrain_config: TerrainConfig | None = None
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


class MapStyleImportWarning(BaseModel):
    code: str
    message: str
    source_id: str | None = None
    layer_id: str | None = None


class MapStyleImportSummary(BaseModel):
    sources_matched: int = 0
    sources_unsupported: int = 0
    layers_imported: int = 0
    layers_skipped: int = 0
    warnings: list[MapStyleImportWarning] = Field(default_factory=list)


class MapStyleImportResponse(BaseModel):
    map: MapResponse
    summary: MapStyleImportSummary


class MapStyleImportRequest(BaseModel):
    """Typed request body for POST /maps/import — API-01 / M-05.

    Mirrors the top-level keys of the MapLibre Style Specification that
    ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
    forward-compatibility with future MapLibre fields (e.g. ``projection``,
    ``light``, ``transition``) so adding a new key on the client side
    doesn't require a server release.

    Replacing the previous bare-``dict`` body parameter removes
    ``additionalProperties: true`` from the OpenAPI schema and lets
    openapi-python-client generate a navigable named model class.
    """

    version: int | None = Field(
        default=None,
        description="MapLibre style version (always 8 in current spec)",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Display name for the imported map",
    )
    metadata: dict | None = Field(
        default=None,
        description="Free-form metadata bag (used by GeoLens for center/zoom/basemap hints)",
    )
    center: list[float] | None = Field(
        default=None,
        description="[longitude, latitude] map center",
    )
    zoom: float | None = Field(default=None, ge=0, le=24)
    bearing: float | None = Field(default=None, ge=-180, le=180)
    pitch: float | None = Field(default=None, ge=0, le=85)
    sources: dict | None = Field(
        default=None,
        description="MapLibre sources object keyed by source id",
    )
    sprite: str | None = Field(default=None, max_length=2000)
    glyphs: str | None = Field(default=None, max_length=2000)
    terrain: dict | None = Field(
        default=None,
        description="MapLibre terrain config (source + exaggeration)",
    )
    layers: list[dict] | None = Field(
        default=None,
        description="MapLibre layer specifications",
    )

    model_config = ConfigDict(extra="allow")


class MapIconResponse(BaseModel):
    id: str
    name: str
    slug: str
    media_type: str
    url: str
    sprite_id: str
    size_bytes: int | None = None
    builtin: bool = False


class MapIconListResponse(BaseModel):
    icons: list[MapIconResponse]


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


class MapHistoryEventResponse(BaseModel):
    id: uuid.UUID
    map_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_username: str | None = None
    target_type: str
    target_id: uuid.UUID | None = None
    target_name: str | None = None
    action: str
    summary: str
    details: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MapHistoryListResponse(BaseModel):
    events: list[MapHistoryEventResponse]
    total: int
    skip: int
    limit: int


class SharedLayerResponse(BaseModel):
    id: str
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
    dem_vertical_units: str | None = None
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
    basemap_config: BasemapConfig | None = None
    terrain_config: TerrainConfig | None = None
    has_non_public_layers: bool = False
    layers: list[SharedLayerResponse]


class ShareTokenRequest(BaseModel):
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Expiration timestamp. Null creates a basic non-expiring share link; "
            "non-null expiration requires GeoLens Enterprise."
        ),
    )

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, v: datetime | None) -> datetime | None:
        if v is not None and v < datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v

    @model_validator(mode="after")
    def validate_enterprise_controls(self):
        if not is_enterprise() and self.expires_at is not None:
            raise ValueError(ADVANCED_SHARING_ERROR)
        return self


class ShareTokenResponse(BaseModel):
    token: str = Field(description="Raw token on create, hint on retrieve")
    share_url: str | None = Field(
        default=None, description="Full shareable URL — only returned on create"
    )
    expires_at: datetime | None = None
    is_active: bool = True


class MapAccessResponse(BaseModel):
    can_view: bool = Field(description="True when the current request may read the map")
    can_edit: bool = Field(
        description="True when the current request may open the map builder"
    )


class ThumbnailUploadRequest(BaseModel):
    """JSON body for PUT /maps/{map_id}/thumbnail/.

    Replaces a previous text/plain body shape that openapi-python-client
    could not parse (would silently skip endpoint). See Phase 254 / SDK-01.

    Phase 254 IN-02: ``data_uri`` carries explicit length bounds so
    Pydantic surfaces a 422 with field-level detail (better SDK-consumer
    UX than a generic 400) and the OpenAPI schema documents the limit.
    The router still validates the ``data:image/`` prefix and base64
    encoding; those are content-shape checks Pydantic length cannot
    cover.

    - ``min_length=22``: a minimal valid prefix is ``data:image/x;base64,``
      (20 chars) plus at least one payload byte (e.g.,
      ``data:image/x;base64,XX``). Use 22 as a pragmatic floor that
      rejects empty / clearly-malformed values without false-positives
      on the smallest legitimate payloads.
    - ``max_length=100_000``: matches the previous router-side 100KB cap.
    """

    data_uri: str = Field(min_length=22, max_length=100_000)


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


# ---------------------------------------------------------------------------
# Bulk-delete layers (Phase 1047, milestone exception — PB-03 / PERF-03)
# One additive endpoint permitted per REQUIREMENTS.md Out-of-Scope to reduce
# N sequential DELETEs to one batched call for bulk-delete UX.
# ---------------------------------------------------------------------------


class BulkDeleteLayersRequest(BaseModel):
    """Request body for POST /maps/{map_id}/layers/bulk-delete."""

    layer_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=_MAX_LAYERS_PER_MAP,
        description=(
            "UUIDs of layers to delete. Must be 1–200 elements "
            "(matches _MAX_LAYERS_PER_MAP)."
        ),
    )

    @field_validator("layer_ids")
    @classmethod
    def _no_duplicate_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("layer_ids must be unique")
        return v


class BulkDeleteLayersFailure(BaseModel):
    """A single layer that could not be deleted."""

    id: str
    reason: str


class BulkDeleteLayersResponse(BaseModel):
    """Response body for POST /maps/{map_id}/layers/bulk-delete."""

    deleted: list[str]
    failed: list[BulkDeleteLayersFailure]
