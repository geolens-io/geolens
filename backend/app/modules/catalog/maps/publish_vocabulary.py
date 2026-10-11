"""Style vocabulary accepted from map publishers, and its published descriptions.

The sets are the single definition behind the style sanitizers and the OpenAPI
descriptions of ``MapLayerInput``, so the documented keys cannot drift from the
keys that survive a style export.
"""

PUBLISHING_GUIDE_URL = (
    "https://docs.getgeolens.com/guides/api/publishing-from-desktop-gis/"
)

LABEL_METADATA_KEYS = frozenset(
    {
        "column",
        "fontSize",
        "textColor",
        "haloColor",
        "haloWidth",
        "minZoom",
        "maxZoom",
        "placement",
        "textAnchor",
        "textOpacity",
        "textOffset",
        "allowOverlap",
    }
)

STYLE_METADATA_KEYS = frozenset(
    {
        "mode",
        "column",
        "ramp",
        "classCount",
        "method",
        "categories",
        "breaks",
        "colors",
        "target",
        "sizes",
        "render_mode",
        "symbol",
        "builder",
        "legendLabel",
        "reversed",
        "sizeRange",
        "sizeLabel",
        "colorLabel",
        "heatmapPaint",
        "savedCirclePaint",
    }
)

SYMBOL_METADATA_KEYS = frozenset(
    {
        "iconImage",
        "iconSize",
        "iconRotation",
        "iconAnchor",
        "iconOffset",
        "categoryColumn",
        "categories",
    }
)

# Spellings as stored. Writes also accept the camelCase aliases of the
# snake_case keys; lineGradient and symbol are stored as written.
BUILDER_STYLE_KEYS = frozenset(
    {
        "fill_disabled",
        "stroke_disabled",
        "fill_opacity_saved",
        "fill_color_saved",
        "outline_width_saved",
        "outline_color",
        "outline_width",
        "heatmap_ramp",
        "heatmap_reversed",
        "heatmap_weight_column",
        "height_column",
        "height_scale",
        "extrusion_min_zoom",
        "extrusion_opacity",
        "arrow_color",
        "arrow_size",
        "arrow_spacing",
        "cluster_radius",
        "cluster_max_zoom",
        "cluster_color",
        "cluster_text_color",
        "cluster_text_size",
        "cluster_color_ramp",
        "cluster_show_counts",
        "folder_group_id",
        "folder_group_name",
        "folder_group_expanded",
        "colormap",
        "stretch",
        "pmin",
        "pmax",
        "sigma",
        "hypso_enabled",
        "hypso_ramp",
        "hypso_reversed",
        "lineGradient",
        "symbol",
    }
)


def _listed(keys: frozenset[str]) -> str:
    return ", ".join(sorted(keys))


LABEL_CONFIG_DESCRIPTION = (
    f"Text label configuration. Accepted keys: {_listed(LABEL_METADATA_KEYS)}. "
    "Unknown keys are dropped when the map is exported as a MapLibre style. "
    f"See {PUBLISHING_GUIDE_URL}"
)

STYLE_CONFIG_DESCRIPTION = (
    "Data-driven and builder UI style configuration. Accepted keys: "
    f"{_listed(STYLE_METADATA_KEYS)}. Builder-only state lives under builder, "
    f"with keys {_listed(BUILDER_STYLE_KEYS)}. Unknown keys are dropped when "
    f"the map is exported as a MapLibre style. See {PUBLISHING_GUIDE_URL}"
)
