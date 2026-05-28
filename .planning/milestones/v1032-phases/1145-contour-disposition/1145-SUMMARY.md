---
phase: 1145
phase_name: Contour Disposition
status: complete
requirements: [CONTOUR-02]
disposition: CUT
completed: 2026-05-28
---

# Phase 1145 Summary — Contour Disposition (CUT)

Executed the Phase 1144 spike recommendation: **cut the contour control** (no compatible `maplibre-contour` upstream fix; harden not clearly cheap; contour is nice-to-have).

## Files changed
- **Deleted:** `contour-sync.ts`, `__tests__/contour-sync.test.ts`.
- **`package.json` / `package-lock.json`:** removed `maplibre-contour` (−7 lockfile lines, `npm install` removed 1 package).
- **`map-sync.ts`:** removed `syncContourLayer` import + call (kept `is_dem` block + `syncColorReliefLayer`); removed stale contour-companion comment.
- **`DEMEditorScene.tsx`:** removed `CONTOUR_CONTROL_ENABLED` flag + doc comment + the gated CONTOUR LINES `<section>`; renumbered hypso section comment.
- **`map-stack.ts`:** removed dead `relief-contour` `MapStackRole` member + the unreachable `mode === 'contour'` branch; dropped "contours" from the relief group description.
- **`map-sync.raster.test.ts`:** removed the contour-sync mock + `syncContourLayer wiring` describe block (kept color-relief).
- **`DEMEditorScene.test.tsx`:** removed 5 dormant `it.skip` tests; relabeled the 3 absence tests as permanent cut regression pins.
- **i18n:** removed 5 contour keys from en/de/es/fr `builder.json`.

## Verification
typecheck 0; affected vitest 70/70; i18n parity 2/2; live MCP — DEM editor hillshade shows no CONTOUR LINES, hypso + sun-position intact, 0 console errors.

## Notes
- `'contour'` was never a StyleConfig `render_mode` (it was a paint-level `_contour-enabled` boolean), so the `map-stack.ts` `relief-contour` mapping was always dead code — removed for a clean cut.
- Contour as a future feature on a maintained approach remains recorded in REQUIREMENTS.md Out of Scope.
