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

_Populated by Plan 03 — see 1133-03-PLAN.md_

---

## Invariant Grep Checks

_Populated by Plan 04 — see 1133-04-PLAN.md_

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
| WALK-SS-05 | 1134 | MAP-20 | Filter pills + MapCoordReadout collision at ≤800px | P2 | Layout collision; verify z-index + positioning at 800×600 |
| WALK-X-02 | 1134 | MAP-17 | cluster-adapter.ts getLayerIds — source removal race | P2 | Cosmetic 404 in console on cluster delete; verify source cleanup order |
| WALK-S-01 | 1134 | MAP-18 | symbol-adapter.ts sprite async load — icon flicker | P2 | Symbol sprite loaded async; brief missing-icon warning on first add |
| WALK-D-01 | 1134 | MAP-18 | hillshade-adapter.ts — informational asymmetry vs raster | P2 | Informational; raster WALK-R-05 is the actionable item; cross-ref only |
| WALK-R-01 | 1136 | EDITOR-RASTER-01 | RasterEditor.tsx — no brightness slider | P1 | Add brightness-min/max slider; route through RasterAdapter OWNED_PAINT_PROPERTIES + coalesceFrame |
| WALK-R-02 | 1136 | EDITOR-RASTER-02 | RasterEditor.tsx — no contrast slider | P1 | Add contrast slider; same contract |
| WALK-R-03 | 1136 | EDITOR-RASTER-03 | RasterEditor.tsx — no saturation slider | P1 | Add saturation slider; same contract |
| WALK-R-04 | 1136 | EDITOR-RASTER-04 | RasterEditor.tsx — no hue-rotate slider + no Reset | P1 | Add hue-rotate + Reset button restoring all 4 to RASTER_PAINT_DEFAULTS |
| WALK-L-01 | 1136 | EDITOR-LINE-01 | LineEditor.tsx — no line-cap control | P1 | Add line-cap picker (butt/round/square); LineAdapter extends OWNED_LAYOUT_PROPERTIES |
| WALK-L-02 | 1136 | EDITOR-LINE-02 | LineEditor.tsx — no line-join control | P1 | Add line-join picker (bevel/round/miter); same LAYOUT not PAINT contract |
| WALK-F-03 | 1136 | EDITOR-FILL-04 | FillEditor.tsx — no 3D extrusion range hint | P2 | When paint._height_column set, show "Range: X–Y, N features" from dataset_sample_values |
| WALK-B-01 | 1136 | EDITOR-BASEMAP-02 | BasemapEditor.tsx — no "No basemap" preset | P1 | Add transparent/blank preset to basemap selector; round-trip test |
| WALK-B-02 | 1136 | EDITOR-BASEMAP-03 | BasemapSublayerEditorScene.tsx — DETAIL LEVEL positive-form regression pin | P2 | v1011 INV-01 surface is GONE (PASS); Phase 1136 must add `queryBy*` regression pin in BasemapSublayerEditor.test.tsx asserting surface stays gone per EDITOR-BASEMAP-03 |
| WALK-D-02 | 1136 | EDITOR-RASTER-01 | DEM editor — no hillshade-exaggeration slider | P2 | hillshade-exaggeration in HILLSHADE_PAINT_DEFAULTS + syncPaint but no UI; add slider; route through owned properties |
| WALK-S-02 | 1136 | (unmapped) | SymbolEditor.tsx — no categorical icon mapping UI | P2 | EDITOR-SYMBOL-04 is v2 deferred; flag to v1031 carry-forward in REQUIREMENTS.md Future Requirements |
| WALK-F-01 | 1136 | EDITOR-FILL-04 | FillEditor.tsx — opacity slider coverage | P2 | Master opacity slider present; assess whether per-layer fill-opacity distinct control is in EDITOR-FILL-04 scope |
