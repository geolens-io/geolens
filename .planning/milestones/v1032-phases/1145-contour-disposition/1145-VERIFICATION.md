---
phase: 1145
phase_name: Contour Disposition
status: passed
verified: 2026-05-28
requirements: [CONTOUR-02]
disposition: CUT
method: code removal + typecheck + vitest + i18n parity + live Playwright MCP
---

# Phase 1145 Verification — Contour Disposition (CUT)

**Status: passed** — contour control cut cleanly per the Phase 1144 spike recommendation. No half-wired state remains.

## Success Criteria (cut branch)

1. **`maplibre-contour` dependency removed** — ✅ `frontend/package.json` line removed; `npm install` removed 1 package; `package-lock.json` −7 lines; `grep -c maplibre-contour package-lock.json` = 0.
2. **Code removed** — ✅
   - `contour-sync.ts` + `__tests__/contour-sync.test.ts` deleted.
   - `map-sync.ts`: `syncContourLayer` import + call removed (kept `is_dem` block + `syncColorReliefLayer`).
   - `DEMEditorScene.tsx`: `CONTOUR_CONTROL_ENABLED` flag + doc comment + the gated CONTOUR LINES `<section>` removed; hypso section renumbered 4→3.
   - Dead `relief-contour` removed from `map-stack.ts` (`MapStackRole` union + the unreachable `mode === 'contour'` branch — `'contour'` was never in the StyleConfig `render_mode` union) + stale "contour companion" comment in `map-sync.ts` removed + "contours" dropped from the relief group description.
   - `map-sync.raster.test.ts`: contour-sync mock + `syncContourLayer wiring` describe block removed (kept color-relief).
   - 5 dormant `it.skip` tests removed from `DEMEditorScene.test.tsx`.
   - i18n: 5 contour keys removed from all 4 locales (en/de/es/fr).
3. **Positive regression pin (surface stays gone)** — ✅ 3 `DEMEditorScene.test.tsx` tests assert `queryByText('CONTOUR LINES')` absent in image/hillshade/terrain modes (relabeled as permanent cut pins). **Live-confirmed** via Playwright MCP: DEM editor in hillshade mode shows `hasContourLines:false`, `hasHypsometric:true`, `hasSunPosition:true`.
4. **typecheck + vitest pass** — ✅ `tsc -b --noEmit` exit 0; affected tests 70/70 (DEMEditorScene 28, map-sync.raster 31, map-stack 11); i18n parity 2/2.

## Live verification (orchestrator Playwright MCP)

- Map `8dd6a129…` reloads with **0 console errors** post-cut; DEM map renders (map-sync call-site removal is safe).
- DEM editor → Hillshade: no CONTOUR LINES section; HYPSOMETRIC TINT + SUN POSITION intact; **0 console errors** on the mode switch.

## Human verification needed

None — cut verified by tests + live MCP.
