# Phase 1143 — Live Playwright MCP Close-Gate Evidence (QA-01)

**Date:** 2026-05-28
**Driver:** Orchestrator (GSD subagents lack `mcp__playwright__*`)
**Target:** `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd` — "Adirondack High Peaks — 3D Relief" (10 layers: 7 vector, single-band raster, multi-band aerial raster, DEM/terrain raster). Authenticated admin session; stack healthy (db 5434, api 8001, frontend 8080, titiler).

## Results

| Check | Control | Result |
|-------|---------|--------|
| Builder loads target map | — | PASS — all 10 layers, no load errors |
| DEM editor opens; RENDER AS Image/Hillshade/Terrain | — | PASS |
| Render-mode gating | DEM editor | PASS — CONTOUR/HYPSOMETRIC sections appear only in hillshade; "No additional controls" in image mode |
| **Contour (EDITOR-DEM-04)** | DEM | **BUG FOUND → FIXED → DEFERRED.** Enabling contour threw `TypeError: maplibre.addProtocol is not a function` (setupMaplibre was passed the Map instance, not the maplibre-gl module; no-op test mock had hidden it). Fixed `716b1927` (pass `{ addProtocol }` named export + regression test). Re-verify: addProtocol error gone, BUT enabling then emitted ~28 MapLibre `error` events from the maplibre-contour worker/isoline stage (NOT auth — DEM tiles 200 OK; NOT encoding — `'mapbox'` matches the working hillshade source). Worker integration needs hardening → **DEM-04 deferred to v1032** (UI gated off `CONTOUR_CONTROL_ENABLED=false`, `21feaf7f`). |
| Hypsometric tint (EDITOR-DEM-05) | DEM hillshade | PASS — HYPSOMETRIC TINT section + Elevation tint toggle present; native `color-relief` reuses the already-authed raster-dem source (no worker re-fetch). Code-level: 88 unit tests; live section confirmed. |
| Raster colormap (EDITOR-RASTER-COLORMAP) | single-band raster | Code-verified (72 tests) — COLORMAP section gated on `band_count===1`; multi-band aerial shows none; tiles re-render via `buildColormapTileUrl` URL-diff through the authed map source. |
| Fill-pattern (EDITOR-FILL-01) | polygon | Code-verified (148 tests) — built-in pattern picker mirrors IconPicker; set/clear via owned `fill-pattern`. |
| OG social cards (SHARE-08) | share | Backend route + escaping + access-control + og-image routes pinned by 22 backend tests incl. 2 BLOCKING security tests; `og_image_url` present in live map API response. |
| Console hygiene | builder | PASS (pre-contour-gate): no errors on load / DEM editor / hypsometric. The 28 errors were contour-only and are now gated out. |

## Disposition
- **3/4 render-mode controls shipped + verified** (hypsometric, colormap, fill-pattern) + OG cards + SharePanel typography.
- **DEM-04 contour deferred to v1032** — see REQUIREMENTS.md + CHANGELOG "Deferred to v1032".
- The live close-gate did its job: caught a runtime bug (addProtocol) that all headless gates missed, and surfaced the worker-integration gap before shipping a broken control.
