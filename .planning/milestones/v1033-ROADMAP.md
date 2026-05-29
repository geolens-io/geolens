# v1033 Builder Terrain, Label & Render-Mode QA — Archived Roadmap

**Shipped:** 2026-05-29 · **Local tag:** `v1033` · **CHANGELOG:** `[1.8.0]`
**Phases:** 1148-1151 (4) · **Plans:** 7 · **Requirements:** 9/9 · **Audit:** `tech_debt` (0 blockers)
**Commit range:** `f5f84a62`..`<tag>` (23 commits) · **Source diff:** 21 files, +516/−135

## Milestone Goal

Close the builder render-mode persistence defects surfaced by a live Playwright MCP walkthrough of the two ADK sample maps — chiefly the DEM `render_mode:'terrain'` strip-on-load (no 3D mesh + raster "Render as" save-revert) — and add the missing layer-list label indicator, with light builder polish and a raster-cache hygiene fix.

**Coverage:** 9/9 v1 requirements.

## Phases

- [x] **Phase 1148: Render-Mode Persistence Fix** — Add `'terrain'` + `'image'` to the `RENDER_MODES` allowlist and extend the `StyleConfig['render_mode']` union; remove the BSR-09 boundary cast; round-trip regression tests. (RMODE-01/02/03)
- [x] **Phase 1149: Layer Label Indicator** — Pure-derived label indicator on layer rows whose `label_config.column` is set; en/de/es/fr i18n + a11y. (LABEL-01)
- [x] **Phase 1150: Builder Polish & Raster Cache Hygiene** — Consolidate duplicate point "Render as" control; graceful DEM hillshade dual-consumer guard; bound `_band_stats_cache`. (POLISH-01/02, HYG-01)
- [x] **Phase 1151: QA Close-Gate** — Orchestrator-driven Playwright MCP re-verify on both ADK sample maps + standard code gates + CHANGELOG. (QA-01/02)

## Phase Details

### Phase 1148: Render-Mode Persistence Fix
**Requirements**: RMODE-01, RMODE-02, RMODE-03
Single root cause: the `RENDER_MODES` allowlist (`normalize-style-config.ts:92`) omitted `'terrain'`/`'image'`, so `normalizeRenderMode()` discarded `'terrain'` on every read → terrain mesh never attached + raster "Render as" reverted to Image. Fix: added both to `RENDER_MODES` + the `StyleConfig['render_mode']` union (`api.ts`, hand-maintained — no OpenAPI regen); removed the `DemRenderMode` boundary cast + BSR-09 comment in `DEMEditorScene.tsx`; added round-trip + RENDER_MODES-guard unit tests.

### Phase 1149: Layer Label Indicator
**Requirements**: LABEL-01
Added a derived label indicator (`Type` glyph + `title`/sr-only) to `StackRow.tsx` name cell, gated on `!!label_config?.column && render_mode !== heatmap/symbol` (mirrors the `map-sync.ts` label gate). 4-locale i18n (`stackRow.labelsIndicator`), positive+negative RTL tests. Inline fix: `min-w-0` on the name span so long names truncate beside the indicator.

### Phase 1150: Builder Polish & Raster Cache Hygiene
**Requirements**: POLISH-01, POLISH-02, HYG-01
- POLISH-01: removed the redundant point render-as `<Select>` dropdown from `LayerStyleEditor.tsx` (+ `onRenderModeChange` pass-through); the segmented control in `LayerEditorPanel.tsx` is now the sole render-mode picker.
- POLISH-02: exported `isHillshadeTerrainBound` from `map-sync.ts`; `syncRasterLayer` skips the hillshade raster-dem consumer when the DEM powers an active terrain source (stops `backfillBorder` spam); `DEMEditorScene` shows an advisory note (4-locale). Inactive when terrain is off → primary hillshade path unaffected.
- HYG-01: `_band_stats_cache` → `cachetools.LRUCache(maxsize=256)`; backend eviction/cache-hit/negative-caching tests.

### Phase 1151: QA Close-Gate
**Requirements**: QA-01, QA-02
Orchestrator-driven live Playwright MCP on both maps (Map A terrain on fresh load + DEM editor shows Terrain + label indicator + single render-as control; Map B hillshade renders with terrain off; 0 console errors each). Code gates: typecheck 0 · vitest 2601/2601 · i18n 2/2 · lint 0-err · backend raster+tile 76 · openapi-check no-drift · e2e:smoke:builder 26/26. CHANGELOG `[1.8.0]`.

## Final Progress

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1148 Render-Mode Persistence Fix | 1/1 | Complete | 2026-05-29 |
| 1149 Layer Label Indicator | 1/1 | Complete | 2026-05-29 |
| 1150 Builder Polish & Raster Cache Hygiene | 3/3 | Complete | 2026-05-29 |
| 1151 QA Close-Gate | 1/1 | Complete | 2026-05-29 |

**Audit:** `.planning/milestones/v1033-MILESTONE-AUDIT.md` — `tech_debt` (9/9 reqs, integration CLEAN 9/9 links + 4/4 E2E flows, 0 blockers).
