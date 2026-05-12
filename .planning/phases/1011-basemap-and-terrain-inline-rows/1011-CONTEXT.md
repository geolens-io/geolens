# Phase 1011: Basemap and terrain inline rows - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 requirements, Phase 1009 sidebar row UI, Phase 1010 row actions

<domain>
## Phase Boundary

Phase 1011 moves basemap and terrain affordances into the stack IA while preserving the existing map-level storage model. It must not introduce persisted basemap sublayers, persisted groups, new terrain layer fields, or any backend migrations.

The phase owns BASE-01..04 and TERRAIN-01..02:
- The basemap group shows one current-basemap row named from the existing `BasemapEntry` registry.
- Basemap controls write only `basemap_style`, `show_basemap_labels`, and normalized `basemap_config`.
- Basemap swap uses enabled `BasemapEntry` entries and reset uses the existing normalization defaults.
- Terrain source/enabled/exaggeration live in the `relief` group and write only `terrain_config`.
- Raster DEM rows expose `Use as terrain`, setting `terrain_config.source_dataset_id` from the layer's `dataset_id`.
</domain>

<current_state>
## Current Code Shape

- `buildMapStack` already derives `surface`, `relief`, `basemap`, `data`, `labels`, and `interactions` groups over existing saved-map fields.
- `makeBasemapEntries` creates a single `basemap-preset` entry, but its title is the generic "Basemap preset" rather than the registry label.
- `MapStackPanel` currently renders `BasemapPicker` and `BasemapAppearanceControls` as a separate basemap panel beneath the row.
- `TerrainControls` currently renders in the `surface` group, while the v1002 IA wants terrain surfaced inline in `relief`.
- Primary layer row overflow already supports row-scoped actions and can host a DEM-only `Use as terrain` item.
</current_state>

<decisions>
## Implementation Decisions

### Basemap Row
- Keep the existing `basemap-preset` stack entry; extend map-stack input with an optional derived `basemap_label`.
- Resolve the current basemap label in `MapStackPanel` from `useBasemaps` plus the existing blank basemap entry.
- Render swap/reset/sublayer controls directly under the basemap row in the `basemap` group, using existing UI primitives.

### Terrain Row
- Move the terrain stack entry from `surface` to `relief` by deriving it before DEM visual relief entries.
- Reuse `TerrainControls` in the `relief` group for map-level source/enabled/exaggeration writes.
- Keep the underlying `terrain_config` handler shape unchanged.

### DEM Row Action
- Add an optional `onUseAsTerrain` handler to `MapStackItem`/`MapStackPanel`.
- Show `Use as terrain` only for primary raster DEM rows.
- Invoke `onTerrainChange` with an updated `terrain_config`, leaving the layer itself untouched.
</decisions>

<specifics>
## Specific Ideas

- Swap should call `onBasemapChange(nextId)` and immediately normalize/write the current config through `normalizeBasemapConfig`.
- Reset should write `normalizeBasemapConfig(null, true)` and restore `show_basemap_labels` to true.
- Tests should assert the basemap row label, swap/reset handlers, terrain row group placement, relief controls, and DEM-only action routing.
</specifics>

<deferred>
## Deferred Ideas

- Saved basemap presets remain punted from v1.
- Add Dataset modal basemap swap states belong to Phase 1012.
- Browser-level visual validation remains part of Phase 1013 unless Phase 1011 surfaces a component issue that requires Playwright.
</deferred>

---

*Phase: 1011-basemap-and-terrain-inline-rows*
*Context gathered: 2026-05-12 from current code and scoped handoff*
