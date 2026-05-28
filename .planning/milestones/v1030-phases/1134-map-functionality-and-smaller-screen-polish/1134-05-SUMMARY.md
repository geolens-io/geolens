---
phase: 1134-map-functionality-and-smaller-screen-polish
plan: 05
subsystem: ui
tags: [builder, notes, i18n, scroll-containment, regression-pin, tailwind]

requires:
  - phase: 1134-04
    provides: prior MAP requirement closures in the same phase

provides:
  - MAP-22: Notes rail button presence dot (6px bg-primary, -top-0.5 -right-0.5) when notes.trim().length > 0
  - MAP-19: Static scroll-containment regression pin via Vite ?raw source assertions
  - i18n key rail.notesPresent in 4 locales (en/de/es/fr)

affects:
  - 1134-06 (Plan 06 Playwright MCP live verification of MAP-19 scroll behavior)
  - BuilderRail consumers (dot visible on any non-whitespace notes)

tech-stack:
  added: []
  patterns:
    - "Vite ?raw import pattern for source-text regression pins (no node:fs / @types/node)"
    - "Presence dot via absolute-positioned span on relative button container"

key-files:
  created:
    - frontend/src/components/builder/__tests__/BuilderMap.scroll.test.tsx
  modified:
    - frontend/src/components/builder/BuilderRail.tsx
    - frontend/src/components/builder/__tests__/BuilderRail.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Use Vite ?raw imports for scroll-containment source-text tests (not node:fs) — project-established pattern in preserve-drawing-buffer.test.ts and ActiveFilterChips.test.tsx"
  - "Notes dot is static (no animation) per UI-SPEC — it is a state indicator, not a notification"
  - "MAP-19 live scroll verification (page body scrollY === 0) deferred to Plan 06 Playwright MCP"

patterns-established:
  - "Presence indicator: conditional span with absolute positioning inside a relative button — exact pattern per UI-SPEC §Notes Presence Indicator"

requirements-completed:
  - MAP-19
  - MAP-22

duration: 4min
completed: 2026-05-27
---

# Phase 1134 Plan 05: Notes Presence Dot + MAP-19 Scroll Pin Summary

**6px primary-color presence dot on Notes rail button (MAP-22) + static scroll-containment regression pin via ?raw source assertions (MAP-19), with rail.notesPresent i18n key in 4 locales**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-27T16:37:00Z
- **Completed:** 2026-05-27T16:40:30Z
- **Tasks:** 2
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments

- MAP-22: Notes rail button shows a 6px `bg-primary` dot at `-top-0.5 -right-0.5` when `notes.trim().length > 0`; absent for empty or whitespace-only notes; dot has `aria-label` via i18n key `rail.notesPresent`
- i18n parity: `rail.notesPresent` added to en/de/es/fr builder.json ("Map has notes" / "Karte hat Notizen" / "El mapa tiene notas" / "La carte a des notes")
- MAP-19: `BuilderMap.scroll.test.tsx` pins (1) outer wrapper has no overflow class near `data-builder-canvas`, (2) `MapBuilderPage` map column has `min-h-0 min-w-0`, (3) MapGL fills wrapper with `style={{ width: '100%', height: '100%' }}`, (4) documentation test as future-failure notice

## Task Commits

1. **Task 1: BuilderRail Notes presence dot + i18n key** - `50c8671f` (feat)
2. **Task 2: MAP-19 BuilderMap scroll containment regression pin** - `1a6b189c` (test)

## Files Created/Modified

- `frontend/src/components/builder/BuilderRail.tsx` — Added `relative` class to rail buttons, conditional presence dot span inside Notes button gated on `notes.trim().length > 0`
- `frontend/src/components/builder/__tests__/BuilderRail.test.tsx` — Extended with `within` import + 3 MAP-22 tests (presence/absence/negative-control)
- `frontend/src/components/builder/__tests__/BuilderMap.scroll.test.tsx` — New 4-test file using Vite `?raw` imports to pin scroll-containment source invariants
- `frontend/src/i18n/locales/en/builder.json` — Added `rail.notesPresent: "Map has notes"`
- `frontend/src/i18n/locales/de/builder.json` — Added `rail.notesPresent: "Karte hat Notizen"`
- `frontend/src/i18n/locales/es/builder.json` — Added `rail.notesPresent: "El mapa tiene notas"`
- `frontend/src/i18n/locales/fr/builder.json` — Added `rail.notesPresent: "La carte a des notes"`

## Decisions Made

- Used `Vite ?raw` imports instead of `node:fs` for source-text assertions in `BuilderMap.scroll.test.tsx` — project-established pattern from `preserve-drawing-buffer.test.ts` and `ActiveFilterChips.test.tsx`. This avoids `@types/node` dependency in `tsconfig.app.json`.
- MAP-19 live scroll verification (page body `scrollY === 0` during canvas pan/zoom) is reserved for Plan 06's Playwright MCP step; the Plan 05 scope is the static source pin only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Rewrote BuilderMap.scroll.test.tsx to use Vite ?raw imports**
- **Found during:** Task 2 (typecheck after creating the test file)
- **Issue:** Original plan showed `import fs from 'node:fs'` + `__dirname` — these require `@types/node` in `tsconfig.app.json`, which is not present. Typecheck reported 5 TS errors (Cannot find name 'node:fs', 'node:path', '__dirname').
- **Fix:** Rewrote imports to `import builderMapSrc from '../BuilderMap.tsx?raw'` and `import mapBuilderPageSrc from '../../../pages/MapBuilderPage.tsx?raw'`. Simplified test assertions to operate on the imported string directly. This matches the existing project pattern in `preserve-drawing-buffer.test.ts` and `ActiveFilterChips.test.tsx`.
- **Files modified:** `frontend/src/components/builder/__tests__/BuilderMap.scroll.test.tsx`
- **Verification:** `npm run typecheck` exits 0; all 4 tests pass
- **Committed in:** `1a6b189c`

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: incompatible import pattern)
**Impact on plan:** Fix was necessary to maintain typecheck parity. Test behavior and assertions are unchanged — only the file-reading mechanism was updated to the project's established pattern.

## Issues Encountered

None beyond the import pattern fix documented above.

## Cross-references

- UI-SPEC §Notes Presence Indicator: 6px filled circle, `bg-primary`, `-top-0.5 -right-0.5`, `size-1.5`, no animation
- UI-SPEC §IC-05 (Map container scroll isolation): `overflow-auto`/`overflow-scroll` must not appear on BuilderMap ancestor chain
- Plan 06: Live Playwright MCP verification of MAP-19 scroll behavior at 800×600 and 414×896

## Known Stubs

None — all changes are complete implementations or regression pins with no placeholder data.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check

- [x] `frontend/src/components/builder/BuilderRail.tsx` exists and contains `notes.trim().length > 0`
- [x] `frontend/src/components/builder/__tests__/BuilderRail.test.tsx` exists with 8 tests
- [x] `frontend/src/components/builder/__tests__/BuilderMap.scroll.test.tsx` exists with 4 tests
- [x] All 4 locale builder.json files contain `notesPresent`
- [x] Commits `50c8671f` (feat) and `1a6b189c` (test) exist
- [x] `npm run typecheck` exits 0
- [x] Combined test run: 12/12 pass

## Self-Check: PASSED

## Next Phase Readiness

Plan 06 (Playwright MCP live verification) can proceed:
- MAP-22 dot is live in the builder rail — any notes with non-whitespace text will show the dot
- MAP-19 static pin is in place; live scroll test at 800×600 and 414×896 is the remaining verification gate

---
*Phase: 1134-map-functionality-and-smaller-screen-polish*
*Completed: 2026-05-27*
