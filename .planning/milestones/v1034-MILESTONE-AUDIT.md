---
milestone: v1034
title: Raster Stretch & Colormap Completion
status: tech_debt
audited: 2026-05-30
verdict: CLEAR-TO-TAG (tech_debt — 8/8 reqs satisfied + verified end-to-end live; 2 latent v1031/v1032 defects fixed in-flight)
requirements: 8/8 satisfied
integration: CLEAN (fixture → backend → frontend → close-gate verified live end-to-end)
---

# v1034 Raster Stretch & Colormap Completion — Milestone Audit

## Verdict: `tech_debt` (CLEAR-TO-TAG)

All 8 requirements satisfied and verified. The milestone's intent was to *complete* the raster stretch/colormap feature assuming v1031 (colormap) + v1032 (single-band stretch) already worked. The orchestrator-driven Playwright MCP close-gate (Phase 1155) **disproved that assumption** and fixed two latent, pre-existing defects — so v1034 delivered a *working* raster colormap/stretch feature for the first time.

## Requirement coverage (8/8)

| REQ | Phase | Evidence |
|-----|-------|----------|
| TESTDATA-01 | 1152 | `GRAY_50M_SR.tif` seeded uint8/band_count=1/is_dem=false (DB-verified); idempotent |
| RASTER-STRETCH-03 | 1153/1154 | backend `n_bands=min(band_count,3)` + 3-`rescale=` unit test; multi-band ortho live shows stretch, hides colormap |
| SPIKE-01 | 1153 | live Titiler `p=5&p=95` → `percentile_5/95` (1153-SPIKE.md) |
| RASTER-STRETCH-UI-01 | 1153/1154 | backend pmin/pmax/sigma + cache-key isolation + 422 (66 tests); frontend live: tile URL gains `pmin=5&pmax=95` (200) |
| RASTER-STRETCH-UI-02 | 1154 | stretch↔colormap hint, conditional, vitest-pinned |
| VERIFY-01 | 1155 | live: set stretch/colormap/bounds on fixture → tile URL carries params → save 200 → reload retains; 0 console errors |
| CLEANUP-01 | 1154 | hillshade note + 4 i18n keys removed; live `onRenderModeChange` untouched; dead RasterEditor duplicate eliminated via shared `RasterStretchControls` |
| QA-01 | 1155 | orchestrator MCP close-gate + standard gates green |

## Close-gate findings (the milestone's headline) — fixed in `de9d1f8d`

Two pre-existing defects in v1031/v1032's raster colormap/stretch, invisible to automated tests, surfaced by the live browser gate:

1. **Controls in an unmounted component** — `LayerEditorPanel` mounts `RasterLayerControls` for rasters; the controls lived in `LayerStyleEditor/RasterEditor` (vectors only). Fixed by extracting a shared `RasterStretchControls` rendered by both.
2. **Builder-private paint keys 422'd on save** — `_colormap`/`_stretch`/`_pmin`/`_pmax`/`_sigma` weren't allowlisted → map save rejected, settings never persisted. Fixed by allowlisting into `style_config.builder` (backend) + re-injecting builder→paint on load (frontend).

## Gate results
typecheck 0 · vitest 2621 (238 files) · i18n 2/2 · backend maps+raster 180 · raster/tile 66 · openapi no-drift · sdks clean (regenerated `6bee34cf`) · e2e:smoke:builder 22/1 (the 1 = pre-existing `builder-v1-5 vector-dataset-onto-stack` console-error, raster-unrelated, reproduces independent of v1034).

## Tech debt / carry-forward

| Item | Severity | Note |
|------|----------|------|
| **band_count hydration (RASTER-META-01-adjacent)** | Minor UX | Freshly-added raster layers have `band_count=null` until first save+reload, so the colormap/stretch section appears only after the layer is persisted once. Pre-existing. Candidate: hydrate band_count on the add-layer response. |
| Pre-existing e2e failure | None (not v1034) | `builder-v1-5 vector-dataset-onto-stack` console-error — reproduces independent of v1034. |
| Stray `sigma:3` on QA map `98f89306` | Trivial | Benign (applies only when stretch=stddev); QA artifact. |
| CI-01-v1030 GH Actions billing | Ops (standing) | Unchanged; not a code phase. |

## Migrations
None. Backend change is paint-allowlist logic only (no DDL). `style_config` is opaque jsonb.

## Commits (range f2c06400..HEAD)
Setup (PROJECT/REQUIREMENTS/ROADMAP/research) · phases 1152-1155 · de9d1f8d (close-gate fix) · 75f7f005 (verification) · 15dd2739 (test fix) · this audit.
