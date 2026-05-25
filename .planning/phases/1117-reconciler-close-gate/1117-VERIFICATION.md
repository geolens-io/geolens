# Phase 1117 Verification

**Completed:** 2026-05-25
**Status:** Pass

## Automated Gates

```bash
cd frontend && npm run test -- src/components/builder/__tests__/layer-adapters.test.ts src/components/builder/layer-adapters/__tests__/shared.test.ts src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts src/components/builder/__tests__/ChatPanel.test.tsx src/components/builder/hooks/__tests__/use-builder-save.test.ts src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx src/components/builder/__tests__/StyleJsonDialog.test.tsx src/components/builder/__tests__/BuilderMap.a11y.test.tsx
```

**Result:** Pass — 8 files, 198 tests.

```bash
cd frontend && npm run typecheck
cd frontend && npm run lint
cd backend && uv run pytest tests/test_phase_275_api_style.py tests/test_map_sprites.py tests/test_ai_style_validation.py
cd backend && uv run ruff check app/modules/catalog/maps/router.py tests/test_phase_275_api_style.py tests/test_map_sprites.py tests/test_ai_style_validation.py
make openapi-check
make sdks-check
```

**Result:** Pass.

## Playwright MCP UAT

Target: `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd`

Verified:

- Hiking trails `Gradient` adds live `line-gradient`; switching back to `Solid color` removes `line-gradient` and leaves scalar `line-color`.
- Hiking trails data-driven `facility` style changes live `line-color` to an expression; `Clear data-driven style` restores scalar `line-color` and no `line-gradient`.
- ADK 46er peaks `Labels` render mode switches the parent layer to `symbol`, registers the GeoLens sprite via `/api/maps/sprites/geolens`, then switches back to `circle` for `Point`.
- GeoLens high-DPI sprite routes return 200 for `/api/maps/sprites/geolens@2x.json` and `/api/maps/sprites/geolens@2x.png`.
- Terrain is active on the fresh target map: `getTerrain()` returns `{ source: "terrain-dem", exaggeration: 2.4 }`, and `terrain-dem` is a `raster-dem` source.
- Browser console capture after UAT: 0 errors, 0 warnings.
- Network capture: no unexpected API/sprite failures. Observed raster tile `net::ERR_ABORTED` entries were expected browser cancellations during style/terrain transitions.
- Screenshot captured locally at `phase-1117-adk-mapbuilder-polished.png` (ignored by git).

## Observations

- Vitest emitted existing `--localstorage-file` warnings and one jsdom canvas `getContext()` notice; they did not affect assertions.
- Backend `uv` emitted the existing virtualenv-path warning; tests and Ruff passed.
