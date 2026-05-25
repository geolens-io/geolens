# Phase 1108 Summary: Layer Metadata and Option Fixes

**Status:** Complete
**Requirements closed:** LAYER-01, LAYER-02, LAYER-03, LAYER-04

## Changes

- `frontend/src/lib/normalize-style-config.ts`
  - Preserves render-mode-only configs such as `{ render_mode: "hillshade" }`.
  - Promotes legacy nested `style_config.builder.render_mode` to top-level `render_mode`.
  - Drops `render_mode` from builder metadata after promotion.
- `frontend/src/lib/__tests__/normalize-style-config.test.ts`
  - Added regression pins for render-mode-only and legacy nested render mode inputs.
- `scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py`
  - Writes canonical 46er peak `label_config`.
  - Writes canonical DEM `style_config: {"render_mode": "hillshade"}`.
  - Writes stronger Blue Line outline metadata and canonical water/land outlines.
  - Rerun updated existing maps without duplicating datasets.

## Verification

- `cd frontend && npm run test -- src/lib/__tests__/normalize-style-config.test.ts` → 7 passed.
- `python scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py --append-log` → all 8 datasets skipped as existing, both saved maps updated.
- Playwright MCP verified target-map API/style JSON:
  - DEM layer `style_config.render_mode == "hillshade"`.
  - Exported style JSON includes a `hillshade` layer.
  - 46er peak style JSON includes a companion `-label` symbol layer with `text-field: ["get", "name"]`.
  - DEM editor opens as `DEM · HILLSHADE`.
