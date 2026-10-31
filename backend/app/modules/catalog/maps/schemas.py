import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from app.core.edition import is_enterprise
from app.core.text import normalize_nfc as _nfc
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.maps.dashboard import DashboardConfig, DashboardConfigInput
from app.modules.catalog.maps.filter_grammar import validate_filter
from app.modules.catalog.maps.publish_vocabulary import (
    LABEL_CONFIG_DESCRIPTION,
    STYLE_CONFIG_DESCRIPTION,
)
from app.modules.catalog.maps.sharing_policy import (
    SHARE_EXPIRATION_SELECTION_ERROR,
    ShareExpirationPresetDays,
)
from app.modules.catalog.maps.visibility_contract import (
    restricted_map_visibility_opted_in,
)
from app.modules.embed_tokens.schemas import ADVANCED_SHARING_ERROR

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
    "_heatmap-reversed": "heatmap_reversed",
    "_heatmap-weight-column": "heatmap_weight_column",
    "_height_column": "height_column",
    # Raster colormap/stretch builder-private keys (buildColormapTileUrl),
    # kept in style_config.builder so paint stays clean and the round-trip
    # persists across save/reload.
    "_colormap": "colormap",
    "_stretch": "stretch",
    "_pmin": "pmin",
    "_pmax": "pmax",
    "_sigma": "sigma",
    # DEM hypsometric (color-relief) builder-private keys (DEMEditorScene),
    # kept in style_config.builder for the same reason.
    "_hypso-enabled": "hypso_enabled",
    "_hypso-ramp": "hypso_ramp",
    "_hypso-reversed": "hypso_reversed",
}
_STYLE_CONFIG_BUILDER_KEY = "builder"

# The frontend normalizes builder keys to camelCase on layer load, so without
# this rewrite a duplicated layer's POST would persist camelCase while the
# original stays snake_case.
#
# The authoritative alias map. Its inverse (below) is what style_json.py
# imports, so the two can't drift and leak snake_case keys into exported
# style.json.
_BUILDER_CAMEL_TO_SNAKE_KEYS = {
    "fillDisabled": "fill_disabled",
    "strokeDisabled": "stroke_disabled",
    "fillOpacitySaved": "fill_opacity_saved",
    "fillColorSaved": "fill_color_saved",
    "outlineWidthSaved": "outline_width_saved",
    "outlineColor": "outline_color",
    "outlineWidth": "outline_width",
    "heatmapRamp": "heatmap_ramp",
    "heatmapReversed": "heatmap_reversed",
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
    "clusterColorRamp": "cluster_color_ramp",
    "clusterShowCounts": "cluster_show_counts",
    "folderGroupId": "folder_group_id",
    "folderGroupName": "folder_group_name",
    "folderGroupExpanded": "folder_group_expanded",
}

# Derived inverse of the table above, imported by `style_json.py` so export
# can't drift.
BUILDER_SNAKE_TO_CAMEL_KEYS = {
    snake: camel for camel, snake in _BUILDER_CAMEL_TO_SNAKE_KEYS.items()
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
        # If both spellings appear, snake_case wins by being written last
        # (callers pass snake_case as the default; camelCase shows up on
        # duplicates).
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
# How many style-import warnings the summary reports individually before it
# starts counting instead.
_MAX_IMPORT_WARNINGS = 100
# The raw `layers` array isn't the logical layer count: a GeoLens export emits
# up to 4 style layers per logical one (companions), so this bound is
# 4 * _MAX_LAYERS_PER_MAP + 200 headroom.
_MAX_STYLE_DOCUMENT_LAYERS = 4 * _MAX_LAYERS_PER_MAP + 200


def _reject_oversize_json(value: object | None, label: str) -> None:
    """Raise when a JSON value serializes past ``_MAX_STYLE_DICT_BYTES``."""
    if value is None:
        return
    serialized = json.dumps(value, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > _MAX_STYLE_DICT_BYTES:
        raise ValueError(
            f"{label} too large (>{_MAX_STYLE_DICT_BYTES} bytes serialized)"
        )


def _validate_style_dict(v: dict | None) -> dict | None:
    """Reject style-override dicts whose JSON serialization exceeds the cap."""
    _reject_oversize_json(v, "Style configuration")
    return v


def _validate_filter_field(v: list | None) -> list | None:
    """Bound a layer filter's nesting and size, then normalize its grammar.

    `filter` needs its own size cap (the cap above only covers dicts); an
    unbounded filter would store megabytes of JSONB, re-serialized on every
    export and builder load.

    `validate_filter` runs first since it carries the nesting bound;
    size-checking an unbounded filter first would RecursionError instead
    of a Pydantic-catchable ValueError.
    """
    normalized = validate_filter(v)
    _reject_oversize_json(normalized, "Filter expression")
    return normalized


def _validate_maplibre_style_dict(v: dict | None) -> dict | None:
    """Size-cap a paint/layout dict, then shape-check any legacy ``stops``.

    A size cap alone would let a structurally nonsense value
    (``{"fill-pattern": {"stops": 1}}``) persist and later 500 whatever
    serializer descended into it.

    ``stops`` only, and only as a direct property value (not inside an
    expression operand) — the legacy shape (a list of
    ``[input, output]`` pairs) needs no per-property allowlist to check.

    ``style_config`` keeps just the size cap: its own ``stops`` shape
    differs and is never handed to MapLibre. Pre-check rows are bounded
    on read instead, in ``build_maplibre_style``.
    """
    _validate_style_dict(v)
    if v is None:
        return v
    for node in v.values():
        if not isinstance(node, dict) or "stops" not in node:
            continue
        stops = node["stops"]
        if not isinstance(stops, list) or any(
            not isinstance(stop, (list, tuple)) or len(stop) != 2 for stop in stops
        ):
            raise ValueError(
                "Invalid MapLibre style value: 'stops' must be a list of "
                "[input, output] pairs"
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

    Old clients may still submit keys in ``LEGACY_BUILDER_PAINT_KEYS``;
    those are stripped from paint and merged into ``style_config.builder``.
    Unknown underscore-prefixed paint keys stay invalid so private client
    state can't leak into stored paint JSON.
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


class MapVisibility(StrEnum):
    """Who may read a map. A response names `restricted` only to a client
    that sends `X-GeoLens-Map-Visibility: restricted`; any other client
    reads a restricted map as `private`."""

    private = "private"
    internal = "internal"
    public = "public"
    restricted = "restricted"


def _project_map_visibility(value: MapVisibility) -> MapVisibility:
    if value == MapVisibility.restricted and not restricted_map_visibility_opted_in():
        return MapVisibility.private
    return value


ReadMapVisibility = Annotated[
    MapVisibility,
    PlainSerializer(
        _project_map_visibility, return_type=MapVisibility, when_used="json"
    ),
]


class TerrainConfig(BaseModel):
    enabled: bool = Field(default=False)
    source_dataset_id: uuid.UUID | None = Field(default=None)
    # Upper bound matches frontend TERRAIN_EXAGGERATION_MAX (map-sync.ts):
    # the client clamps to [0, 3], so a larger stored value would silently
    # render as 3.
    exaggeration: float = Field(default=1.0, ge=0.0, le=3.0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _enabled_requires_source(self) -> "TerrainConfig":
        # An enabled mesh with no source leaves dangling status text. Coerce
        # to disabled rather than raise, since this model also validates
        # stored JSONB on read (MapResponse).
        if self.enabled and self.source_dataset_id is None:
            self.enabled = False
        return self


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


class BasemapPosition(str, Enum):
    """Whether the basemap renders below ('bottom', default) or above ('top') data layers."""

    bottom = "bottom"
    top = "top"


class BasemapProjection(str, Enum):
    """Map projection. 'mercator' (default) or experimental 'globe'."""

    mercator = "mercator"
    globe = "globe"


# #RRGGBB: exactly 6 hex digits. Rejects names, short/long hex and URI schemes
# ("javascript:", "data:").
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class SublayerOverride(BaseModel):
    """Per-sublayer style override for a single basemap sublayer.

    All fields are nullable — a ``None`` value means "use the basemap default".
    Only ``#RRGGBB`` hex strings are accepted for color fields; ``None`` means
    the basemap default color is preserved.  Numeric ranges are clamped at
    validation time (Pydantic ``ge``/``le`` constraints).

    The key set of ``BasemapConfig.sublayer_overrides`` is treated as opaque
    (forward-compatible with future sublayer IDs).

    Security:
        extra="forbid" locks the scope guardrail: unknown style axes such as
        dash patterns, line caps, halo blur, and text-font are rejected at
        validation time.
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
            "Composes on top of BasemapConfig.opacity (the whole-basemap master "
            "opacity). The rendered opacity is the sublayer override multiplied "
            "by the master opacity."
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
        """Ensure min_zoom <= max_zoom when both are specified.

        MapLibre's behavior with an inverted range is undefined and
        version-dependent — in practice the layer becomes permanently
        invisible until corrected. Reject at validation time to surface it.
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
            "(e.g. 'road', 'boundary', 'building'). The key set is opaque: "
            "a sublayer ID this release does not know is accepted and "
            "stored rather than rejected."
        ),
    )
    basemap_position: BasemapPosition | None = Field(
        default=None,
        description=(
            "Whether the basemap renders above ('top') or below ('bottom', "
            "default) the data layers. null/undefined loads as 'bottom' on "
            "the client."
        ),
    )
    projection: BasemapProjection | None = Field(
        default=None,
        description=(
            "Map projection: 'mercator' (default) or experimental 'globe'. "
            "null/undefined loads as 'mercator' on the client."
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


class LabelPlacement(str, Enum):
    point = "point"
    line = "line"
    line_center = "line-center"


class LabelTextAnchor(str, Enum):
    center = "center"
    top = "top"
    bottom = "bottom"
    left = "left"
    right = "right"
    top_left = "top-left"
    top_right = "top-right"
    bottom_left = "bottom-left"
    bottom_right = "bottom-right"


class LabelConfig(BaseModel):
    """Per-layer text-label configuration.

    The frontend adapters (``label-layer-utils.ts``) read specific camelCase
    fields. This schema gives the editable fields bounds/enums while staying
    forward-compatible:

    * ``model_config = ConfigDict(extra="allow")`` keeps unknown / future keys
      (migration-safe for rows written by older or newer clients);
    * the ``model_serializer`` drops ``None`` values so the stored JSONB shape
      stays minimal and byte-compatible with existing rows — a ``.get(key,
      default)`` lookup in ``style_json._label_layout`` still falls back to its
      default instead of reading a stored ``null`` (backward compatibility).

    Field names intentionally mirror the camelCase storage keys (``fontSize``,
    ``textColor``, ...) so no aliasing is needed and the round-trip is exact.
    ``fontSize``/``textOpacity`` accept either a scalar or a MapLibre zoom
    expression (a list), matching the frontend ``ZoomExpression`` union.
    """

    column: str | None = Field(default=None, max_length=255)
    fontSize: float | list | None = Field(default=None)
    textColor: str | None = Field(default=None, max_length=64)
    haloColor: str | None = Field(default=None, max_length=64)
    haloWidth: float | None = Field(default=None, ge=0.0, le=20.0)
    minZoom: float | None = Field(default=None, ge=0.0, le=24.0)
    maxZoom: float | None = Field(default=None, ge=0.0, le=24.0)
    placement: LabelPlacement | None = Field(default=None)
    textAnchor: LabelTextAnchor | None = Field(default=None)
    textOpacity: float | list | None = Field(default=None)
    textOffset: list | None = Field(default=None)
    allowOverlap: bool | None = Field(default=None)

    model_config = ConfigDict(extra="allow")

    @field_validator("fontSize")
    @classmethod
    def _validate_font_size(cls, v: float | list | None) -> float | list | None:
        # Bound the scalar form; pass MapLibre zoom expressions (lists) through.
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not 0.0 < v <= 512.0:
                raise ValueError("fontSize must be in (0, 512] points")
        return v

    @field_validator("textOpacity")
    @classmethod
    def _validate_text_opacity(cls, v: float | list | None) -> float | list | None:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not 0.0 <= v <= 1.0:
                raise ValueError("textOpacity must be in [0, 1]")
        return v

    @model_serializer(mode="wrap")
    def _serialize_drop_none(self, handler) -> dict:
        # Keep the persisted JSONB minimal: only emit keys the client set
        # (extras included via extra="allow").
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


def _validate_label_config_dict(v: dict | None) -> dict | None:
    """Validate label_config bounds/enums through LabelConfig, return a dict.

    Stays a plain ``dict`` on the wire/storage
    boundary, but every write is validated against ``LabelConfig`` (422 on
    out-of-range/bad-enum values). ``extra="allow"`` plus the None-dropping
    serializer keep unknown keys and the minimal shape, so old rows
    round-trip unchanged.
    """
    if v is None:
        return None
    _validate_style_dict(v)  # 64 KB serialized cap (shared with paint/layout)
    return LabelConfig.model_validate(v).model_dump()


class MapLayerInput(BaseModel):
    # The id lets _replace_layers' by-id reconcile match on PUT. Optional: ids
    # match only against this map's existing layers, so a foreign id can't
    # hijack another map's row.
    id: uuid.UUID | None = Field(
        default=None,
        description="Existing layer id to update in place (full-save reconcile)",
    )
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
        default=None,
        description=(
            "MapLibre layout properties override. `_minzoom` and `_maxzoom` set "
            "the zoom range where the layer is visible; the exported style "
            "writes them as `minzoom` and `maxzoom`."
        ),
    )
    display_name: str | None = Field(
        default=None, max_length=255, description="Label shown in the layer list"
    )
    filter: list | None = Field(default=None, description="MapLibre filter expression")
    label_config: dict | None = Field(
        default=None, description=LABEL_CONFIG_DESCRIPTION
    )
    popup_config: PopupConfig | None = Field(
        default=None,
        description="Popup configuration: {enabled, expression, visible_fields}",
    )
    style_config: dict | None = Field(
        default=None, description=STYLE_CONFIG_DESCRIPTION
    )

    _validate_paint = field_validator("paint")(_validate_maplibre_style_dict)
    _validate_layout = field_validator("layout")(_validate_maplibre_style_dict)
    # Validates label_config bounds/enums via LabelConfig but keeps the stored
    # value a plain dict (see _validate_label_config_dict).
    _validate_label_config = field_validator("label_config")(
        _validate_label_config_dict
    )
    _validate_style_config = field_validator("style_config")(_validate_style_dict)
    # The editable MapLibre filter subset (filter_grammar, shared with style
    # import/export and AI set_filter), plus the size cap the other open
    # columns carry, via _validate_filter_field.
    _validate_filter = field_validator("filter")(_validate_filter_field)
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
        # Store builder keys as snake_case so frontend-normalized camelCase
        # keys don't persist as a second schema (see
        # canonicalize_builder_style_config).
        self.style_config = canonicalize_builder_style_config(self.style_config)
        _validate_maplibre_style_dict(self.paint)
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
        default=None,
        description=(
            "MapLibre layout properties override. `_minzoom` and `_maxzoom` set "
            "the zoom range where the layer is visible."
        ),
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

    _validate_paint = field_validator("paint")(_validate_maplibre_style_dict)
    _validate_layout = field_validator("layout")(_validate_maplibre_style_dict)
    # Validates label_config bounds/enums via LabelConfig but keeps the stored
    # value a plain dict (see _validate_label_config_dict).
    _validate_label_config = field_validator("label_config")(
        _validate_label_config_dict
    )
    _validate_style_config = field_validator("style_config")(_validate_style_dict)
    # The editable MapLibre filter subset (filter_grammar, shared with style
    # import/export and AI set_filter), plus the size cap the other open
    # columns carry, via _validate_filter_field.
    _validate_filter = field_validator("filter")(_validate_filter_field)

    @model_validator(mode="before")
    @classmethod
    def _normalize_paint_boundary(cls, data: Any) -> Any:
        # Must run in before-mode: an after-validator that sets
        # self.paint/style_config unconditionally defeats exclude_unset=True,
        # so a partial patch like {id, visible} would erase stored DEM/builder
        # metadata.
        if not isinstance(data, dict):
            return data
        if "paint" not in data and "style_config" not in data:
            return data
        paint = data.get("paint")
        style_config = data.get("style_config")
        if not isinstance(paint, dict | None) or not isinstance(
            style_config, dict | None
        ):
            # Let field validation reject the wrong type.
            return data
        paint, style_config = split_legacy_builder_paint(paint, style_config)
        # Store builder keys as snake_case so frontend-normalized camelCase
        # keys don't persist as a second schema (see
        # canonicalize_builder_style_config).
        style_config = canonicalize_builder_style_config(style_config)
        data = dict(data)
        if "paint" in data:
            data["paint"] = paint
        # Only materialize style_config when the client sent it or the split
        # moved legacy builder paint keys into it; writing None/{} for an
        # omitted field would turn the patch into an explicit clear.
        if "style_config" in data or style_config:
            data["style_config"] = style_config
        return data


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
    dashboard_config: DashboardConfigInput | None = Field(
        default=None,
        description="The dashboard. Omit to keep it; null removes the widgets you see.",
    )
    visibility: MapVisibility | None = Field(
        default=None,
        description=(
            "private, internal, public or restricted. A map shared with groups "
            "is restricted when it would otherwise be private, so private keeps "
            "it restricted; restricted needs at least one group."
        ),
    )
    layers: list[MapLayerInput] | None = Field(
        default=None,
        max_length=_MAX_LAYERS_PER_MAP,
        description=f"Full replacement layer list (max {_MAX_LAYERS_PER_MAP} layers)",
    )
    plugins: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Enabled plugin IDs, e.g. ['measurement']",
    )
    legend_title: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "Custom map-level legend title. Null or empty leaves the legend "
            "without a heading override. At most 120 characters."
        ),
    )

    @field_validator("legend_title", mode="before")
    @classmethod
    def _normalize_legend_title_nfc(cls, v: str | None) -> str | None:
        return _nfc(v)

    @model_validator(mode="after")
    def _validate_unique_layer_ids(self) -> "MapUpdate":
        # A repeated id would silently collapse entries in the by-id
        # reconcile (the second overwrites the first); mirrors PATCH's
        # duplicate-id rejection.
        if self.layers is not None:
            ids = [layer.id for layer in self.layers if layer.id is not None]
            if len(set(ids)) != len(ids):
                raise ValueError("layer ids must be unique")
        return self


class DatasetMetaKwargs(TypedDict, total=False):
    """Keyword arguments carrying dataset metadata into _build_layer_response."""

    dataset_name: str
    geometry_type: str | None
    table_name: str
    extent: object
    column_info: list | None
    tile_columns: list[str] | None
    feature_count: int | None
    sample_values: dict | None
    record_type: str | None
    is_3d: bool | None
    is_dem: bool | None
    dem_vertical_units: str | None
    band_count: int | None
    tile_version: int | None
    publication_version: int | None
    dataset_visibility: str | None
    dataset_status: str | None
    dataset_attribution: str | None


class MapLayerResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    dataset_geometry_type: str | None
    dataset_table_name: str
    dataset_extent_bbox: list[float] | None
    dataset_column_info: list[dict] | None = Field(
        default=None,
        description=(
            "The dataset's columns, each with its name and type. In a map "
            "response each also carries its current attribute title, semantic "
            "role and value labels when set."
        ),
    )
    dataset_tile_columns: list[str] | None = Field(
        default=None,
        description=(
            "Dataset tile attribute allowlist, used to check cluster filters; "
            "null allows all queryable columns, [] exposes none."
        ),
    )
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
    band_count: int | None = None
    # Dataset content version, the client's `_v=` tile-URL cache-buster
    # (map-sync.ts). Reads Dataset.tile_cache_version (bumped by feature edits,
    # column DDL, tile_columns changes and reupload), not current_version
    # (reupload only), so every content mutation rolls the URL.
    tile_version: int | None = None
    # The counter the signed tile scope binds. The saved-map style document
    # mints tile signatures, so it needs the version the tile route verifies.
    publication_version: int | None = None
    # Dataset visibility/status so the builder can badge a layer whose
    # dataset is hidden from a public/shared map's anonymous audience.
    dataset_visibility: str | None = None
    dataset_status: str | None = None
    # The dataset's required credit line, shown in MapLibre's attribution
    # control alongside the basemap's.
    dataset_attribution: str | None = None

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
    dashboard_config: DashboardConfig | None = None
    visibility: ReadMapVisibility
    thumbnail_url: str | None = None
    og_image_url: str | None = None
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
    plugins: list[str] | None = None
    legend_title: str | None = None
    groups: list[GroupRef] | None = Field(
        default=None,
        description=(
            "The sharing groups the map is shared with, by name. Set on the "
            "detail endpoint for the owner and admins only; null elsewhere."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class MapGroupsUpdate(BaseModel):
    group_ids: list[uuid.UUID] = Field(
        max_length=100,
        description=(
            "Every group the map is shared with afterwards; an empty list "
            "unshares it. An owner may add only groups they belong to, and an "
            "admin any group."
        ),
    )
    confirm: Literal["share_datasets", "map_only"] | None = Field(
        default=None,
        description=(
            "Required when the map would become restricted with layers some "
            "of its new groups can't read; without it the request answers 409 "
            "and lists them. `share_datasets` also shares each such dataset "
            "the caller may share with the groups that lack it; `map_only` "
            "leaves those layers hidden from them."
        ),
    )


class MapLayerAccessGap(BaseModel):
    layer_id: uuid.UUID
    layer_title: str
    dataset_id: uuid.UUID
    dataset_title: str
    group_ids: list[uuid.UUID] = Field(
        description="The map's groups that have a member who can't read it."
    )
    can_share: bool = Field(
        description=(
            "Whether `confirm: share_datasets` would share the dataset with "
            "those groups."
        )
    )


class MapGroupsResponse(BaseModel):
    visibility: ReadMapVisibility = Field(
        description=(
            "The map's visibility after the change: a private map shared with "
            "a group becomes restricted, and a restricted one left with no "
            "group becomes private."
        )
    )
    groups: list[GroupRef] = Field(
        description="The sharing groups the map is shared with, by name."
    )
    shared_dataset_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Datasets this request shared with the map's new groups.",
    )
    hidden_layers: list[MapLayerAccessGap] = Field(
        default_factory=list,
        description=(
            "Layers that some of the map's new groups still can't read; the "
            "same shape a 409 lists under `detail.layers`."
        ),
    )


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
    # A document can carry unboundedly many unmatched sources, each rendered
    # as a DOM node from the 201 response. Keep the first
    # _MAX_IMPORT_WARNINGS and count the rest.
    warnings_truncated: int = Field(
        default=0,
        ge=0,
        description="Warnings produced beyond the reported list",
    )

    def add_warning(self, warning: MapStyleImportWarning) -> None:
        """Record a warning, or count it when the reported list is full."""
        if len(self.warnings) >= _MAX_IMPORT_WARNINGS:
            self.warnings_truncated += 1
            return
        self.warnings.append(warning)


class MapStyleImportResponse(BaseModel):
    map: MapResponse
    summary: MapStyleImportSummary


class MapSpriteEntry(BaseModel):
    """One entry of the MapLibre array-form ``sprite`` ({id, url})."""

    id: str = Field(max_length=255)
    url: str = Field(max_length=2000)


class MapStyleImportRequest(BaseModel):
    """Typed request body for POST /maps/import.

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
    # The spec allows a base-URL string or an array, and GET .../style.json
    # always emits the array, so a string-only field would make exported
    # styles fail import with 422.
    sprite: (
        Annotated[str, StringConstraints(max_length=2000)] | list[MapSpriteEntry] | None
    ) = Field(
        default=None,
        description=(
            "MapLibre sprite: base URL string or array of {id, url} entries "
            "(the array form is what GeoLens style exports emit)"
        ),
    )
    glyphs: str | None = Field(default=None, max_length=2000)
    terrain: dict | None = Field(
        default=None,
        description="MapLibre terrain config (source + exaggeration)",
    )
    # Bounds the raw document before anything walks it. _MAX_LAYERS_PER_MAP
    # here would refuse a large export; the logical limit applies after
    # companion classification.
    layers: list[dict] | None = Field(
        default=None,
        max_length=_MAX_STYLE_DOCUMENT_LAYERS,
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
    visibility: ReadMapVisibility
    thumbnail_url: str | None = None
    # The thumbnail's cache version, apart from the map's edit timestamp.
    # Null for older thumbnails; the card falls back to `updated_at`.
    thumbnail_updated_at: datetime | None = None
    layer_count: int
    has_dashboard: bool = Field(
        default=False,
        description="True when the map shows you at least one dashboard widget.",
    )
    created_by_username: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None

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
    # Dataset content version for the `_v=` tile cache-buster, as on
    # MapLayerResponse.tile_version.
    tile_version: int | None = None
    # As on MapLayerResponse.dataset_attribution. The shared/embed viewer is
    # shown to people outside the instance, where a license's display
    # obligation matters most.
    dataset_attribution: str | None = None
    # As on MapLayerResponse.dataset_extent_bbox: an RFC 7946 bbox, with
    # west > east on an antimeridian crossing.
    dataset_extent_bbox: list[float] | None = None
    dataset_tile_columns: list[str] | None = Field(
        default=None,
        description=(
            "Dataset tile attribute allowlist, as on MapLayerResponse: null "
            "allows all queryable columns, [] exposes none."
        ),
    )


class SharedMapResponse(BaseModel):
    name: str
    description: str | None
    center_lng: float
    center_lat: float
    zoom: float
    has_saved_view: bool = Field(
        description=(
            "True when the map stores a center and zoom. When false, center and "
            "zoom are defaults and a viewer should fit the layers instead."
        ),
    )
    bearing: float
    pitch: float
    basemap_style: str
    show_basemap_labels: bool = True
    basemap_config: BasemapConfig | None = None
    terrain_config: TerrainConfig | None = None
    dashboard_config: DashboardConfig | None = None
    has_non_public_layers: bool = False
    legend_title: str | None = None
    layers: list[SharedLayerResponse]


class ShareTokenRequest(BaseModel):
    # `AwareDatetime`, not `datetime`: Pydantic accepts a naive ISO string,
    # and comparing it to an aware datetime below would raise TypeError (500)
    # instead of a 422.
    expires_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "Expiration timestamp; must carry a UTC offset. Null creates a "
            "non-expiring share link. A custom expiration requires advanced "
            "sharing controls."
        ),
    )
    expires_in_days: ShareExpirationPresetDays | None = Field(
        default=None,
        description=(
            "Server-calculated expiration preset. Choose 1, 7, 30, or 90 days."
        ),
    )

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, v: AwareDatetime | None) -> AwareDatetime | None:
        if v is not None and v < datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v

    @model_validator(mode="after")
    def validate_enterprise_controls(self):
        # The route handlers enforce the edition boundary, but a direct
        # service caller could bypass it, so the schema guards too (as
        # `EmbedTokenCreate` does). ``None`` stays valid: Community can still
        # clear an expiration.
        if self.expires_at is not None and self.expires_in_days is not None:
            raise ValueError(SHARE_EXPIRATION_SELECTION_ERROR)
        if self.expires_at is not None and not is_enterprise():
            raise ValueError(ADVANCED_SHARING_ERROR)
        return self


class ShareTokenResponse(BaseModel):
    token: str = Field(description="Raw token on create, hint on retrieve")
    share_url: str | None = Field(
        default=None, description="Full shareable URL — only returned on create"
    )
    share_url_absolute: str | None = Field(
        default=None, description="share_url on the public app URL; create only"
    )
    viewer_url: str | None = Field(
        default=None, description="The map page on the public app URL"
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
    could not parse (would silently skip endpoint).

    ``data_uri`` carries explicit length bounds so
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


class OgImageUploadRequest(BaseModel):
    """JSON body for PUT /maps/{map_id}/og-image/.

    Accepts a base64 data URI up to 750 KB (as a string). This generous
    ceiling accommodates a 1200x630 JPEG at quality 0.85, which encodes
    to roughly 150-400 KB raw and ~200-540 KB as a base64 string.

    - ``min_length=22``: same floor as ThumbnailUploadRequest — rejects
      empty/clearly-malformed URIs without false-positives.
    - ``max_length=750_000``: ~562 KB decoded — generous for 1200x630 JPEG.
      DO NOT raise ThumbnailUploadRequest.max_length to match this value;
      the 100KB thumbnail cap is a locked contract.
    """

    data_uri: str = Field(min_length=22, max_length=750_000)


class VisibilityCheckResponse(BaseModel):
    non_public_datasets: list[str] = Field(
        description="Titles of datasets not publicly visible"
    )
    has_non_public: bool = Field(
        description="True if any layer references a non-public dataset"
    )
    hidden_from_groups: list[MapLayerAccessGap] = Field(
        default_factory=list,
        description=(
            "On a restricted map, the layers some of its groups can't read, "
            "among those the caller reads. Empty on other maps, and when the "
            "permission authority can't say who reads a dataset."
        ),
    )


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
