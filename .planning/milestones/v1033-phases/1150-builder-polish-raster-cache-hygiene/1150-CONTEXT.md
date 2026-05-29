# Phase 1150: Builder Polish & Raster Cache Hygiene - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped); grounded in the v1033 audit (F5, F3) + v1032 carry-forward.

<domain>
## Phase Boundary

Three independent, low-risk cleanups:
- **POLISH-01 (F5):** Remove the redundant second "Render as" control on point layers.
- **POLISH-02 (F3):** Gracefully handle a DEM that's bound to terrain AND asked to hillshade (stop the `backfillBorder` "dem dimension mismatch" error spam; inform the user).
- **HYG-01:** Bound the unbounded `_band_stats_cache` (v1032 carry-forward).

These are independent — can be separate plans/waves. POLISH-01/02 are frontend; HYG-01 is backend.
</domain>

<decisions>
## Implementation Decisions

### POLISH-01 — remove the duplicate point render-as dropdown (LOCKED)
- The canonical "Render as" control is the **segmented pill row** in `LayerEditorPanel.tsx:410-441` (`layerEditor.section.renderAs`), which has confirm-before-switch and covers point modes (Point/Symbols/Heatmap/Cluster), lines, polygons. Verified live in the audit.
- The redundant control is the `<Select>` **dropdown** in `LayerStyleEditor.tsx:367-384`, gated `geomType === 'circle'` (point-only). **Remove that `StyleControlSection` + `<Select>` block.**
- `renderMode` stays in use (it gates the data-driven section at `:387` and the appearance dispatch) — do NOT remove `renderMode`/`dispatchKey`. Only remove the dropdown JSX. Clean up any import (`Select`/`SelectItem`/`PointRenderMode`/`onRenderModeChange` prop) that becomes unused AFTER removal so typecheck + lint stay green. If `onRenderModeChange` becomes unused, drop the prop and its pass-through from the parent (`LayerEditorPanel`/wherever LayerStyleEditor is rendered) — but verify the segmented control does NOT route through `onRenderModeChange` before removing it. (The segmented control uses `handleRenderAsClick`/`renderAsOptions`/`currentRenderAs`, a separate path.)
- Acceptance: point Style tab shows exactly ONE "Render as" control (the segmented pills). Point render-mode switching still works (Points↔Symbols↔Heatmap↔Cluster) with the confirm dialog. No regression to line/polygon/raster editors.

### POLISH-02 — DEM hillshade dual-consumer guard (LOCKED predicate, conservative scope)
- **Predicate:** a DEM layer is the *active terrain source* when `terrainConfig?.enabled === true && terrainConfig.source_dataset_id === layer.dataset_id`. (`MapTerrainConfig` = `{enabled, source_dataset_id, exaggeration}`; flows into BuilderMap as `terrainConfig`.)
- **Why this is safe:** the predicate is TRUE only in Map A's scenario (terrain on, same DEM). Map B has `terrain_config.enabled=false`, so the predicate is FALSE there and its primary hillshade path is UNAFFECTED. This is the key safety property — the guard cannot regress the working hillshade map.
- **Behavior when predicate TRUE:**
  1. **map-sync:** at the hillshade gate `map-sync.ts:608` (`useHillshade = is_dem && renderMode === 'hillshade'`), do NOT spin up a second raster-dem hillshade consumer of a DEM already bound to the `terrain-dem` source — that mismatch is what emits the `backfillBorder` errors. Skip/suppress the hillshade layer for that DEM while terrain consumes it (the terrain mesh already provides relief). Implement as a derived guard fed by the terrain config; keep the change minimal and reversible.
  2. **DEMEditorScene:** when the active render mode is `hillshade` AND the predicate is true, show a muted advisory note (e.g. "Hillshade is unavailable while this DEM powers 3D Terrain — turn off Terrain to use Hillshade."). i18n key in `builder` namespace, 4-locale parity.
- **Scope discipline:** do NOT attempt to make hillshade+terrain coexist on one DEM (MapLibre limitation with non-uniform DEM tiles). The guard + note is the deliverable. Could not reproduce the raw error live (Map B clean), so verification is unit tests on the predicate + the map-sync skip + the editor note; live re-check at 1151 is best-effort.
- Unit-test the predicate and the skip/note behavior.

### HYG-01 — bound `_band_stats_cache` (LOCKED)
- `backend/app/processing/tiles/router.py:237` — `_band_stats_cache: dict[str, list[dict] | None] = {}` is unbounded. Replace with a bounded cache.
- `cachetools>=5.5.0` IS a backend dependency (resolved 7.1.1). Use `cachetools.LRUCache(maxsize=256)` (or TTLCache if freshness across re-ingest is wanted — LRU is sufficient for "bound it"). Mirrors the bounded-cache precedent at `backend/app/processing/ai/sql_generator.py:40` (`_SCHEMA_CACHE_MAX`).
- Preserve negative caching (storing `None` on fetch failure) and the `if open_path in cache` fast path — `cachetools.LRUCache` supports both (`in`, `[]`, assignment).
- Backend unit test: assert the cache evicts the oldest entry past `maxsize` (insert maxsize+1 distinct paths → first evicted) and that a cached value is returned without a second Titiler call (mock `_titiler_client.get`, assert call count 1 across two `_fetch_band_statistics` calls for the same path).
- Backend-only; no API/schema change → `make openapi-check` unaffected.
</decisions>

<code_context>
## Existing Code Insights
- `frontend/src/components/builder/LayerEditorPanel.tsx:410-441` — canonical segmented render-as control (keep).
- `frontend/src/components/builder/LayerStyleEditor.tsx:366-384` — redundant point dropdown (remove); `renderMode` still used at `:387`.
- `frontend/src/components/builder/map-sync.ts:608` — hillshade gate (`useHillshade`); `:623-625` adapter/source selection.
- `frontend/src/components/builder/BuilderMap.tsx:376-411` — `terrainConfig` ref + `applyTerrainConfig` (predicate inputs).
- `frontend/src/components/builder/DEMEditorScene.tsx` — DEM editor (render-as radios, Appearance per mode) — add the advisory note here.
- `frontend/src/types/api.ts` — `MapTerrainConfig {enabled, source_dataset_id, exaggeration}`.
- `backend/app/processing/tiles/router.py:237,240-265,571` — `_band_stats_cache`, `_fetch_band_statistics`.
- `backend/app/processing/ai/sql_generator.py:40-143` — bounded-cache precedent.
- i18n: `frontend/src/i18n/locales/{en,de,es,fr}/builder.json`.
</code_context>

<specifics>
## Specific Ideas
- POLISH-01: removing the dropdown must not break point render switching (segmented control covers it). Add/keep a test asserting the point editor renders only one render-as control.
- POLISH-02: guard predicate true only when terrain enabled + same DEM → Map B (terrain off) unaffected. Note is i18n + a11y.
- HYG-01: `cachetools.LRUCache(maxsize=256)`; eviction + cache-hit unit tests.
- Live re-verification (point editor single control; Map A terrain still attaches with no hillshade-mismatch spam; raster tiles still render) happens at the Phase 1151 orchestrator MCP close-gate.
</specifics>

<deferred>
## Deferred Ideas
None — discuss phase skipped.
</deferred>
