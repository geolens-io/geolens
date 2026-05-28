---
phase: 1136-per-render-mode-editor-polish
plan: "06"
subsystem: testing
tags: [builder, pitfall-9, grep-guard, i18n-parity, vitest, de, es, fr]

# Dependency graph
requires:
  - phase: 1136-per-render-mode-editor-polish/plan-01
    provides: RasterEditor (Pitfall #9 clean, no setPaintProperty)
  - phase: 1136-per-render-mode-editor-polish/plan-02
    provides: LineEditor Cap/Join Selects + English lineEnds/lineCap/lineJoin stubs in de/es/fr
  - phase: 1136-per-render-mode-editor-polish/plan-03
    provides: FillEditor extrusionRange hint + en key
  - phase: 1136-per-render-mode-editor-polish/plan-04
    provides: BasemapGroupEditorScene noBasemap card + de/es/fr translations for noBasemap + extrusionRange
  - phase: 1136-per-render-mode-editor-polish/plan-05
    provides: BasemapSublayerEditorScene regression pin (production file unchanged)

provides:
  - Phase 1136 EDITOR Pitfall #9 grep guard (10 tests, 5 files x 2 properties) as executable CI test
  - 9 translated lineEnds/lineCap/lineJoin keys in de, es, fr (27 translation entries)
  - i18n parity green across en/de/es/fr for all Phase 1136 keys

affects:
  - 1136-07 (MCP smoke verification — i18n parity contract now maintained)
  - 1139-quality-sweep (QA-03 i18n parity gate)
  - Any future plan modifying the 5 watched editor files (CI fail if Pitfall #9 regresses)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vite ?raw imports for source-file grep guard (avoids @types/node dependency in tsconfig.app.json)"
    - "it.each with object array ({ name, src }) for descriptive test names without fs.readFileSync"

key-files:
  created:
    - frontend/src/components/builder/__tests__/pitfall-9-editor-polish.test.ts
  modified:
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "?raw imports over node:fs readFileSync — tsconfig.app.json does not include node types; ?raw is the established project pattern (preserve-drawing-buffer.test.ts)"
  - "it.each with object array (name + src) provides descriptive test names showing the short relative filename rather than the full object stringification"
  - "Plan 04 had already translated extrusionRange and noBasemap in de/es/fr (Rule 3 auto-fix); Plan 06 only needed to replace the 9 English stubs for lineEnds keys"

patterns-established:
  - "Vite ?raw grep guard pattern: import src as string, strip comments, regex-match — works without @types/node, aligned with tsconfig.app.json constraints"

requirements-completed:
  - EDITOR-RASTER-01
  - EDITOR-RASTER-02
  - EDITOR-RASTER-03
  - EDITOR-RASTER-04
  - EDITOR-LINE-01
  - EDITOR-LINE-02
  - EDITOR-FILL-04
  - EDITOR-BASEMAP-02

# Metrics
duration: 4min
completed: 2026-05-27
---

# Phase 1136 Plan 06: Pitfall #9 Grep Guard + i18n Parity Sweep Summary

**Pitfall #9 grep guard installed as a 10-test Vite ?raw CI gate, and 9 English lineEnds/lineCap/lineJoin stubs replaced with real de/es/fr translations — i18n parity green across all 4 locales**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-27T20:55:24Z
- **Completed:** 2026-05-27T20:59:07Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `pitfall-9-editor-polish.test.ts` with 10 tests (5 files × 2 properties) using Vite `?raw` imports — no `@types/node` dependency needed
- `stripComments` helper drops `/* */` block comments and `// line` comments before regex matching — confirmed QA self-check: adding a `// map.setPaintProperty(...)` comment to RasterEditor still passes 10/10
- All 9 `lineEnds`, `lineCap`, `lineCapButt`, `lineCapRound`, `lineCapSquare`, `lineJoin`, `lineJoinBevel`, `lineJoinRound`, `lineJoinMiter` English stubs replaced with canonical de/es/fr translations
- `extrusionRange` and `noBasemap` were already properly translated by Plan 04 auto-fix — Plan 06 only had 9 keys to replace
- En-dash (U+2013) preserved in all 4 locales for `extrusionRange`
- `npm run test:i18n` parity gate: 2/2 pass; all 4 locale JSON files valid

## Task Commits

1. **Task 1: Pitfall #9 phase-scoped grep guard vitest** — `cf58636e` (test)
2. **Task 2: Translate 9 lineEnds/lineCap/lineJoin keys to de/es/fr** — `03043b67` (feat)

## Files Created/Modified

- `frontend/src/components/builder/__tests__/pitfall-9-editor-polish.test.ts` — New file: Vite `?raw` imports of 5 editor files; `stripComments` helper; `it.each(WATCHED)` for 10 assertions
- `frontend/src/i18n/locales/de/builder.json` — Replaced 9 English stubs with German: Linienenden, Ende, Stumpf, Rund, Quadratisch, Verbindung, Abgeschrägt, Rund, Spitz
- `frontend/src/i18n/locales/es/builder.json` — Replaced 9 English stubs with Spanish: Extremos de línea, Extremo, Plano, Redondo, Cuadrado, Unión, Biselado, Redondo, Inglete
- `frontend/src/i18n/locales/fr/builder.json` — Replaced 9 English stubs with French: Extrémités de ligne, Extrémité, Plat, Rond, Carré, Jointure, Biseauté, Rond, Onglet

## Decisions Made

- Used Vite `?raw` imports instead of `node:fs` + `readFileSync` — tsconfig.app.json does not include `node` types, so `import { readFileSync } from 'node:fs'` causes TS2591 (`Cannot find name 'node:fs'`). The `?raw` pattern is already established in `preserve-drawing-buffer.test.ts`.
- Used `it.each` with object array `{ name, src }` for descriptive test names (displays the short filename) rather than parallel array of just filenames.
- Plan 06 only translated 9 keys (lineEnds family) — Plan 04 had already auto-fixed extrusionRange + noBasemap in de/es/fr as a Rule 3 blocking fix, so those 2 key sets were already properly translated.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Switched from node:fs to Vite ?raw imports**
- **Found during:** Task 1 — typecheck run after creating the test file
- **Issue:** `import { readFileSync } from 'node:fs'` produced TS2591 + TS2304 (`__dirname`) errors because tsconfig.app.json does not have `node` in its `types` array
- **Fix:** Rewrote test to use Vite `?raw` imports (the established pattern in `preserve-drawing-buffer.test.ts`) and `it.each(WATCHED)` with `{ name, src }` pairs
- **Files modified:** `pitfall-9-editor-polish.test.ts`
- **Verification:** `npm run typecheck` exits 0; `npm test -- pitfall-9-editor-polish --run` passes 10/10
- **Committed in:** `cf58636e`

---

**Total deviations:** 1 auto-fixed (Rule 1 - adapted to project's established test pattern)
**Impact on plan:** No scope change; the fix aligns the test with the project's existing `?raw` grep guard pattern.

## Pitfall Compliance

- **Pitfall #9 guard installed:** `pitfall-9-editor-polish.test.ts` executes in CI; 10/10 pass on current codebase; any future plan adding a direct callsite to the 5 watched files will fail the build
- **BuilderActionSource + BuilderLayerAction:** `git diff frontend/src/components/builder/builder-action-contract.ts` → empty (unchanged)
- **Production code:** Zero production source files modified in this plan (only test file + locale JSONs)

## Test Counts

- `pitfall-9-editor-polish.test.ts`: 10/10 (new file — 5 files × 2 properties)
- `resources.test.ts` (i18n parity): 2/2 pass

## Issues Encountered

Minor: `node:fs` approach required switching to `?raw` pattern (auto-fixed inline per Rule 1).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 8 requirements (EDITOR-RASTER-01..04, EDITOR-LINE-01..02, EDITOR-FILL-04, EDITOR-BASEMAP-02) are now closed by Plans 01-06
- Plan 07 (MCP smoke verification) can proceed on live `localhost:8080`
- ROADMAP Phase 1139 QA-03 i18n parity contract is maintained

## Self-Check: PASSED

- `frontend/src/components/builder/__tests__/pitfall-9-editor-polish.test.ts`: FOUND
- `frontend/src/i18n/locales/de/builder.json` lineEnds/lineCap/lineJoin: German translations confirmed
- `frontend/src/i18n/locales/es/builder.json` lineEnds/lineCap/lineJoin: Spanish translations confirmed
- `frontend/src/i18n/locales/fr/builder.json` lineEnds/lineCap/lineJoin: French translations confirmed
- Commit `cf58636e`: FOUND
- Commit `03043b67`: FOUND

---
*Phase: 1136-per-render-mode-editor-polish*
*Completed: 2026-05-27*
