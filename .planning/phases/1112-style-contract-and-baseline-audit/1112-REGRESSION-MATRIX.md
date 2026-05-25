# Phase 1112 Stale-Style Regression Matrix

| Flow | Entry Point | Risk | Expected Result |
|------|-------------|------|-----------------|
| Hiking trails gradient -> solid | `LineGradientControls.activateSolid` -> `handlePaintChange`/`handleStyleConfigChange` | Live `line-gradient` remains after canonical paint drops it. | `line-gradient` cleared live; `line-color` visible; saved/reloaded/viewer map is solid. |
| Solid -> gradient -> solid round trip | `LineGradientControls` | Builder gradient metadata and raw expression drift. | Non-canonical expression preserved only for intentional reactivation; solid canonical state has no active `line-gradient`. |
| Dashed -> solid | `LineEditor` layout change -> `handleLayoutChange` | `line-dasharray` is stored in layout but is MapLibre paint; live dashes can survive empty layout. | `line-dasharray` cleared live and absent/default in canonical state. |
| Data-driven color -> flat | `DataDrivenStyleEditor.handleClear` / column clear | Expression paint value survives after style config clears. | Color prop reset to scalar default; style_config data-driven mode cleared. |
| Data-driven size -> flat | `DataDrivenStyleEditor.handleClear` / target changes | `circle-radius` or `line-width` expression survives. | Size prop restored to scalar default for geometry. |
| Categorical -> graduated and back | `DataDrivenStyleEditor.handleModeChange` | Prior expression/class metadata contaminates new mode. | New mode starts from flat default until column selection generates a fresh expression. |
| Fill/stroke toggles | `LayerStyleEditor.handleToggleFill` / `handleToggleStroke` | Native fill outline or outline companion stays visible after stroke disabled. | Parent fill and outline companion visibility/paint reflect builder flags atomically. |
| Polygon extrusion -> fill/stroke | `buildRenderAsPatch` -> `swapLayerOnMap` | `fill-extrusion` companion or height builder keys remain active. | Extrusion layer removed; height/extrusion builder keys cleared unless re-entering extrusion. |
| Fill/stroke -> extrusion | `buildRenderAsPatch` | Missing height defaults or stale opacity/minzoom. | Extrusion companion added with numeric height column, height scale, min zoom, opacity. |
| Heatmap -> point | `handleRenderModeChange` / `buildRenderAsPatch` | Heatmap paint survives on circle layer, labels remain hidden. | Circle paint restored/defaulted; heatmap layer removed; labels restored when configured. |
| Point -> heatmap | `handleRenderModeChange` / `buildRenderAsPatch` | Circle paint properties are applied to heatmap, labels overlap density view. | Heatmap paint only on heatmap layer; labels hidden while heatmap is active. |
| Cluster -> point | `buildRenderAsPatch` and `map-sync` cluster cleanup | Cluster/count companion layers remain. | Cluster companion layers removed; unclustered circle layer remains. |
| Cluster setting change | cluster builder keys -> source signature | Source options drift without tile/source refresh. | Cluster source is refreshed only when cluster source signature changes. |
| Symbol -> point | `buildRenderAsPatch` | Symbol icon/text layout survives on circle layer. | Symbol layer removed/replaced by circle; label companion restored if configured. |
| Label off -> on | `LabelEditor` -> map-sync label branch | Symbol companion remains after config clear or misses zoom/layout resets on re-enable. | Label layer removed when off; rebuilt/synced from `label_config` when on. |
| Raster band/color reset | `RasterLayerControls` -> `rasterAdapter.syncPaint` | Old raster paint props survive after reset. | Raster owned props reset to defaults or supported current values. |
| DEM hillshade -> image | `buildRenderAsPatch` -> raster/hillshade adapters | Hillshade paint/source type survives on raster image. | Raster/hillshade source/layer rebuilt only as needed; stale hillshade props not persisted as active image style. |
| Terrain exaggeration change | `TerrainControls` and terrain sync | Exaggeration outside sane bounds distorts map. | Exaggeration normalized to 0-3 before applying/persisting. |
| Basemap color/visibility overrides | `applyBasemapConfigToMap` | Data layer reconciler clears basemap style keys or basemap changes clear data keys. | Basemap mutations remain isolated to basemap layers; data adapter ownership ignores basemap layers. |
| AI `set_style` color patch | `ChatPanel.handleChatAction` | Paint object replaces full canonical paint, dropping unrelated width/opacity/config. | Patch preserves unspecified paint; live reconciler updates changed key only. |
| AI `set_style` clear gradient | future clear field/action | LLM cannot intentionally clear stale properties. | AI action explicitly clears owned key; undo restores through same reconciler path. |
| AI data-driven -> solid | `set_data_driven_style` plus clear/reset | Backend action lacks clear semantics for reverting modes. | Full data-driven actions replace intended paint/config; clear/reset path documented and tested. |
| Chat undo | `ChatPanel.handleUndo` | Undo uses mixed paint/style calls and can resurrect stale live properties. | Undo restores canonical snapshot through reconciler semantics. |
| Save/reload | `useBuilderSave.buildLayerDiff` | Persisted JSON omits/keeps stale keys inconsistently with live map. | Saved JSON matches canonical reconciled state; reload does not resurrect stale properties. |
| Public/embed viewer | `ViewerMap` -> adapters | Viewer renders differently because builder-only live clears were not persisted. | Viewer renders canonical saved styles with same adapter ownership. |
| Style JSON export/import | style spec/debug/export paths | Invalid stale keys leak across import/export. | Import/export remains compatible and sanitizes or rejects invalid stale keys consistently. |
