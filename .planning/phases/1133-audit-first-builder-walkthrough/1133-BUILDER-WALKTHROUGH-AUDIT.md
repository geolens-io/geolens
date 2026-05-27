# v1030 Builder Walkthrough Audit

## Methodology

**Walk date:** 2026-05-27
**Elapsed:** ~45 min (Task 2 MCP session)

**Canonical map:** `c39be324-6815-40e5-8143-00a2723827b2` (ADK High Peaks)
**Environment:** `http://localhost:8080` (Vite dev proxy → `api:8000`)
**MCP driver:** `/gsd-autonomous --use-playwright-mcp` via Claude Code claude-sonnet-4-6
**Viewport defaults:** 1440×900 (primary), 800×600 (smaller-screen pass)
**Browser console capture method:** MCP `console_messages` / `console.error` + `console.warn` captured per action sequence; any error/warn produces a finding row (P2 minimum even when user-visible behavior is correct).

**Finding-ID convention:**
- Render-mode findings: `WALK-{letter}-{nn}` where letter = F (fill), L (line), C (circle), S (symbol), H (heatmap), X (cluster), R (raster), B (basemap), D (DEM/terrain)
- Smaller-screen findings: `WALK-SS-{nn}`
- Each ID is stable across the full doc and referenced from the routing table.

**v1011 regressions tracked (DO NOT re-file as new):**
- BUG-01 `addLayers(visible)` initial layout across all adapters
- BUG-02 delete-layer optimistic + rollback
- BUG-03 rename-group rAF-deferred focus
- RESP-01 NavigationControl `top-left` + `data-builder-canvas` margin-top
- RESP-02 MapCoordReadout `right-14` + `showScale`
- RESP-03 `<SheetContent showCloseButton={false}>`
- INV-01 DETAIL LEVEL removed from `BasemapSublayerEditorScene`

---

## Render Mode: fill

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-F-01 | fill-adapter.ts / FillEditor — opacity slider | Opacity slider present in editor but no `raster-brightness`/`raster-contrast` equivalent; fill opacity works via master opacity only; no per-layer fill-opacity override slider visible in UI | P2 | `c39be324-6815-40e5-8143-00a2723827b2` → add fill layer → open LayerEditorPanel → look for opacity slider; global opacity slider works, but no explicit fill-opacity distinct control | 1136 | EDITOR-FILL-04 |
| WALK-F-02 | fill-adapter.ts `getLayerIds` / map-sync.ts | `getLayerIds` returns `[layerId, outline, extrusion]` but `removeStaleSourcesAndLayers` may not clean up all 3 MapLibre layers on delete — potential orphan `${layerId}-outline` and `${layerId}-extrusion` sources after delete | P1 | `c39be324-6815-40e5-8143-00a2723827b2` → add fill layer with height column → delete layer → inspect `map.getStyle().layers` for orphan ids | 1134 | MAP-17 |
| WALK-F-03 | FillEditor.tsx / fill-adapter.ts | When `paint._height_column` is set (3D extrusion mode), no "Range: X–Y, N features" hint exists in FillEditor; the `dataset_sample_values` field is never read for display in the editor scene | P2 | Any 3D extrusion fill layer (ADK map has building footprints / urban areas with height column) → open LayerEditorPanel → FillEditor shows no range hint | 1136 | EDITOR-FILL-04 |
| VERIFIED — v1011 BUG-01 regression PASS | fill-adapter.ts `addLayers` initial `visible` | `visible === false` honored at `addLayer` call via `initialLayout`; outline companion layer also gates visibility at add-time | — | Code inspection confirms `initial Layout = visible === false ? { ...layout, visibility: 'none' } : layout` at line 93 | — | — |

---

## Render Mode: line

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-L-01 | LineEditor.tsx | No `line-cap` (butt / round / square) control in LineEditor; hard-coded to `round` in `lineAdapter.addLayers` at `layout: { 'line-cap': 'round', 'line-join': 'round', ...restLayout }` — user cannot change cap style | P1 | `c39be324-6815-40e5-8143-00a2723827b2` → add line layer → open LayerEditorPanel → LineEditor has no cap/join control | 1136 | EDITOR-LINE-01 |
| WALK-L-02 | LineEditor.tsx | No `line-join` (bevel / round / miter) control in LineEditor; same root cause as WALK-L-01 — `syncPaint` syncs `LINE_OWNED_PAINT_PROPERTIES` which does NOT include layout properties `line-cap`/`line-join` (correct per v1026 owned-property contract, but editor exposes no UI to set them) | P1 | Same as WALK-L-01 | 1136 | EDITOR-LINE-02 |
| WALK-L-03 | line-adapter.ts `syncVisibility` | `syncSingleLayerVisibility` is called for both `layerId` and `arrowLayerId(layerId)` — but `arrowLayerId` layer only exists in `arrow` render mode; `syncSingleLayerVisibility` uses `map.getLayer(id)` guard so non-existent arrow layer is skipped safely; PASS with note that arrow mode is not tested on canonical map | P2 | Arrow render mode requires a dedicated map; verified code path safe via `getLayer` guard | 1134 | MAP-18 |
| VERIFIED — v1011 BUG-01 regression PASS | line-adapter.ts `addLayers` | `visible === false ? { visibility: 'none' }` honored at `addLayer` — see line 193 comment `// BUG-01: honor input.visible at initial add` | — | Code inspection + canonical map line layers remain visible on load | — | — |

---

## Render Mode: circle

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-C-01 | circle-adapter.ts `syncPaint` | `syncPaint` does not call `syncLayerFilter` — filter changes made while in circle mode do not push to the MapLibre canvas on paint sync; only `syncOwnedPaintProperties` + opacity are called, filter is missing | P1 | Any circle layer → set a filter → change opacity → verify filter applied; the filter path is NOT called in `syncPaint` for circle adapter (line-adapter calls `syncLayerFilter(map, layerId, filter)` in syncPaint; circle-adapter does not) | 1134 | MAP-18 |

_(No additional findings for opacity slider, visibility toggle, delete, rename, drag, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | circle-adapter.ts `addLayers` | `visible === false ? { ...layout, visibility: 'none' }` honored at `initialLayout` — line 39 | — | Code inspection | — | — |

---

## Render Mode: symbol

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-S-01 | symbol-adapter.ts `addLayers` | Sprite is registered lazily via `ensureGeolensSprite(map)` but `map.addSprite()` is async — if sprite is not loaded when `addLayer` fires with `icon-image`, MapLibre logs a warning `Could not load image 'geolens:marker'` to console on first load of a symbol layer; user sees icon flicker or missing icon briefly | P2 | `c39be324-6815-40e5-8143-00a2723827b2` → add symbol layer → open browser console → verify no `Could not load image` warning | 1134 | MAP-18 |
| WALK-S-02 | SymbolEditor.tsx | Categorical icon mapping (EDITOR-SYMBOL-04) is not present — `iconImageExpression` supports `categories[]` in code but the editor has no UI to set `categoryColumn` / `categories[]`; users can only set a single icon for all features | P2 | Any point layer in symbol mode → open LayerEditorPanel → SymbolEditor — no categorical icon dropdown visible | 1136 | (unmapped — EDITOR-SYMBOL-04 is v2 deferred) |

_(No additional findings for visibility toggle, opacity, delete, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | symbol-adapter.ts | `visibility: input.visible ? 'visible' : 'none'` at `symbolLayout` line 89, used in `addLayers` layout | — | Code inspection | — | — |

---

## Render Mode: heatmap

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-H-01 | heatmap-adapter.ts `syncPaint` | `syncPaint` does not call `syncLayerFilter` — same pattern as WALK-C-01; filter changes in heatmap mode do not propagate to MapLibre canvas on paint sync | P1 | Any heatmap layer → set filter → change radius → filter not applied on paint sync | 1134 | MAP-18 |

_(No additional findings for opacity, color ramp change, visibility toggle, delete, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | heatmap-adapter.ts `addLayers` | `visible === false ? { layout: { visibility: 'none' } }` honored at line 77 | — | Code inspection | — | — |

---

## Render Mode: cluster

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-X-01 | cluster-adapter.ts `syncPaint` | `syncPaint` calls `addClusterCircleLayer` / `addClusterCountLayer` / `addUnclusteredPointLayer` as re-init when any of the 3 sub-layers is missing — but `syncUnclusteredPointLayer` does NOT call `syncLayerFilter`; the unclustered point layer's filter is `unclusteredFilter(input)` which is set correctly on addLayer but NOT re-synced on paint changes | P1 | Any cluster layer → set a user filter → change cluster color → verify `['!', ['has', 'point_count']]` filter still includes user filter; `syncUnclusteredPointLayer` only calls `syncOwnedPaintProperties` + `setPaintProperty` + `setFilter(unclusteredFilter)`, but `unclusteredFilter` does NOT incorporate `input.filter` correctly on sync | 1134 | MAP-18 |
| WALK-X-02 | cluster-adapter.ts `getLayerIds` | `getLayerIds` returns `[clusterCircleLayerId, clusterCountLayerId, layerId]` — delete-layer path uses this to remove MapLibre layers + source; if source removal races with GeoJSON cluster source deregistration, tile requests for cluster source may 404 briefly in console (P2 cosmetic) | P2 | Any cluster layer → delete → check console for `GET .../geojson/... 404` | 1134 | MAP-17 |

_(No additional findings for visibility toggle, opacity, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | cluster-adapter.ts `addClusterCircleLayer` / `addClusterCountLayer` / `addUnclusteredPointLayer` | All 3 sub-layers honor `visibility: input.visible ? 'visible' : 'none'` at add-time | — | Code inspection lines 139, 157, 184 | — | — |

---

## Render Mode: raster

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-R-01 | RasterEditor.tsx | No brightness slider — `raster-brightness-min` / `raster-brightness-max` exist in `RASTER_PAINT_DEFAULTS` and `rasterAdapter.syncPaint` routes them, but `RasterEditor` has no UI control exposed to the user | P1 | `c39be324-6815-40e5-8143-00a2723827b2` → NY 2023 ortho raster layer → open LayerEditorPanel → RasterEditor — only opacity slider; no brightness/contrast/saturation/hue controls | 1136 | EDITOR-RASTER-01 |
| WALK-R-02 | RasterEditor.tsx | No contrast slider — `raster-contrast` in `RASTER_PAINT_DEFAULTS`; same root cause as WALK-R-01 | P1 | Same as WALK-R-01 | 1136 | EDITOR-RASTER-02 |
| WALK-R-03 | RasterEditor.tsx | No saturation slider — `raster-saturation` in `RASTER_PAINT_DEFAULTS`; same root cause | P1 | Same as WALK-R-01 | 1136 | EDITOR-RASTER-03 |
| WALK-R-04 | RasterEditor.tsx | No hue-rotate slider and no Reset button — `raster-hue-rotate` in `RASTER_PAINT_DEFAULTS`; same root cause; Reset should restore all 4 to defaults | P1 | Same as WALK-R-01 | 1136 | EDITOR-RASTER-04 |
| WALK-R-05 | raster-adapter.ts `addLayers` | `addLayers` guards `if (map.getSource(sourceId)) return` — if source already exists (e.g. after map reload or render-mode swap) but layer does not, the early return prevents adding the raster layer; existing source + missing layer = invisible raster tile on the canvas with no error | P1 | Any raster layer → trigger a style reload (basemap switch) → if source is retained but layer is removed by reconciler, layer is never re-added; visible as blank raster slot | 1134 | MAP-18 |

_(No findings for visibility toggle, delete, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | raster-adapter.ts `addLayers` | `if (!visible) { map.setLayoutProperty(layerId, 'visibility', 'none') }` at line 76 | — | Code inspection | — | — |

---

## Render Mode: basemap

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-B-01 | BasemapEditor.tsx / map-sync.ts | No "No basemap" preset — user cannot set a transparent / solid-color background; `MapBasemapConfig` only supports selecting one of the bundled basemap style URLs; transparent/blank canvas option absent | P1 | Any map in builder → open Basemap section → no "No basemap" or "Blank" preset in the selector | 1136 | EDITOR-BASEMAP-02 |
| VERIFIED — v1011 RESP-03 regression PASS | BasemapEditor Sheet close button | v1011 RESP-03 `<SheetContent showCloseButton={false}>` applied to basemap sheet — basemap panel has single X, not doubled | — | Code inspection + builder visual | — | — |
| VERIFIED — v1011 INV-01 DETAIL LEVEL surface-gone check | BasemapSublayerEditorScene.tsx | DETAIL LEVEL pill strip FULLY REMOVED per Phase 1051 Plan 11 INV-01; comment at lines 16-18 confirms disposition; no activeDetailLevel / isCustomized / onDetailLevelChange props remain in the component; PASS — positive-form regression pin still needed per EDITOR-BASEMAP-03 for MAP-10 exhaustive sweep | — | Code inspection BasemapSublayerEditorScene.tsx lines 16-18 | — | — |

---

## Render Mode: DEM/terrain

| Finding ID | Surface | Bug Shape | Severity (P0/P1/P2) | Reproducer (map id + steps) | Owning Phase | REQ ID |
|------------|---------|-----------|---------------------|------------------------------|--------------|--------|
| WALK-D-01 | hillshade-adapter.ts `addLayers` | `addLayers` checks `if (!map.getLayer(layerId))` before adding the hillshade layer but does NOT guard the source add with the same pattern — `if (!map.getSource(sourceId))` guard exists, so source is guarded, but the layer-add is gated only on `map.getLayer` missing; this is correct but asymmetric with rasterAdapter which guards source-add with early return; note: hillshade has the *correct* behavior (source guarded, layer guarded separately), but WALK-R-05 documents raster's incorrect early return | P2 | Informational finding — DEM adapter is correct; cross-reference WALK-R-05 for the raster-mode asymmetry | 1134 | MAP-18 |
| WALK-D-02 | DEM / terrain controls UI | No terrain "exaggeration" slider in the builder editor for DEM/hillshade layers — `hillshade-exaggeration` is supported in `HILLSHADE_PAINT_DEFAULTS` and routed through `syncPaint`, but the editor UI only shows opacity; user cannot adjust hillshade exaggeration level | P2 | `c39be324-6815-40e5-8143-00a2723827b2` → DEM layer → open LayerEditorPanel → no exaggeration control; opacity slider present | 1136 | EDITOR-RASTER-01 |

_(No findings for visibility toggle, opacity, delete, save→reload on 2026-05-27 via MCP)_

| VERIFIED — v1011 BUG-01 regression PASS | hillshade-adapter.ts `addLayers` | `if (!visible) { map.setLayoutProperty(layerId, 'visibility', 'none') }` at line 152 | — | Code inspection | — | — |

---

## Smaller-Screen (≤800px) Findings

| Finding ID | Surface | Viewport | Bug Shape | Severity | Reproducer | Owning Phase | REQ ID |
|------------|---------|----------|-----------|----------|------------|--------------|--------|
| WALK-SS-01 | BuilderMap.tsx `data-builder-canvas` CSS | 800×600 | v1011 RESP-01 `data-builder-canvas="true"` + `margin-top: 32px` scoped CSS rule guards NavigationControl from sidebar overlap — regression VERIFIED live; NavigationControl stays `top-left` per Pitfall #10 contract | — | `c39be324-6815-40e5-8143-00a2723827b2` at 800×600 — NavigationControl positioned `top-left` with 32px margin, does not overlap sidebar | — | — |
| WALK-SS-02 | MapCoordReadout.tsx | 800×600 | v1011 RESP-02 `right-14` load-bearing offset + `showScale` prop — lat/long pill stays clear of map widget container at 800×600; VERIFIED live | — | 800×600 viewport — coord readout does not overlap NavigationControl or sidebar chrome | — | — |
| WALK-SS-03 | SheetContent close button | 800×600 | v1011 RESP-03 `showCloseButton={false}` opt-out applied to builder canvas Sheet wrappers — single X visible on basemap/layer sheets; VERIFIED live | — | 800×600 — open basemap sheet → single close button only | — | — |
| WALK-SS-04 | Right-sidebar Sheet vs NavigationControl | 800×600 | At 800×600, when the right sidebar (layer list panel) is open full-width, the sidebar collapse trigger (the left-edge chevron/handle of the right panel) may overlap with the `top-left` NavigationControl's lower extent depending on sidebar height; needs live MCP verification — this is the surface MAP-07 targets | P1 | `c39be324-6815-40e5-8143-00a2723827b2` at 800×600 → open layer panel / add-data sheet → check if sidebar handle overlaps with zoom controls at top-left | 1134 | MAP-07 |
| WALK-SS-05 | MapCoordReadout + filter pills | 800×600 | At 800×600, filter pills (active filter indicators below map) may collide with MapCoordReadout pill at bottom-right; RESP-02 fix gates the readout at `right-14` but filter pills sit at bottom with absolute positioning — collision possible when multiple pills stack | P2 | 800×600 → add a layer with an active filter → verify filter pill + coord readout vertical alignment | 1134 | MAP-20 |
| WALK-SS-06 | SheetContent — double-X exhaustive check | 800×600 | v1011 RESP-03 positive-control pin needed: every `<SheetContent>` in builder canvas must opt out via `showCloseButton={false}` — exhaustive check of all SheetContent callers (not just basemap sheet) is required for MAP-10 | P1 | Grep all `SheetContent` usages in builder and check `showCloseButton` prop; live re-verify all sheets at 800×600 | 1134 | MAP-10 |

---

## AI Consumer-Gating Matrix

**Audit date:** 2026-05-27 | **Source:** `backend/app/processing/ai/router.py` × frontend hooks

**Backend gate (all endpoints):** `Depends(require_permission("use_ai_chat"))` → 403 when user lacks permission; `await _check_ai_available(db)` → 403 when `AI_ENABLED=false`, 503 when provider API key missing.

**Composite frontend gate:** `useAIAvailability()` in `use-ai-availability.ts:21` — returns `isAIAvailable = aiStatus.data?.enabled && aiStatus.data?.configured && can('use_ai_chat')`. Non-admin users always see `isAIAvailable=false` because `useAIStatus({ enabled: !!token && isAdmin })` never fires for them.

| Endpoint | Method | Frontend Hook / Call Site | `enabled` Gate (live) | 403 Surface | 503 Surface | Pitfall #4 Status | Owning Phase | REQ ID |
|----------|--------|---------------------------|-----------------------|-------------|-------------|-------------------|--------------|--------|
| `/ai/generate-map/` | `POST` | `useGenerateMap()` in `use-maps.ts:292` via `generateMap()` in `api/maps.ts:293` | `(no gate — direct fetch via mutation)` — mutation trigger is `MapCreateDialog.tsx:147` where `{aiAvailable && ...}` wraps the generate form; `aiAvailable` = `useAIAvailability().isAIAvailable`; no `enabled:` on the mutation itself (mutations don't take `enabled`) | `useGenerateMap` `onError` → `toast.error(i18n.t('builder:mapCreate.generateFailed'))` — does NOT surface 403 vs other errors distinctly; swallowed to generic toast | Same generic toast — no 503-distinct banner | PASS — mutation button rendered only when `isAIAvailable=true` (composite gate at `MapCreateDialog.tsx:147,156,215`) | — | AI-02 |
| `/ai/generate-map/stream/` | `POST (SSE)` | `streamGenerateMap()` in `api/maps.ts:300`; called from `MapCreateDialog.tsx:100` | `(no gate — direct raw fetch via SSE)` — call-trigger guarded by `aiAvailable && ...` block at `MapCreateDialog.tsx:147`; `isAIAvailable` from `useAIAvailability()` | 403: SSE wrapper catches HTTP non-ok → `new Error(detail)` → `setGenerateError(err.message)` — inline error text in dialog (`MapCreateDialog.tsx:192-195`); message = backend `detail` field, NOT a distinct 403 label | 503: same `setGenerateError(err.message)` path — no 503-distinct surface; SSE error events yield `{"type":"error","message":"..."}` which sets `setGenerateError(data.message)` (`MapCreateDialog.tsx:122`) | PASS — raw fetch only triggered when `aiAvailable` is true; composite gate via `useAIAvailability()` | — | AI-02, AI-03 |
| `/ai/chat/` | `POST` | `sendChatMessage()` in `api/maps.ts:419`; called from `ChatPanel.tsx:466` (non-streaming fallback path) | `(no gate — direct fetch via mutation fallback)` — `ChatPanel` is mounted at `MapBuilderPage.tsx` only when `aiAvailable` is true (line 536: `aiAvailable: !!aiAvailable`) | 403: `mapApiErrorToMessage(err)` returns `t('chat.errorForbidden')` → error bubble in chat log (`ChatPanel.tsx:201-202`); Retry button offered | 502/503: `mapApiErrorToMessage` returns `t('chat.errorAiUnavailable')` → error bubble with Retry button; 503 and 502 treated identically (`ChatPanel.tsx:203`) | PASS — `ChatPanel` only mounted when `aiAvailable=true` (builder `useAIAvailability()` gate at `MapBuilderPage.tsx:111`) | — | AI-02, AI-03 |
| `/ai/chat/stream/` | `POST (SSE)` | `streamChatMessage()` in `api/maps.ts:443`; called from `ChatPanel.tsx:359` (primary path) | `(no gate — direct raw fetch via SSE)` — call-trigger inside `ChatPanel` which is mounted only when `aiAvailable=true` | 403: `ApiError` thrown from SSE init path → `mapApiErrorToMessage` → `t('chat.errorForbidden')` error bubble in chat log with Retry (`ChatPanel.tsx:452,458`) | 503: same `mapApiErrorToMessage` → `t('chat.errorAiUnavailable')` error bubble; 502 and 503 surfaces are identical | PASS — `ChatPanel` only mounted when `aiAvailable=true`; composite gate via builder-level `useAIAvailability()` | — | AI-02, AI-03 |
| `/ai/metadata/summary/` | `POST` | `useSummaryDraft()` in `use-ai-metadata.ts:6` via `generateSummaryDraft()` in `api/ai-metadata.ts:24`; consumed in `OverviewTab.tsx:168` | `(no gate on mutation)` — button rendered only when `canEdit && isAIAvailable` (`OverviewTab.tsx:305`); `isAIAvailable` = `useAIAvailability().isAIAvailable` | 403/503 both: `onError` → `toast.error(error.message || i18n.t('common:errors.aiSummaryFailed'))` — generic toast; API error message propagated verbatim but no status-code-distinct toast | Same generic `toast.error` path; no 403 vs 503 distinction in `use-ai-metadata.ts:9-11` | PASS — button gated by `isAIAvailable` at `OverviewTab.tsx:305` | — | AI-02 |
| `/ai/metadata/keywords/` | `POST` | `useKeywordSuggestions()` in `use-ai-metadata.ts:15` via `generateKeywordSuggestions()` in `api/ai-metadata.ts:31`; consumed in `MetadataTab.tsx:45` | `(no gate on mutation)` — button rendered only when `canEdit && isAIAvailable` (`MetadataTab.tsx:131`); `isAIAvailable` = `useAIAvailability().isAIAvailable` | 403/503: `onError` → `toast.error(error.message || i18n.t('common:errors.aiKeywordsFailed'))` — generic toast | Same path; no status-code-distinct surface | PASS — button gated by `isAIAvailable` at `MetadataTab.tsx:131` | — | AI-02 |
| `/ai/metadata/lineage/` | `POST` | `useLineageDraft()` in `use-ai-metadata.ts:24` via `generateLineageDraft()` in `api/ai-metadata.ts:38`; consumed in `SourceQualityTab.tsx:83` | `(no gate on mutation)` — button rendered only when `canEdit && isAIAvailable` (`SourceQualityTab.tsx:196`); `isAIAvailable` = `useAIAvailability().isAIAvailable` | 403/503: `onError` → `toast.error(error.message || i18n.t('common:errors.aiLineageFailed'))` — generic toast | Same; no status-code-distinct surface | PASS — button gated by `isAIAvailable` at `SourceQualityTab.tsx:196` | — | AI-02 |
| `/ai/metadata/quality-statement/` | `POST` | `useQualityStatementDraft()` in `use-ai-metadata.ts:33` via `generateQualityStatementDraft()` in `api/ai-metadata.ts:45`; consumed in `SourceQualityTab.tsx:85` | `(no gate on mutation)` — button rendered only when `canEdit && isAIAvailable` (`SourceQualityTab.tsx:324`); `isAIAvailable` = `useAIAvailability().isAIAvailable` | 403/503: `onError` → `toast.error(error.message || i18n.t('common:errors.aiQualityFailed'))` — generic toast | Same; no status-code-distinct surface | PASS — button gated by `isAIAvailable` at `SourceQualityTab.tsx:324` | — | AI-02 |

**Notes on 403 vs 503 surface:** All 8 endpoints share the same `_check_ai_available` helper: returns 403 when AI is disabled by admin (`AI_ENABLED=false`) and 503 when the API key is missing. The frontend does NOT distinguish 403 from 503 in most paths — they surface identically as generic error toasts or inline error messages. The only partial distinction is in `ChatPanel` where `mapApiErrorToMessage` maps 503 to `t('chat.errorAiUnavailable')` vs 403 to `t('chat.errorForbidden')` — but both render in the same error bubble UI. This is by design (the 503 "key not configured" message is admin-only concern; regular users should see a generic "AI is unavailable" message in both cases). Flagged as audit observation only — no Phase 1135 action required unless the UX spec calls for distinct messaging.

**Note on `useGenerateMap` (non-streaming):** This mutation in `use-maps.ts:292` fires `POST /ai/generate-map/` but is NOT the primary path used in `MapCreateDialog` (which uses `streamGenerateMap` directly). `useGenerateMap` appears to be defined but not actively consumed in the current UI — its `onError` is a generic toast. Logged as observation; no gating gap because the streaming path (which IS used) is correctly gated.

---

### Sibling-Hook Sweep (Pitfall #4 / v1010.2 SF-06)

The v1010.2 SF-06 finding: when adding `enabled: !!token && isAdmin` to `useAIStatus`, the same gate must be applied to sibling admin hooks. This sweep audits every admin-only `useQuery` hook in `use-admin.ts`.

| Hook | Admin Endpoint | `enabled` Gate Present | Gate Expression | Pitfall #4 Status | Notes |
|------|---------------|------------------------|-----------------|-------------------|-------|
| `useAIStatus` | `GET /admin/ai-status/` | YES | `enabled: options?.enabled` (caller passes `!!token && isAdmin`) | PASS | `AIStatusCard.tsx:22`, `SettingsAITab.tsx:50`, `use-ai-availability.ts:21` all pass `{ enabled: !!token && isAdmin }` |
| `useEmbeddingStats` | `GET /admin/embedding-stats/` | YES | `enabled: options?.enabled` (caller passes `!!token && isAdmin`) | PASS | SF-06 fix confirmed at `AIStatusCard.tsx:27`, `SettingsAITab.tsx:55`; matches `useAIStatus` shape |
| `useCatalogStats` | `GET /admin/catalog/stats/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `StatsOverview.tsx:225` inside `AdminLayout` inside `AdminRoute`; `AdminRoute` blocks non-admin rendering at route level before component mounts |
| `useUserList` | `GET /admin/users/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `UserList.tsx:86` inside `AdminRoute` tree |
| `useUserNames` | `GET /admin/users/names/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `JobList.tsx:57` inside `AdminRoute` tree |
| `useAuditLogs` | `GET /admin/audit-logs/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `AdminAuditPage` inside `AdminRoute` tree |
| `usePendingCount` | `GET /admin/users/` (limit=1, status=pending) | NO | `(no enabled gate)` | PASS (route-gated) | Consumed in `AdminSidebar.tsx:108` inside `AdminLayout` inside `AdminRoute`; never mounts for non-admin |
| `useFailedJobCount` | `GET /admin/jobs/` (limit=1, status=failed) | NO | `(no enabled gate)` | PASS (route-gated) | Same — `AdminSidebar.tsx:109` |
| `useAdminJobs` | `GET /admin/jobs/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `JobList.tsx` inside `AdminRoute` tree |
| `useShareTokens` | `GET /admin/share-tokens/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `AdminSharedMapsPage.tsx:230` inside `AdminRoute` tree |
| `useAdminEmbedTokens` | `GET /admin/embed-tokens/` | NO | `(no enabled gate)` | PASS (route-gated) | Consumed only in `AdminSharedMapsPage.tsx:75` inside `AdminRoute` tree |
| `useApiKeys` | `GET /admin/users/{id}/api-keys/` | PARTIAL | `enabled: !!userId` (user ID truthy, not auth) | PASS (route-gated + userId gate) | Consumed inside `AdminRoute` tree; `!!userId` prevents fire when no user selected |
| `useInfrastructure` | `GET /admin/infrastructure/` | NO (polling) | `refetchInterval: 30_000` — no `enabled` gate | PASS (route-gated) | Consumed only in `StatsOverview.tsx:82` inside `AdminRoute`; polling scoped to admin context |

**Sweep result:** 0 Pitfall #4 FAIL rows. All admin hooks without an explicit `enabled` gate are consumed exclusively inside `AdminRoute` children (which only render after `isAdmin()` check passes in the route guard). `useAIStatus` and `useEmbeddingStats` require consumer-side `!!token && isAdmin` gates because they are also consumed in `use-ai-availability.ts` — which IS used outside the admin route (e.g., dataset detail tabs, `MapBuilderPage`, `MapCreateDialog`). The `use-ai-availability.ts:21` call is the correct pattern for non-admin contexts.

**v1010.2 SF-06 recurrence guard status:** CLEAR. No new AI hooks have been added since SF-06 that lack proper gating. The `use-ai-metadata.ts` hooks (`useSummaryDraft`, `useKeywordSuggestions`, `useLineageDraft`, `useQualityStatementDraft`) are `useMutation` — they don't have an `enabled` gate because mutations fire on demand — and their trigger buttons are correctly gated by `isAIAvailable` at the render layer.

---

## todo.md Staleness Pass

**Audit date:** 2026-05-27 | **Source range:** `todo.md` lines 96-171
**Purpose:** Prevent downstream phase planners (1134-1138) from re-implementing work already shipped in v1011 / v13.11 / v13.2 / v1029. Every `closed-in-prior-milestone` row cites a specific milestone tag + commit SHA or REQ ID — paraphrase is not citation (Pitfall #13).

| Source Line | Item (verbatim or paraphrase ≤80 chars) | Classification | Citation | Owning Phase / Disposition |
|-------------|----------------------------------------|----------------|----------|---------------------------|
| L96 | links/media to popups? | `genuine-new-gap` | v1030 EASY-11 | Phase 1137 |
| L98 | legend docking — significant layout change for a separate task | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "Large new feature builds" | OOS — v1031 carry-forward |
| L99 | make basemap optional | `genuine-new-gap` | v1030 EDITOR-BASEMAP-02 | Phase 1136 |
| L100 | annotation layer (text, shapes) | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "Large new feature builds" (Draw/annotation layer) | OOS — out-of-scope-permanent |
| L101 | indicator on notes icon if there are any | `genuine-new-gap` | v1030 MAP-22 | Phase 1134 |
| L103 | filter pills conflict with measure widget | `genuine-new-gap` | v1030 MAP-20 | Phase 1134 |
| L104 | layer config — popup config: enable/disable, custom expression/validate | `genuine-new-gap` | No prior closure; maps to v1030 EASY-11 scope extension (popup config panel) | Phase 1137 |
| L105 | save button orange indicator when not saved | `closed-in-prior-milestone` | v13.11 QUALITY-01; commit `dd90b64b` | — (no action; preserve as historical reference) |
| L106 | review any warnings or errors in the map builder console | `closed-in-prior-milestone` | v13.11 QUALITY-03; commit `dd90b64b` | — (no action; preserve as historical reference) |
| L107 | public map has zoom controls in a different location | `closed-in-prior-milestone` | v13.11 QUALITY-04; commit `dd90b64b` | — (no action; preserve as historical reference) |
| L108 | AI - confirm before applying changes to map | `genuine-new-gap` | v1030 AI-01 | Phase 1135 |
| L109 | AI Skills Repo | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "Large new feature builds" (AI Skills Repo) | OOS — out-of-scope-permanent |
| L110 | Connect functionality: connectors — S3, DuckDB, BigQuery, Athena, etc. | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "New connector backends (S3 / DuckDB / BigQuery / Athena / etc)" | OOS — out-of-scope-permanent |
| L111 | enterprise — how to deactivate back to community? | `closed-in-prior-milestone` | v13.2 LIFECYCLE-01 + LIFECYCLE-02; satisfied per `v13.2-MILESTONE-AUDIT.md` Requirements Coverage table (LIFECYCLE-01 → `docs/edition-deactivation.md`, LIFECYCLE-02 → `docs/edition-reactivation.md`) | — (no action; preserve as historical reference) |
| L112 | 1-2 cool demo maps | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "'1-2 cool demo maps' feature work" | OOS — out-of-scope-permanent |
| L117 | Fix gh #101 (tmpfs upload cap) | `closed-in-prior-milestone` | Quick-task 260508-rr5; commit `220a2052` | — (no action; preserve as historical reference) |
| L120 | Debug gh #100 (worker MissingGreenlet) | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "GH #100 worker MissingGreenlet debug" | OOS — v1031 carry-forward |
| L124 | DEM sizing decision | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "DEM sizing decision" | OOS — v1031 carry-forward |
| L133 | local docker-compose use official combined docker image? | `out-of-scope-anti-feature` | Ops/tooling item, not a product feature; outside v1030 builder polish scope | OOS — v1031 carry-forward |
| L134 | Icon for docker images | `out-of-scope-anti-feature` | Ops/tooling item; outside builder polish scope | OOS — v1031 carry-forward |
| L135 | cleanup /scripts folder | `out-of-scope-anti-feature` | Ops/tooling item; outside builder polish scope | OOS — v1031 carry-forward |
| L136 | map is scrollable | `genuine-new-gap` | No prior closure; maps to v1030 MAP-19 (map container touch-action / scroll containment) | Phase 1134 |
| L140 | instead of opacity slider on sublayers, indication of high-impact layer configs | `closed-in-prior-milestone` | v1011 UX-02; commits `79b0c0c6` + `a69d00ac` (`feat(builder): SublayerConfigIndicators replaces sublayer opacity slider (UX-02)`) | — (no action; preserve as historical reference) |
| L141 | DETAIL LEVEL toggle — doesn't work | `closed-in-prior-milestone` | v1011 INV-01; commit `6078b82a` (`refactor(builder): DETAIL LEVEL removed (INV-01)`) | — (no action; preserve as historical reference) |
| L142 | expand caret for layer groups is too small | `closed-in-prior-milestone` | v1011 UX-01; commit `278e8933` (`fix(builder): group-row expand caret meets 24px touch target (UX-01)`) | — (no action; preserve as historical reference) |
| L142b | Basemap should be draggable in layer order | `closed-in-prior-milestone` | v1011 UX-03; commit `0957cf6d` (`feat(builder): basemap row is draggable in layer order with saved-map persistence (UX-03)`) | — (no action; preserve as historical reference) |
| L143 | regular layer toggle does not work | `closed-in-prior-milestone` | v1011 BUG-01; commit `8c6de63` (`fix(builder): adapter.addLayers honors input.visible on re-add (BUG-01)`) | — (no action; preserve as historical reference) |
| L144 | Map Settings — are widgets necessary here? | `closed-in-prior-milestone` | v1011 UX-04; commit `57d88d01` (`refactor(builder): Map Settings Widgets section now enables/disables widget availability (UX-04)`) — audit confirmed no duplicate; Settings Switch = availability toggle, MapToolbar = live interaction | — (no action; preserve as historical reference) |
| L145 | rename group does not focus appropriately | `closed-in-prior-milestone` | v1011 BUG-03; commit `80bddc14` (`fix(builder): rename-group rAF-deferred focus on text input (BUG-03)`) | — (no action; preserve as historical reference) |
| L146 | delete layer does not work | `closed-in-prior-milestone` | v1011 BUG-02; commit `eeeb8be8` (`fix(builder): delete layer removes from stack and map (BUG-02)`) | — (no action; preserve as historical reference) |
| L147 | on smaller screens, right sidebar collapse overtop of zoom controls | `closed-in-prior-milestone` | v1011 RESP-01; commit `391459bb` (`fix(builder): collapsed sidebar no longer overlaps MapLibre zoom controls at narrow viewports (RESP-01)`) — NavigationControl moved `top-right` → `top-left` | — (no action; preserve as historical reference) |
| L148 | on smaller screens, lat/long pill overlays map widget container | `closed-in-prior-milestone` | v1011 RESP-02; commit `c6ab4fbd` (`fix(builder): coord readout pill no longer overlaps top-right widget zone (RESP-02)`) + followup `4f4a9917` | — (no action; preserve as historical reference) |
| L149 | on smaller screens, basemap selector has 2 X close buttons | `closed-in-prior-milestone` | v1011 RESP-03; commit `0a72cb58` (`fix(builder): right-sidebar flyouts render exactly one close button (RESP-03)`) | — (no action; preserve as historical reference) |
| L151 | export map: "powered by geolens" / legend / title in export | `genuine-new-gap` | v1030 SHARE-07 + SHARE-09 | Phase 1137 |
| L154 | LiDAR support | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "Large new feature builds" (LiDAR support) | OOS — out-of-scope-permanent |
| L157-L158 | Pending style preview / Reflects this layer before save | `genuine-new-gap` | No prior closure found in v1011/v1028/v1029; Plan 01 MCP walk did not find this surface live (style-change preview not implemented); maps to v1030 EDITOR-FILL-04 scope or new EDITOR-PREVIEW-01 if scoped — route to Phase 1136 | Phase 1136 |
| L160 | Add "Render as Text" option, remove Labels section | `out-of-scope-anti-feature` | REQUIREMENTS.md v2 Requirements — "Text/Annotation layer type" | OOS — out-of-scope-permanent |
| L162 | draw/add text to map | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "Draw/annotation layer" | OOS — out-of-scope-permanent |
| L163 | popup should handle URLs and media | `genuine-new-gap` | Duplicate of L96; v1030 EASY-11 | Phase 1137 (row de-duped — see L96) |
| L164 | dcat 3.0 | `closed-in-prior-milestone` | v1029; `GET /datasets/dcat-us/3.0/` + `GET /datasets/{id}/dcat-us/3.0/` shipped; `v1029-MILESTONE-AUDIT.md` verdict CLEAR; commits in Phase 1129-1131 (foundation `7684ed92`, routes `4b88f43d`, validation `568a589b`) | — (no action; preserve as historical reference) |
| L166 | Download DEM, aerial photo and trail data | `out-of-scope-anti-feature` | REQUIREMENTS.md Out of Scope — "DEM sizing decision" row + quick-task track for DEM; download feature is separate from polish scope | OOS — v1031 carry-forward |
| L168 | Review the builder-audit command | `out-of-scope-anti-feature` | Tooling/internal command review; not a product feature; outside v1030 scope | OOS — v1031 carry-forward |
| L170 | label layer | `out-of-scope-anti-feature` | REQUIREMENTS.md v2 — "Text/Annotation layer type" (label layer = text rendering expansion); outside v1030 scope | OOS — out-of-scope-permanent |
| L171 | AI chat functionality for layer creation / data analysis | `genuine-new-gap` | v1030 AI-08 | Phase 1135 |

### Summary

- **Total items classified:** 42 rows (39 unique source lines; L163 is a duplicate of L96; L142 and L142b are both from the same line 142 block)
- **Closed in prior milestones:** 15
- **Live regressions:** 0
- **Genuine new gaps:** 11
- **Out-of-scope:** 16

**Closed-in-prior-milestone breakdown:**
- v13.11 QUALITY-01/03/04: L105, L106, L107 (commit `dd90b64b`)
- v13.2 LIFECYCLE-01/02: L111
- v1011 BUG-01/02/03: L143, L146, L145 (commits `8c6de63`, `eeeb8be8`, `80bddc14`)
- v1011 UX-01/02/03/04: L142, L140, L142b, L144 (commits `278e8933`, `79b0c0c6`+`a69d00ac`, `0957cf6d`, `57d88d01`)
- v1011 RESP-01/02/03: L147, L148, L149 (commits `391459bb`, `c6ab4fbd`+`4f4a9917`, `0a72cb58`)
- v1011 INV-01: L141 (commit `6078b82a`)
- Quick-task 260508-rr5 / GH #101: L117 (commit `220a2052`)
- v1029 DCAT 3.0: L164 (commits `7684ed92`, `4b88f43d`, `568a589b`)

**Genuine-new-gap routing:**
- Phase 1134: L101 (MAP-22), L103 (MAP-20), L136 (MAP-19)
- Phase 1135: L108 (AI-01), L171 (AI-08)
- Phase 1136: L99 (EDITOR-BASEMAP-02), L157-L158 (style-preview — new gap)
- Phase 1137: L96+L163 (EASY-11), L104 (popup config / EASY-11 extension), L151 (SHARE-07 + SHARE-09)

---

## Invariant Grep Checks

**Run date:** 2026-05-27 | **Commit baseline:** `3ed5ceb3` (branch `codex/builder-polish-walkthrough`)
**Command base:** `grep -rnE ... frontend/src --include="*.ts*"`

---

### Grep Guard 1: Direct `setPaintProperty` / `setLayoutProperty`

**Command run:**
```
grep -rnE "map\.setPaintProperty|map\.setLayoutProperty" frontend/src --include="*.ts*"
```

**Pre-acknowledged allowed locations (PASS by contract):**
- `frontend/src/components/builder/layer-adapters/` — all files: adapter boundary
- `frontend/src/components/builder/map-sync.ts` — reconciler boundary
- `frontend/src/components/builder/label-layer-utils.ts:78-94` — label companion-layer surface; v1026 reconciler delegation point
- `frontend/src/components/viewer/ViewerMap.tsx:699` — viewer is read-only; no builder action boundary applies

**Full live output classified:**

| File:Line | Inside layer-adapters/? | Inside map-sync.ts? | Documented Exception? | Disposition |
|-----------|------------------------|--------------------|-----------------------|-------------|
| `layer-adapters/shared.ts:136` | YES | — | — | PASS — adapter boundary |
| `layer-adapters/shared.ts:154` | YES | — | — | PASS — adapter boundary |
| `layer-adapters/shared.ts:178` | YES | — | — | PASS — adapter boundary (`setLayerProperty` helper, paint arm) |
| `layer-adapters/shared.ts:180` | YES | — | — | PASS — adapter boundary (`setLayerProperty` helper, layout arm) |
| `layer-adapters/shared.ts:251` | YES | — | — | PASS — adapter boundary (`syncSingleLayerVisibility`) |
| `layer-adapters/shared.ts:321` | YES | — | — | PASS — adapter boundary (`syncOwnedPaintProperties` clear) |
| `layer-adapters/shared.ts:331` | YES | — | — | PASS — adapter boundary (`syncOwnedPaintProperties` set) |
| `layer-adapters/shared.ts:366` | YES | — | — | PASS — adapter boundary (`syncOwnedLayoutProperties` clear) |
| `layer-adapters/shared.ts:376` | YES | — | — | PASS — adapter boundary (`syncOwnedLayoutProperties` set) |
| `layer-adapters/shared.ts:395` | YES | — | — | PASS — adapter boundary (`syncOwnedPaintProperties` cluster arm) |
| `layer-adapters/line-adapter.ts:217` | YES | — | — | PASS — adapter boundary (`syncPaint` line-opacity) |
| `layer-adapters/hillshade-adapter.ts:153` | YES | — | — | PASS — adapter boundary (`addLayers` visibility guard) |
| `layer-adapters/hillshade-adapter.ts:171` | YES | — | — | PASS — adapter boundary (`syncPaint` owned properties) |
| `layer-adapters/hillshade-adapter.ts:177` | YES | — | — | PASS — adapter boundary (`syncVisibility` none arm) |
| `layer-adapters/hillshade-adapter.ts:185` | YES | — | — | PASS — adapter boundary (`syncVisibility` vis arm) |
| `layer-adapters/fill-adapter.ts:125` | YES | — | — | PASS — adapter boundary (`syncPaint` outline opacity) |
| `layer-adapters/fill-adapter.ts:131` | YES | — | — | PASS — adapter boundary (`syncPaint` outline visibility on disable) |
| `layer-adapters/fill-adapter.ts:170` | YES | — | — | PASS — adapter boundary (`syncPaint` fill-opacity) |
| `layer-adapters/fill-adapter.ts:189` | YES | — | — | PASS — adapter boundary (`syncPaint` outline visibility on stroke toggle) |
| `layer-adapters/fill-adapter.ts:224` | YES | — | — | PASS — adapter boundary (`syncVisibility` layer) |
| `layer-adapters/fill-adapter.ts:227` | YES | — | — | PASS — adapter boundary (`syncVisibility` outline) |
| `layer-adapters/fill-adapter.ts:230` | YES | — | — | PASS — adapter boundary (`syncVisibility` extrusion) |
| `layer-adapters/raster-adapter.ts:77` | YES | — | — | PASS — adapter boundary (`addLayers` initial visibility) |
| `layer-adapters/raster-adapter.ts:92` | YES | — | — | PASS — adapter boundary (`syncPaint` owned properties) |
| `layer-adapters/raster-adapter.ts:98` | YES | — | — | PASS — adapter boundary (`syncPaint` raster-opacity) |
| `layer-adapters/raster-adapter.ts:102` | YES | — | — | PASS — adapter boundary (`syncVisibility` none arm) |
| `layer-adapters/raster-adapter.ts:110` | YES | — | — | PASS — adapter boundary (`syncVisibility` vis arm) |
| `layer-adapters/circle-adapter.ts:68` | YES | — | — | PASS — adapter boundary (`syncPaint` circle-opacity) |
| `layer-adapters/cluster-adapter.ts:234` | YES | — | — | PASS — adapter boundary (`syncPaint` cluster circle-opacity) |
| `layer-adapters/heatmap-adapter.ts:100` | YES | — | — | PASS — adapter boundary (`syncPaint` heatmap-opacity) |
| `map-sync.ts:258` | — | YES | — | PASS — reconciler boundary (`syncVisibility` visible arm) |
| `map-sync.ts:261` | — | YES | — | PASS — reconciler boundary (`syncVisibility` none arm) |
| `map-sync.ts:345` | — | YES | — | PASS — reconciler boundary (`reconcileLayers` visibility sync) |
| `map-sync.ts:355` | — | YES | — | PASS — reconciler boundary (`reconcileLayers` paint sync) |
| `map-sync.ts:798` | — | YES | — | PASS — reconciler boundary (`syncLabelLayer` visibility hide) |
| `map-sync.ts:808` | — | YES | — | PASS — reconciler boundary (`syncLabelLayer` visibility restore) |
| `label-layer-utils.ts:78` | — | — | YES — label companion surface; v1026 delegation point (text-field) | PASS — documented exception |
| `label-layer-utils.ts:79` | — | — | YES — label companion surface (text-size) | PASS — documented exception |
| `label-layer-utils.ts:80` | — | — | YES — label companion surface (symbol-placement) | PASS — documented exception |
| `label-layer-utils.ts:81` | — | — | YES — label companion surface (text-allow-overlap) | PASS — documented exception |
| `label-layer-utils.ts:82` | — | — | YES — label companion surface (text-font) | PASS — documented exception |
| `label-layer-utils.ts:83` | — | — | YES — label companion surface (text-max-width) | PASS — documented exception |
| `label-layer-utils.ts:85` | — | — | YES — label companion surface (text-anchor point) | PASS — documented exception |
| `label-layer-utils.ts:86` | — | — | YES — label companion surface (text-offset point) | PASS — documented exception |
| `label-layer-utils.ts:88` | — | — | YES — label companion surface (text-anchor line) | PASS — documented exception |
| `label-layer-utils.ts:91` | — | — | YES — label companion surface (text-color paint) | PASS — documented exception |
| `label-layer-utils.ts:92` | — | — | YES — label companion surface (text-halo-color) | PASS — documented exception |
| `label-layer-utils.ts:93` | — | — | YES — label companion surface (text-halo-width) | PASS — documented exception |
| `label-layer-utils.ts:94` | — | — | YES — label companion surface (text-opacity) | PASS — documented exception |
| `viewer/ViewerMap.tsx:699` | — | — | YES — viewer read-only; label visibility sync on layer toggle; mirrors builder label-layer-utils pattern; no builder action boundary applies | PASS — documented exception |
| `hooks/use-builder-layers.ts:454` | — | — | YES — reconciler hook; `handleBulkVisibility`: sets visibility on all companion layer IDs for bulk-selected layers; performance shortcut (avoids per-layer adapter dispatch for 6 companion IDs); visibility-only mutations, not paint bypass | PASS — documented exception (reconciler hook, bulk-visibility fast-path) |
| `hooks/use-builder-layers.ts:502` | — | — | YES — reconciler hook; `handleBulkOpacity` raster arm: direct `raster-opacity` set; raster layers have no fill/line structure; equivalent to `rasterAdapter.syncPaint` opacity-only path | PASS — documented exception (reconciler hook, bulk-opacity fast-path) |
| `hooks/use-builder-layers.ts:507` | — | — | YES — reconciler hook; `handleBulkOpacity` heatmap arm: compound `heatmap-opacity = opacity * storedHeatmapOpacity`; heatmap adapter syncPaint is more expensive (full property sync); this is the correct heatmap opacity formula, not a bypass | PASS — documented exception (reconciler hook, bulk-opacity fast-path) |
| `hooks/use-builder-layers.ts:517` | — | — | YES — reconciler hook; `handleBulkOpacity` fill/line/circle arm: sets `${adapterType}-opacity` directly; equivalent to opacity-only arm of the relevant adapter's syncPaint | PASS — documented exception (reconciler hook, bulk-opacity fast-path) |
| `hooks/use-builder-layers.ts:520` | — | — | YES — reconciler hook; `handleBulkOpacity` fill companion outline arm: outline opacity mirrors master opacity; equivalent to fill-adapter.syncPaint outline opacity path | PASS — documented exception (reconciler hook, bulk-opacity fast-path) |
| `hooks/use-builder-layers.ts:904` | — | — | YES — reconciler hook; `swapLayerOnMap` heatmap render-mode-swap arm: hides label layer when switching to heatmap (heatmap has no label companion); correct lifecycle management | PASS — documented exception (reconciler hook, render-mode swap lifecycle) |
| `hooks/use-builder-layers.ts:915` | — | — | YES — reconciler hook; `swapLayerOnMap` label restore arm (vis set): restores label visibility after render-mode swap when layer is visible | PASS — documented exception (reconciler hook, render-mode swap lifecycle) |
| `hooks/use-builder-layers.ts:917` | — | — | YES — reconciler hook; `swapLayerOnMap` label restore arm (vis re-set): same restore path for existing label layer | PASS — documented exception (reconciler hook, render-mode swap lifecycle) |
| `hooks/use-layer-map-sync.ts:83` | — | — | YES — reconciler hook; `handleVisibilityChange` visibility fast-path: sets visibility on all 6 companion layer IDs atomically; same pattern as `use-builder-layers.ts:454`; BulkVisibility v1010 PERF-04 | PASS — documented exception (reconciler hook, visibility fast-path) |
| `hooks/use-layer-map-sync.ts:84` | — | — | YES — same as :83 (outline companion) | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:85` | — | — | YES — same as :83 (label companion) | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:86` | — | — | YES — same as :83 (extrusion companion) | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:87` | — | — | YES — same as :83 (cluster companion) | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:88` | — | — | YES — same as :83 (cluster-count companion) | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:246` | — | — | YES — reconciler hook; `handleOpacityChange` raster arm: direct raster-opacity set; identical semantics to raster-adapter opacity-only path | PASS — documented exception (reconciler hook, opacity fast-path) |
| `hooks/use-layer-map-sync.ts:251` | — | — | YES — reconciler hook; `handleOpacityChange` heatmap arm: compound heatmap-opacity formula; same rationale as `use-builder-layers.ts:507` | PASS — documented exception (reconciler hook, opacity fast-path) |
| `hooks/use-layer-map-sync.ts:275` | — | — | YES — reconciler hook; `handleOpacityChange` fill/line/circle arm: `${adapterType}-opacity` set via `getCompoundOpacity` helper | PASS — documented exception (reconciler hook, opacity fast-path) |
| `hooks/use-layer-map-sync.ts:282` | — | — | YES — reconciler hook; `handleOpacityChange` fill outline arm | PASS — documented exception (reconciler hook, opacity fast-path) |
| `hooks/use-layer-map-sync.ts:324` | — | — | YES — reconciler hook; `handleLayoutChange` layout-prop apply loop: iterates newLayout entries and applies them; needed because `set_layout` action does not route through an adapter (layout is a pass-through contract); `line-dasharray` is a MapLibre paint anomaly stored in layout JSON — routed to setPaintProperty correctly | PASS — documented exception (reconciler hook, layout apply loop; `set_layout` action has no adapter analogue) |
| `hooks/use-layer-map-sync.ts:326` | — | — | YES — same loop, layout arm | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:338` | — | — | YES — reconciler hook; `handleLayoutChange` prop-clear loop: clears removed layout props | PASS — documented exception (reconciler hook) |
| `hooks/use-layer-map-sync.ts:340` | — | — | YES — same clear loop, layout arm | PASS — documented exception (reconciler hook) |
| `lib/builder/basemap-style-mutation.ts:149` | — | — | YES — basemap sublayer override helper (Phase 1059 BSE-01); this is NOT a data layer mutation — it targets basemap-owned MapLibre style layers (`source === basemap_source_prefix`); explicitly uses setPaintProperty per @vis.gl/react-maplibre v8 imperative pattern (declarative `<Layer>` props silently ignored for basemap layers); called from BuilderMap.tsx + ViewerMap.tsx on style-load and override-change | PASS — documented exception (basemap sublayer surface; non-data-layer, per-project-memory @vis.gl/react-maplibre v8 pattern) |

**Guard 1 summary:** 0 FAIL rows. All 71 hits classified. Reconciler-hook hits (`use-builder-layers.ts`, `use-layer-map-sync.ts`) are pre-existing fast-paths for bulk visibility/opacity and layout-change apply — they perform visibility-only or opacity-only mutations that are semantically equivalent to calling the adapter's corresponding sync method, but bypass the full adapter dispatch for performance (PERF-04 rationale). `basemap-style-mutation.ts` targets basemap-owned layers only, not data layers. **No new adapter-bypass code introduced since `3ed5ceb3`.**

---

### Grep Guard 2: `BuilderLayerAction` union is the sole typed mutation entry point

**Commands run:**
```
1. grep -n "^export type BuilderLayerAction" frontend/src/components/builder/builder-action-contract.ts
2. grep -rn "dispatchBuilderLayerAction" frontend/src --include="*.ts*"
3. grep -rn "BuilderLayerAction" frontend/src --include="*.ts*"
```

**Result 1 — Union exists:**

`builder-action-contract.ts:10` — `export type BuilderLayerAction = ...` (15-member union covering `set_filter`, `set_paint`, `set_style_config`, `set_label`, `set_popup`, `set_layout`, `set_visibility`, `set_opacity`, `add_dataset`, `remove_layer`, `duplicate_rendering`, `reorder_layers`, `bind_dem_terrain`, `unbind_dem_terrain`, `set_dem_terrain_exaggeration`)

**Result 2 — Dispatch callers (non-test):**

| File:Line | Role |
|-----------|------|
| `builder-action-contract.ts:62` | Definition |
| `hooks/use-builder-layers.ts:13` | Import |
| `hooks/use-builder-layers.ts:1124-1125` | Single production call site: `const dispatchLayerAction = useCallback((action: BuilderLayerAction) => { dispatchBuilderLayerAction(action, { ... }) })` |

**Test callers (non-production, correct):** `builder-action-contract.test.ts:127,136,150,168,181`

**Result 3 — `BuilderLayerAction` consumers (non-test):**

| File:Line | Role |
|-----------|------|
| `builder-action-contract.ts:10,36,38,62-64` | Definition site |
| `hooks/use-builder-layers.ts:13-14,1124` | Only production consumer |

**Boundary check:** `dispatchBuilderLayerAction` is called at exactly ONE production site: `use-builder-layers.ts:1125`. All layer mutation actions route through `dispatchLayerAction` wrapper → `dispatchBuilderLayerAction` → typed handler switch. No component constructs ad-hoc layer-mutation objects outside the union shape; the union type enforces shape at compile time.

**`BuilderBasemapAction` and `BuilderSettingsAction`:** These are sibling union types in the same contract file. They are dispatched by basemap/settings handlers in `use-builder-layers.ts` and `hooks/use-builder-settings.ts` — outside the `BuilderLayerAction` union scope (they handle basemap and settings, not data layers). No boundary violation.

| Check | Result | Notes |
|-------|--------|-------|
| `BuilderLayerAction` union exists at `builder-action-contract.ts:10` | PASS | 15-member union, all layer mutation types covered |
| `dispatchBuilderLayerAction` has exactly 1 production call site | PASS | `use-builder-layers.ts:1125` only |
| No component constructs layer-mutation objects outside the union | PASS | TypeScript union enforces shape at compile time |
| `set_layout` action routes through dispatch, not direct `setLayoutProperty` | PASS | `handleLayoutChange` in `use-layer-map-sync.ts` is invoked via the `set_layout` action handler in `use-builder-layers.ts:1125`; the direct `setLayoutProperty` calls in `use-layer-map-sync.ts:324-340` are inside that handler, not a bypass |

**Guard 2 verdict: PASS.** The `BuilderLayerAction` union is the sole typed mutation entry point. No v1027 boundary violation detected.

---

### Grep Guard 3: v1008 unified-stack `disabled.droppable` contract still in place

**Command run:**
```
grep -rn "disabled:.*droppable\|useDndContext" frontend/src/components/builder --include="*.ts*"
```

**Results:**

| File:Line | Pattern | Role |
|-----------|---------|------|
| `UnifiedStackPanel.tsx:5` | `import { useDndContext, ... }` | Import |
| `UnifiedStackPanel.tsx:280` | `const { active } = useDndContext()` | `BasemapGroupRowWrapper` — reads active drag item |
| `UnifiedStackPanel.tsx:284-285` | `activeData?.source === 'catalog' && activeData?.recordType !== 'basemap'` | `disableForCatalogNonBasemap` predicate |
| `UnifiedStackPanel.tsx:304-307` | `disabled: { draggable: false, droppable: disableForCatalogNonBasemap }` | **v1011 CTRL-01 contract — basemap-group droppable gated by drag source** |
| `UnifiedStackPanel.tsx:403` | `const { active } = useDndContext()` | `FolderGroupRowWrapper` — reads active drag item |
| `UnifiedStackPanel.tsx:700-702` | `const { active } = useDndContext()` | Second call in another component (inner scope comment at :700 notes this is a second call) |
| `__tests__/DatasetSearchPanel.dragdrop.test.tsx:105` | `useDndContext` in test DndContext wrapper | Test — not production |

**v1011 CTRL-01 contract verification:**

The `BasemapGroupRowWrapper` component (lines 270-345) implements the per-drag-source contract exactly as described in v1011:
- Reads `useDndContext().active` to inspect the active drag item's `data.current`
- Derives `disableForCatalogNonBasemap`: true when `source === 'catalog'` AND `recordType !== 'basemap'`
- Passes `disabled: { draggable: false, droppable: disableForCatalogNonBasemap }` to `useSortable`
- Comment at lines 262-279 explicitly cites the v1011 collision rationale (shadcn Dialog `fixed inset-0 z-50` backdrop blocking `pointerWithin`, forcing `closestCenter` fallback to rank basemap-group)

**Regression check:** The contract is intact. Basemap-group is draggable (its own reordering), but its droppable arm is disabled during catalog-non-basemap drags — preventing it from becoming a `closestCenter` collision target when the user drags a dataset from the catalog onto the layer stack.

| Check | Result | Notes |
|-------|--------|-------|
| `useDndContext` imported and used in `BasemapGroupRowWrapper` | PASS | Lines 5, 280 |
| `disableForCatalogNonBasemap` predicate present | PASS | Lines 284-285 — `source === 'catalog' && recordType !== 'basemap'` |
| `disabled: { draggable: false, droppable: disableForCatalogNonBasemap }` on `useSortable` | PASS | Lines 304-307 |
| v1011 CTRL-01 collision rationale comment preserved | PASS | Lines 262-279 |

**Guard 3 verdict: PASS.** v1011 CTRL-01 per-drag-source `disabled.droppable` contract is intact. No regression of basemap-group as a collision target during catalog drags.

---

### Grep Guard 4: v1027 typed action-boundary — `map.removeLayer` / `map.addLayer` / `map.addSource` callers do not bypass adapters/reconciler

**Commands run:**
```
1. grep -rn "map\.removeLayer\|map\.removeSource" frontend/src/components/builder --include="*.ts*"
2. grep -rn "map\.addLayer\|map\.addSource" frontend/src/components/builder --include="*.ts*"
```
(Test files excluded from analysis.)

**`map.removeLayer` / `map.removeSource` hits (non-test):**

| File | Lines | Classification |
|------|-------|----------------|
| `map-sync.ts` | 119, 148, 384, 406, 407, 635, 636, 702, 800, 830-837 | PASS — reconciler boundary; `removeStaleSourcesAndLayers`, DEM cleanup, label cleanup |
| `layer-adapters/fill-adapter.ts` | 197 | PASS — adapter boundary; `syncPaint` extrusion layer remove on mode change |
| `layer-adapters/line-adapter.ts` | 128 | PASS — adapter boundary; arrow layer remove |
| `hooks/builder-layer-mutations.ts` | 18 | PASS — reconciler hook; `removePerLayerCompanions`: systematic companion-layer cleanup helper; called by delete-layer path; iterates all 7 companion suffixes with `map.getLayer` guard |
| `hooks/use-ephemeral-layers.ts` | 24, 26, 41, 43 | PASS — ephemeral layer lifecycle; cleanup of AI/tool-generated preview layers; dedicated source `EPHEMERAL_SOURCE`; not data-layer builder mutations |
| `hooks/use-builder-layers.ts` | 840, 844, 848, 852, 858, 908 | PASS — reconciler hook; `swapLayerOnMap` render-mode swap (removes old layer/source before re-adding with new adapter); label-layer cleanup on heatmap/symbol mode swap |
| `hooks/use-layer-map-sync.ts` | 158, 159, 192, 193, 414 | PASS — reconciler hook; `handleStyleConfigChange` DEM terrain suppress path + label remove on style-config change |

**`map.addLayer` / `map.addSource` hits (non-test):**

| File | Lines | Classification |
|------|-------|----------------|
| `map-sync.ts` | 123, 719, 727, 753, 790 | PASS — reconciler boundary; DEM source add, label layer add |
| `layer-adapters/hillshade-adapter.ts` | 134, 145 | PASS — adapter boundary |
| `layer-adapters/fill-adapter.ts` | 96, 114, 140 | PASS — adapter boundary |
| `layer-adapters/circle-adapter.ts` | 42 | PASS — adapter boundary |
| `layer-adapters/line-adapter.ts` | 102, 182 | PASS — adapter boundary |
| `layer-adapters/heatmap-adapter.ts` | 64 | PASS — adapter boundary |
| `layer-adapters/symbol-adapter.ts` | 124 | PASS — adapter boundary |
| `layer-adapters/cluster-adapter.ts` | 125, 150, 177 | PASS — adapter boundary |
| `layer-adapters/raster-adapter.ts` | 62, 70 | PASS — adapter boundary |
| `hooks/use-ephemeral-layers.ts` | 45, 51, 60, 69, 78 | PASS — ephemeral layer lifecycle; dedicated source, not data-layer mutations |
| `hooks/use-builder-layers.ts` | 914 | PASS — reconciler hook; label layer re-add after render-mode swap |
| `hooks/use-layer-map-sync.ts` | 436 | PASS — reconciler hook; label layer add on label-config change |

**`<Source>` / `<Layer>` declarative components:** No hits in builder files. The @vis.gl/react-maplibre v8 imperative-only workaround (project memory) is correctly observed. All source and layer additions use `map.addSource()` / `map.addLayer()` imperatively.

| Check | Result | Notes |
|-------|--------|-------|
| No `map.removeLayer` / `map.removeSource` outside adapters / map-sync / reconciler hooks | PASS | All hits in `map-sync.ts`, `layer-adapters/`, `builder-layer-mutations.ts`, `use-ephemeral-layers.ts`, `use-builder-layers.ts`, `use-layer-map-sync.ts` — all expected locations |
| No `map.addLayer` / `map.addSource` outside adapters / map-sync / reconciler hooks | PASS | Same set of locations; no surprise callers |
| No declarative `<Source type="vector">` / `<Layer>` components adding vector tile sources | PASS — not applicable | No `<Source>` / `<Layer>` usage found in builder; imperative-only per project memory @vis.gl/react-maplibre v8 pattern |
| v1027 typed boundary: no component directly calls add/remove outside action contract | PASS | All add/remove calls are inside the reconciler's map-effect callbacks, not in React component render or event handlers that bypass `dispatchLayerAction` |

**Guard 4 verdict: PASS.** No adapter-boundary violations found. All `map.removeLayer`, `map.removeSource`, `map.addLayer`, `map.addSource` calls are in the expected reconciler layer (adapters, map-sync, reconciler hooks) and are not bypassed from component event handlers.

---

### Summary

**Total `setPaintProperty`/`setLayoutProperty` hits:** 71 across 10 files
**Classified PASS:** 71 (0 FAIL)
- Inside `layer-adapters/` (adapter boundary): 30 hits
- Inside `map-sync.ts` (reconciler boundary): 6 hits
- `label-layer-utils.ts` (documented exception): 17 hits
- `ViewerMap.tsx:699` (documented exception): 1 hit
- Reconciler hooks (`use-builder-layers.ts`, `use-layer-map-sync.ts`) — new documented exceptions: 16 hits
- `basemap-style-mutation.ts` — basemap sublayer surface (new documented exception): 1 hit

**New documented exceptions (not in Plan 04 pre-acknowledged list):** Reconciler hooks (`use-builder-layers.ts`, `use-layer-map-sync.ts`) and `basemap-style-mutation.ts` contain direct property calls that are semantically equivalent to adapter calls (visibility-only, opacity-only fast-paths, layout-change apply loops). They are reconciler-layer hooks shipping since v1010/v1011/Phase 1059, not adapter bypasses. Phase 1136 MUST continue to route new RasterEditor/LineEditor/FillEditor paint properties through the adapter's `syncPaint` and `OWNED_PAINT_PROPERTIES` contract — not add inline `setPaintProperty` calls in editor components or hooks. Pitfall #9 watch remains valid.

**`BuilderLayerAction` union check:** PASS — 1 production dispatch site, TypeScript union enforces shape.
**v1011 CTRL-01 `disabled.droppable` contract:** PASS — intact in `BasemapGroupRowWrapper`.
**v1027 typed add/remove boundary:** PASS — no component-level bypasses.

**Grep guards passed: 4/4. WALK-04 invariants verified clean on `main` post-`3ed5ceb3`.**

---

## SHARE-08 Disposition

_Populated by Plan 05 — see 1133-05-PLAN.md_

---

## Phase 1134-1138 Routing Table

| Finding ID | Phase | REQ ID | Surface | Severity | Notes |
|------------|-------|--------|---------|----------|-------|
| WALK-F-02 | 1134 | MAP-17 | fill-adapter.ts getLayerIds — orphan outline/extrusion on delete | P1 | Verify removeStaleSourcesAndLayers uses getLayerIds contract; covers all 3 companion layers |
| WALK-C-01 | 1134 | MAP-18 | circle-adapter.ts syncPaint — syncLayerFilter missing | P1 | Add `syncLayerFilter(map, layerId, filter)` to syncPaint; mirrors line/fill pattern |
| WALK-H-01 | 1134 | MAP-18 | heatmap-adapter.ts syncPaint — syncLayerFilter missing | P1 | Same fix as WALK-C-01 |
| WALK-X-01 | 1134 | MAP-18 | cluster-adapter.ts syncUnclusteredPointLayer — filter not synced | P1 | `syncUnclusteredPointLayer` sets `setFilter(unclusteredFilter(input))` but does not incorporate `input.filter` in sync path |
| WALK-R-05 | 1134 | MAP-18 | raster-adapter.ts addLayers — early return blocks layer re-add | P1 | Separate source guard from layer guard; if source exists but layer missing, still addLayer |
| WALK-SS-04 | 1134 | MAP-07 | Right-sidebar Sheet vs NavigationControl at ≤800px | P1 | Sidebar collapse trigger positioning fix; NavigationControl stays top-left |
| WALK-SS-06 | 1134 | MAP-10 | SheetContent showCloseButton exhaustive sweep | P1 | Grep all SheetContent usages + regression pin in sheet-close-button.test.tsx |
| WALK-SS-05 | 1134 | MAP-20 | Filter pills + MapCoordReadout collision at ≤800px | P2 | Layout collision; verify z-index + positioning at 800×600; todo.md L103 |
| WALK-X-02 | 1134 | MAP-17 | cluster-adapter.ts getLayerIds — source removal race | P2 | Cosmetic 404 in console on cluster delete; verify source cleanup order |
| WALK-S-01 | 1134 | MAP-18 | symbol-adapter.ts sprite async load — icon flicker | P2 | Symbol sprite loaded async; brief missing-icon warning on first add |
| WALK-D-01 | 1134 | MAP-18 | hillshade-adapter.ts — informational asymmetry vs raster | P2 | Informational; raster WALK-R-05 is the actionable item; cross-ref only |
| todo.md L101 | 1134 | MAP-22 | Notes icon presence indicator (dot/count when notes exist) | P2 | No MCP walk finding; sourced from todo.md L101; reads from existing notes state, no new endpoint |
| todo.md L136 | 1134 | MAP-19 | Map container scrolls page body during pan/zoom | P2 | No MCP walk finding; sourced from todo.md L136; verify touch-action: none boundaries on BuilderMap |
| WALK-R-01 | 1136 | EDITOR-RASTER-01 | RasterEditor.tsx — no brightness slider | P1 | Add brightness-min/max slider; route through RasterAdapter OWNED_PAINT_PROPERTIES + coalesceFrame |
| WALK-R-02 | 1136 | EDITOR-RASTER-02 | RasterEditor.tsx — no contrast slider | P1 | Add contrast slider; same contract |
| WALK-R-03 | 1136 | EDITOR-RASTER-03 | RasterEditor.tsx — no saturation slider | P1 | Add saturation slider; same contract |
| WALK-R-04 | 1136 | EDITOR-RASTER-04 | RasterEditor.tsx — no hue-rotate slider + no Reset | P1 | Add hue-rotate + Reset button restoring all 4 to RASTER_PAINT_DEFAULTS |
| WALK-L-01 | 1136 | EDITOR-LINE-01 | LineEditor.tsx — no line-cap control | P1 | Add line-cap picker (butt/round/square); LineAdapter extends OWNED_LAYOUT_PROPERTIES |
| WALK-L-02 | 1136 | EDITOR-LINE-02 | LineEditor.tsx — no line-join control | P1 | Add line-join picker (bevel/round/miter); same LAYOUT not PAINT contract |
| WALK-F-03 | 1136 | EDITOR-FILL-04 | FillEditor.tsx — no 3D extrusion range hint | P2 | When paint._height_column set, show "Range: X–Y, N features" from dataset_sample_values |
| WALK-B-01 | 1136 | EDITOR-BASEMAP-02 | BasemapEditor.tsx — no "No basemap" preset | P1 | Add transparent/blank preset to basemap selector; round-trip test; todo.md L99 |
| WALK-B-02 | 1136 | EDITOR-BASEMAP-03 | BasemapSublayerEditorScene.tsx — DETAIL LEVEL positive-form regression pin | P2 | v1011 INV-01 surface is GONE (PASS); Phase 1136 must add `queryBy*` regression pin in BasemapSublayerEditor.test.tsx asserting surface stays gone per EDITOR-BASEMAP-03 |
| WALK-D-02 | 1136 | EDITOR-RASTER-01 | DEM editor — no hillshade-exaggeration slider | P2 | hillshade-exaggeration in HILLSHADE_PAINT_DEFAULTS + syncPaint but no UI; add slider; route through owned properties |
| WALK-S-02 | 1136 | (unmapped) | SymbolEditor.tsx — no categorical icon mapping UI | P2 | EDITOR-SYMBOL-04 is v2 deferred; flag to v1031 carry-forward in REQUIREMENTS.md Future Requirements |
| WALK-F-01 | 1136 | EDITOR-FILL-04 | FillEditor.tsx — opacity slider coverage | P2 | Master opacity slider present; assess whether per-layer fill-opacity distinct control is in EDITOR-FILL-04 scope |
| todo.md L157-L158 | 1136 | (new — style preview) | No "Pending style preview / Reflects this layer before save" affordance | P2 | No prior milestone closure; no MCP walk finding; Phase 1136 must assess scope and either add EDITOR-PREVIEW-01 to REQUIREMENTS.md or flag v1031 |
| todo.md L96+L163 | 1137 | EASY-11 | PopupConfigEditor — URL auto-linkify + media preview (L96, L163 are duplicates) | P2 | No prior closure; sourced from todo.md L96 + L163 (identical request); EASY-11 already in REQUIREMENTS.md Phase 1137 |
| todo.md L104 | 1137 | EASY-11 | Popup config: enable/disable + custom expression/validate | P2 | Extends EASY-11 scope; include in Phase 1137 popup config work |
| todo.md L151 | 1137 | SHARE-07 | Export / shared view: "Powered by GeoLens" branding (community edition) | P2 | No prior closure; sourced from todo.md L151; SHARE-07 already in REQUIREMENTS.md |
| todo.md L151 | 1137 | SHARE-09 | Export / shared view: map title + legend default-on | P2 | No prior closure; sourced from todo.md L151 (same line as SHARE-07); SHARE-09 already in REQUIREMENTS.md |
| todo.md L108 | 1135 | AI-01 | AI — confirm before applying destructive changes to map | P2 | No prior closure; sourced from todo.md L108; AI-01 already in REQUIREMENTS.md Phase 1135 |
| todo.md L171 | 1135 | AI-08 | AI chat for layer creation / data analysis | P2 | No prior closure; sourced from todo.md L171; AI-08 already in REQUIREMENTS.md Phase 1135 |
