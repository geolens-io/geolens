# Requirements: GeoLens — v1033 Builder Terrain, Label & Render-Mode QA

**Defined:** 2026-05-29
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Audit source:** `.planning/audits/BUILDER-LABEL-RASTER-AUDIT-v1033.md` (live Playwright MCP walkthrough of maps `8dd6a129…` + `c39be324…`).

## v1 Requirements

### Render-Mode Persistence (P0)

The `RENDER_MODES` allowlist (`frontend/src/lib/normalize-style-config.ts:92` — currently `heatmap|hillshade|symbol|arrow|cluster`) is the single choke point: it omits `'terrain'` and `'image'`, so `normalizeRenderMode()` (`:174-188`) discards `'terrain'` on every load. This causes both the no-3D-terrain bug and the raster "Render as" save-revert. Fix is frontend-only (`api.ts` hand-maintained; backend `style_config` is opaque jsonb).

- [ ] **RMODE-01**: A DEM layer stored with `style_config.render_mode:'terrain'` loads with the 3D terrain mesh attached (`map.getTerrain()` is non-null and a `terrain-dem` source exists) on Map A (`8dd6a129-8eb0-4ba9-b421-716c83b160dd`) fresh load — `'terrain'` survives the normalize round trip. Pinned by adding `'terrain'` + `'image'` to `RENDER_MODES` (`frontend/src/lib/normalize-style-config.ts:92`) and extending the `StyleConfig['render_mode']` union (`frontend/src/types/api.ts:863`), plus a round-trip unit test in `frontend/src/lib/__tests__/normalize-style-config.test.ts`.
- [ ] **RMODE-02**: Changing a raster/DEM layer's "Render as" and saving persists across reload (no silent revert to Image) — after reload the DEM editor shows the saved mode (e.g. ◬ Terrain checked, not ▦ Image). Same fix as RMODE-01; distinct acceptance verified live on Map A.
- [ ] **RMODE-03**: Remove the now-obsolete boundary cast + BSR-09 follow-up comment in `frontend/src/components/builder/DEMEditorScene.tsx:22-29` (the union now includes `'terrain'`); add/confirm regression coverage that `image`, `hillshade`, and `terrain` DEM render modes each survive the normalizer.

### Label Discoverability (P1)

- [ ] **LABEL-01**: Layer rows in the builder layer list show a derived indicator (small icon/badge) when that layer has labels enabled (`label_config` present + enabled), so a labeled layer (e.g. "ADK 46er peaks") is visually distinct from an unlabeled one (e.g. "Hiking trails"). Pure derivation from layer state (mirror the v1011 `SublayerConfigIndicators` pattern — no new persisted state), with an accessible label and en/de/es/fr i18n parity.

### Builder Polish (P2)

- [ ] **POLISH-01**: The point-layer Style tab exposes a single "Render as" control. Today it renders both a segmented button group (Point/Symbols/Heatmap/Cluster) **and** a redundant "Render as" combobox; line/polygon editors show only the segmented control. Consolidate to the segmented control (or, if the combobox drives a distinct sub-variant, relabel it so it is not a second "Render as").
- [ ] **POLISH-02**: Enabling DEM hillshade on a DEM that is simultaneously bound to a terrain source degrades gracefully — no `backfillBorder` "dem dimension mismatch" console-error spam. Guard the dual-consumer case (reuse the terrain DEM-source tile size for the hillshade consumer, or surface a one-line editor note) rather than letting MapLibre throw. Narrow edge (user-confirmed on Map A; not reproduced on Map B's primary hillshade path).

### Raster Hygiene (P2)

- [ ] **HYG-01**: Bound `_band_stats_cache` in `backend/app/processing/tiles/router.py` with an LRU cap or TTL (currently unbounded — one entry per single-band raster that gets a percentile/stddev tile, evicted only on process restart). Closes the v1032 deferred carry-forward. Backend unit test pins the bound.

### Close-Gate (QA)

- [ ] **QA-01**: Orchestrator-driven Playwright MCP re-verify on both sample maps: Map A fresh load → `getTerrain()` non-null + visible 3D relief; DEM render-as persists across a save+reload; the label indicator is visible on labeled rows and absent on unlabeled rows; layer reorder + visibility toggle work; **0 console errors** on both maps. Evidence (screenshots + console capture) saved under the phase directory.
- [ ] **QA-02**: Code gates green and release paper-trail written — frontend `npm run typecheck` (0), `vitest` (touched suites), `e2e:smoke:builder`, i18n 2/2, backend `pytest` (raster + tile suites), `make openapi-check` (expect **no drift** — the render_mode change is a frontend type only); CHANGELOG entry for v1033.

## v2 / Future Requirements (out of scope for v1033)

### Raster rendering
- **RASTER-STRETCH-03**: Multi-band raster stretch.
- **RASTER-STRETCH-UI-01**: Configurable percentile bounds / σ multiplier for single-band stretch.
- **RASTER-META-01**: Correct `band_count` on the `get_dataset_meta` path (currently shows "1 band" for RGB ortho); fixes the colormap/stretch UI gating signal.

### Test data
- **TESTDATA-01**: Seed a non-DEM single-band raster fixture to enable a genuine stretch/colormap UI spot-check.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multi-band stretch / configurable percentile-σ | Feature work, not related to the terrain/label defects; keep milestone tight (v1032 ethos). |
| Seeding a non-DEM single-band raster fixture | Test-data convenience; not a defect; deferred to Future. |
| `band_count` "1 band" display fix | Peripheral cosmetic; no functional break (colormap correctly hidden for imagery). Logged as RASTER-META-01 Future. |
| Making hillshade fully work on a terrain-bound DEM | MapLibre limitation with non-uniform DEM tiles; POLISH-02 only guards against error spam. Intended Map A state is hillshade hidden + terrain on. |
| CI-01 GitHub Actions billing live-verify | Standing operator ops task; not a code phase (carried since v1023). |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RMODE-01 | Phase 1148 | Pending |
| RMODE-02 | Phase 1148 | Pending |
| RMODE-03 | Phase 1148 | Pending |
| LABEL-01 | Phase 1149 | Pending |
| POLISH-01 | Phase 1150 | Pending |
| POLISH-02 | Phase 1150 | Pending |
| HYG-01 | Phase 1150 | Pending |
| QA-01 | Phase 1151 | Pending |
| QA-02 | Phase 1151 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-29*
*Last updated: 2026-05-29 — traceability populated after roadmap creation*
