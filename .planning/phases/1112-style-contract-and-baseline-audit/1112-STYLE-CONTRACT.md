# Phase 1112 Style Mutation and Reconciliation Contract

## Canonical State

Canonical style state is the saved builder layer model:

- `paint`
- `layout`
- `style_config`
- `label_config`
- `opacity`
- `visible`
- `filter`
- `layer_type`
- `is_dem`

MapLibre layer state is a projection of those fields. Direct MapLibre writes are allowed only inside adapters and map-sync helpers that reconcile live state back to the canonical state.

## Mutation Semantics

| Operation | Meaning | Expected User/API Sources |
|-----------|---------|---------------------------|
| Patch | Merge provided fields into current canonical state; preserve unspecified fields. | Normal style controls, AI `set_style`, opacity, labels, filters, simple builder config edits. |
| Replace | Treat provided object as authoritative for a scoped field; absent owned properties are cleared. | Advanced JSON paint/layout editor, render-as patch paint replacements, reset helpers. |
| Clear | Explicitly unset named owned paint/layout/style properties. | Gradient-to-solid, dashed-to-solid, AI clear lists, mode deactivation. |
| Reset | Restore layer-type defaults and clear inactive-mode owned properties. | Reset style buttons, data-driven clear, render-as return-to-base. |
| Rebuild | Remove/re-add layers or sources only where topology changes require it. | Raster/hillshade switches, cluster source strategy changes, symbol/heatmap/arrow/extrusion companion topology. |

AI `set_style` is a patch by default because the backend tool contract says paint properties are "to set/override" (`backend/app/processing/ai/tools.py:134`). Phase 1115 must add explicit clear/replace semantics to the `ChatAction` path instead of overloading omission.

## Reconciler Contract

Each migrated adapter declares the MapLibre properties it owns for each layer it manages.

The shared reconciler must:

- Filter custom builder metadata and cross-geometry keys before MapLibre calls.
- Set changed owned properties where canonical state has a non-null value.
- Clear owned properties that are absent from canonical state when the operation is replace/reset/clear or when the adapter treats missing owned keys as default/clear.
- Preserve expression-valued arrays by passing the original array through to MapLibre.
- Avoid cloning expressions solely for comparison; value comparison can use existing `paintValueChanged` behavior.
- Swallow and DEV-log MapLibre property errors so one invalid property cannot break the full layer sync.
- Never recreate a source for paint-only changes.

Source-level stickiness is exempt from property clearing. Example: vector `lineMetrics` remains sticky once a shared source is created for line gradients; clearing `line-gradient` does not tear down the source.

## Initial Ownership Inventory

| Adapter/Layer | Owned Paint | Owned Layout | Style/Metadata Inputs |
|---------------|-------------|--------------|-----------------------|
| Line parent | `line-*`, especially `line-color`, `line-width`, `line-opacity`, `line-gradient`, `line-dasharray`, `line-blur`, `line-offset`, `line-gap-width` | `line-cap`, `line-join`, `visibility`, `_minzoom`, `_maxzoom` where applied by helper | `style_config.builder.lineGradient`, arrow render mode |
| Line arrow companion | `icon-color`, `icon-opacity` | `symbol-placement`, `symbol-spacing`, `icon-image`, `icon-size`, icon overlap/alignment, `visibility` | `builder.arrowColor`, `builder.arrowSize`, `builder.arrowSpacing` |
| Fill parent | `fill-*` excluding `fill-extrusion-*`; compounded `fill-opacity`; native `fill-outline-color` suppression | `visibility`, `_minzoom`, `_maxzoom` | `builder.fillDisabled`, `builder.strokeDisabled`, outline builder keys |
| Fill outline companion | `line-color`, `line-width`, `line-opacity` | `visibility`, `_minzoom`, `_maxzoom` | `builder.outlineColor`, `builder.outlineWidth`, stroke-disabled flags |
| Fill extrusion companion | `fill-extrusion-height`, `fill-extrusion-base`, `fill-extrusion-color`, `fill-extrusion-opacity`, `fill-extrusion-vertical-gradient` | zoom range via `setLayerZoomRange`, `visibility` | `builder.heightColumn`, `builder.heightScale`, `builder.extrusionMinZoom`, `builder.extrusionOpacity` |
| Circle parent | `circle-*`, compounded `circle-opacity` | `visibility`, `_minzoom`, `_maxzoom` | data-driven color/radius/width config |
| Heatmap parent | `heatmap-radius`, `heatmap-weight`, `heatmap-intensity`, `heatmap-color`, compounded `heatmap-opacity` | `visibility`, `_minzoom`, `_maxzoom` | `builder.heatmapRamp`, `builder.heatmapWeightColumn` |
| Cluster companions | cluster circle `circle-color`, `circle-opacity`, `circle-stroke-opacity`; count symbol `text-color`, `text-opacity` | count `text-size`, companion visibility | `builder.clusterRadius`, `builder.clusterMaxZoom`, `builder.clusterColor`, `builder.clusterTextColor`, `builder.clusterTextSize` |
| Symbol parent | `icon-opacity`, optional label `text-*` paint | icon layout keys, optional label text layout keys, `visibility` | `style_config.symbol`, `builder.symbol`, `label_config` |
| Raster parent | raster defaults in `RASTER_PAINT_DEFAULTS`, `raster-opacity` | `visibility` | raster tile token/source metadata |
| Hillshade parent | hillshade defaults in `HILLSHADE_PAINT_DEFAULTS` | `visibility` | DEM/raster tile token/source metadata |
| Label companion | `text-color`, `text-halo-color`, `text-halo-width`, `text-opacity` | `text-field`, `text-size`, `symbol-placement`, `text-anchor`, `text-offset`, `text-allow-overlap`, `text-font`, `text-max-width`, zoom range, `visibility` | `label_config` |
| Basemap style layers | changed basemap paint/layout keys only | visibility and order | `basemap_config`, `show_basemap_labels`, `basemap_position` |
| Terrain | MapLibre terrain exaggeration | n/a | `terrain_config.exaggeration`, DEM source binding |

## Compatibility Rules

- Legacy custom paint keys (`_outline-width`, `_outline-color`, `_fill-disabled`, `_stroke-disabled`, `_fill-opacity-saved`, `_outline-width-saved`, `_heatmap-ramp`, `_heatmap-weight-column`, `_height_column`) remain readable but should be normalized into `style_config.builder` where controls already support that path.
- Saved JSON must not include reconciler bookkeeping.
- Viewer/embed should use the same adapter add/sync ownership as builder where possible.
