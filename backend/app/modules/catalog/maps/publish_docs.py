"""Published OpenAPI descriptions for the open style dicts on map layers."""

PUBLISHING_GUIDE_URL = (
    "https://docs.getgeolens.com/guides/api/publishing-from-desktop-gis/"
)

LABEL_CONFIG_DESCRIPTION = (
    "Text label configuration. Accepted keys: column, fontSize, textColor, "
    "haloColor, haloWidth, minZoom, maxZoom, placement, textAnchor, "
    "textOpacity, textOffset, allowOverlap. Unknown keys are dropped when the "
    f"map is exported as a MapLibre style. See {PUBLISHING_GUIDE_URL}"
)

STYLE_CONFIG_DESCRIPTION = (
    "Data-driven and builder UI style configuration. Accepted keys: mode, "
    "column, ramp, classCount, method, categories, breaks, colors, target, "
    "sizes, render_mode, symbol, builder, legendLabel, reversed, sizeRange, "
    "sizeLabel, colorLabel, heatmapPaint, savedCirclePaint. Builder-only state "
    "lives under builder, e.g. fill_disabled, stroke_disabled, outline "
    "settings, heatmap metadata, and height_column. Unknown keys are dropped "
    f"when the map is exported as a MapLibre style. See {PUBLISHING_GUIDE_URL}"
)
