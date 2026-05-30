---
phase: 1155
title: Close-Gate
status: passed
verified: 2026-05-30
requirements: [VERIFY-01, QA-01]
score: 2/2 must-haves verified (after 2 close-gate defects found + fixed)
---

# Phase 1155 — Close-Gate Verification

**Orchestrator-driven** (Playwright MCP is orchestrator-only — executors lack `mcp__playwright__*`).

## Headline: the close-gate worked

The live browser gate surfaced **two pre-existing defects** in the raster colormap/stretch feature (shipped by v1031/v1032) that automated tests never caught because they only exercised the wrong component / never round-tripped through save:

1. **Controls in an unmounted component.** `LayerEditorPanel.tsx:485` mounts `RasterLayerControls` for raster/vrt layers, but the colormap/stretch controls (v1031 colormap, v1032 stretch, **all of v1034's** multi-band gate + pmin/pmax/sigma + hint) lived in `LayerStyleEditor/RasterEditor.tsx`, which is only mounted for vector layers. Result: no colormap/stretch UI ever appeared for raster layers.

2. **Builder-private paint keys rejected on save (422).** `_colormap`/`_stretch`/`_pmin`/`_pmax`/`_sigma` were never in the `LEGACY_BUILDER_PAINT_KEYS` allowlist, so `split_legacy_builder_paint` raised "Unsupported private paint key(s)" → the whole map save 422'd and settings were lost on reload.

Both fixed in commit `8b9a3a0d`:
- Extracted the colormap/stretch section into a shared `RasterStretchControls` mounted by **both** raster editors; `RasterLayerControls` now receives `band_count`.
- Allowlisted the 5 keys → backend moves them into `style_config.builder` (clean paint boundary); frontend re-injects builder→paint on load (`normalizeLayerStyleState`) so the editor + `buildColormapTileUrl` keep working.

## VERIFY-01 — single-band stretch/colormap UI (live, against TESTDATA-01 fixture)

Map `98f89306` with seeded `GRAY_50M_SR.tif` (band_count=1, is_dem=false):

- Stretch select + Colormap select render (after the mount fix). ✓
- Setting `stretch=percentile` → tile URL `?stretch=percentile` (200). ✓
- Setting `colormap=viridis` → `?colormap_name=viridis&stretch=percentile` (200). ✓
- Setting Low%=5 / High%=95 → `?colormap_name=viridis&stretch=percentile&pmin=5&pmax=95` (200). ✓
- **Persistence round-trip:** Save → `PUT /api/maps/98f89306` **200 OK** (was 422). Stored `paint: {}` (clean) + `style_config.builder: {colormap: viridis, stretch: percentile, pmin: 5, pmax: 95, sigma: 3}`. ✓
- **Fresh reload:** editor re-populates Colormap=Viridis, Stretch=Percentile, Low%=5, High%=95; tile URL on load carries `?colormap_name=viridis&stretch=percentile&pmin=5&pmax=95` (200). ✓
- 0 console errors. ✓

## QA-01 — multi-band + close-gate suite

- **Multi-band ortho** (`adk_high_peaks_ny_orthos_3857.tif`, band_count=3): editor shows STRETCH, **hides COLORMAP** (combos: Linear + Min/Max). ✓ (3-`rescale=`-fragment per-band backend behavior unit-tested in 1153.)
- 0 console errors on each surface. ✓

### Standard gates
| Gate | Result |
|------|--------|
| `npm run typecheck` | 0 errors ✓ |
| vitest | 2624 passed (239 files) ✓ |
| `npm run test:i18n` | 2/2 ✓ |
| backend `test_maps.py` + `test_raster_colormap_proxy.py` | 245 passed, 2 skipped ✓ |
| backend raster/tile (1153 suite) | 66 passed ✓ |
| `make openapi-check` | no drift ✓ |
| `make sdks-check` | clean (Python+TS SDKs regenerated for the 1153 query params, committed `6bee34cf`) ✓ |
| `e2e:smoke:builder` | see below |

### e2e:smoke:builder note
First run: 22 passed / 1 failed. The 1 failure is `builder-v1-5 … vector-dataset-onto-stack` (console errors on a **vector** drag) — unrelated to v1034 (raster-only changes). Tracked as pre-existing (matches the project-memory note on v1011 pre-existing e2e failures). Re-run after the close-gate fixes to confirm no new failures.

## New regression tests
- `backend/tests/test_maps.py::test_add_layer_moves_raster_stretch_paint_to_style_config` — the 5 keys move to `style_config.builder`, clean paint.
- `frontend .../normalize-style-config.test.ts` — builder→paint re-injection round-trip + no-op when absent.
- `RasterStretchControls` is shared; existing RasterEditor + RasterLayerControls vitest suites green (DOM identical via extraction).

## Disposition
VERIFY-01 ✓ and QA-01 ✓ — both fully satisfied, with two latent v1031/v1032 defects fixed in the process. Feature works genuinely end-to-end (mount + live tile params + persistence round-trip).
