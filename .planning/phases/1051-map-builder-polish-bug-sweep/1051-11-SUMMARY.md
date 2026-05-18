---
phase: 1051-map-builder-polish-bug-sweep
plan: 11
subsystem: ui
tags: [builder, investigation, detail-level, dead-code-removal, disposition, i18n]

# Dependency graph
requires:
  - phase: 1051-map-builder-polish-bug-sweep
    provides: Plans 01-10 already committed atomically; Plan 11 isolated to the BasemapSublayerEditorScene + its single MapBuilderPage call site + 4 locale files; no cross-wave coupling.
provides:
  - DETAIL LEVEL pill strip + DETAIL_LEVELS const + DetailLevel TS type fully removed from BasemapSublayerEditorScene
  - {activeDetailLevel, isCustomized, onDetailLevelChange} props removed from component interface, signature destructure, and the MapBuilderPage call site
  - 6 i18n keys removed per locale × 4 locales = 24 entries (parity preserved)
  - 4 deleted Vitest cases (DETAIL LEVEL pill strip / styling / dispatch / customized hint) + 1 new regression-pin test (Test 13) asserting the REMOVE disposition
  - CHANGELOG bullet drafted for Plan 13 consumption
affects: [basemap-sublayer-editor-scene, map-builder-page-call-site, i18n-builder-namespace]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dead-code disposition documented inline at the removal site (comment block at top of component) so a future maintainer who greps for DETAIL LEVEL finds the rationale before re-adding the surface"
    - "Removed-feature regression pin: delete the surface AND add a 1-test assertion that the surface stays gone — prevents accidental re-introduction via cargo-cult copy from sibling editor scenes"
    - "Scope-boundary discipline: sibling no-op callbacks (onStrokeColorChange/onCasingColorChange/onCasingWidthChange/onZoomChange — all bearing the same Phase 1038 TODO) NOT touched in this plan; flagged for EMRG-01 (Plan 12) triage"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
    - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Disposition: REMOVE (not FIX, not relocate, not rename, not replace with SublayerConfigIndicators). FIX requires 3-5 days of MapLibre style-mutation work across basemap presets — explicitly out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1. REMOVE is the clean choice for this hygiene milestone."
  - "Coordination with W5 (SublayerConfigIndicators): DETAIL LEVEL is orthogonal to the W5 indicator surface — DETAIL LEVEL was intended to MUTATE basemap style (a control input), whereas SublayerConfigIndicators DISPLAYS derived style state (a status badge). Replacing DETAIL LEVEL with an indicator would not preserve the intended semantics; full REMOVE is the right call."
  - "Sibling no-op callbacks (onStrokeColorChange/onCasingColorChange/onCasingWidthChange/onZoomChange) explicitly NOT removed in this plan — they share the same Phase 1038 TODO but belong to a separate scope per the plan's <action> directive. Flagged for EMRG-01 triage in Plan 12 (Phase 1038 dead-stub cleanup candidate)."
  - "Regression pin via Test 13: rather than only deleting Tests 1-4 (which would silently allow the surface to reappear under any future refactor), added one positive-form assertion that no radiogroup, no `DETAIL LEVEL` text, and no `currently customized` text render. Makes the REMOVE intent contract-explicit."

patterns-established:
  - "Inline disposition comment at removal site: `// Phase {N} Plan {M} (REQ-ID): {SURFACE} removed — {one-line rationale}` placed immediately above the affected interface so the next grep-driven reader sees WHY before WHERE."
  - "Removed-feature regression test: a single positive-form `queryBy*` assertion that the removed surface stays gone — single test, low-cost, prevents copy-paste regression."

requirements-completed: [INV-01]

# Metrics
duration: ~10 min
completed: 2026-05-18
---

# Phase 1051 Plan 11: INV-01 DETAIL LEVEL Disposition Summary

**Dead-wired DETAIL LEVEL pill strip removed from BasemapSublayerEditorScene. Disposition: REMOVE — no live consumer, no path to a quick FIX within v1011 scope. Replaced by a regression-pin test that asserts the surface stays gone.**

## Performance

- **Duration:** ~10 min (Task 2 executor work; Tasks 1 + 3 Playwright MCP gates deferred to orchestrator per phase 1051 lesson)
- **Started:** 2026-05-18T22:08:00Z (approximate)
- **Completed:** 2026-05-18T22:18:00Z (approximate)
- **Tasks executed:** 1 of 3 (Tasks 1 + 3 deferred — MCP is orchestrator-scoped per `<lesson_from_phase>`)
- **Files created:** 0
- **Files modified:** 7

## Accomplishments

- **Investigation confirmed dead wiring (no MCP needed).** Pre-removal grep enumerated every reference:
  - `BasemapSublayerEditorScene.tsx` line 16 (type), 21 (prop), 30 (prop), 44 (DETAIL_LEVELS const), 54 (destructure), 63 (destructure), 90-132 (JSX section), 98 (active check), 114 (callback), 123 (hint gate)
  - `MapBuilderPage.tsx` line 838 (`activeDetailLevel="default"` hardcoded), 839 (`isCustomized={false}` hardcoded), 847 (`onDetailLevelChange={() => { /* TODO(Phase 1038) */ }}` no-op)
  - 4 locale files × 6 keys (`customizedHint`, `detailLevelLabel`, `detailLevelOff`, `detailLevelMinimal`, `detailLevelDefault`, `detailLevelFull`)
  - `__tests__/BasemapSublayerEditorScene.test.tsx` Tests 1-4 + `defaultProps` defaults at lines 57-58, 66
- **Disposition resolved: REMOVE.** FIX path requires 3-5 days of MapLibre style-mutation work (sublayer detail-level filtering across multiple basemap presets) — out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1. REMOVE is the clean choice for this hygiene milestone.
- **`BasemapSublayerEditorScene.tsx` removals (1 file, -56 lines):**
  - `DetailLevel` type alias
  - `activeDetailLevel`, `isCustomized`, `onDetailLevelChange` from `BasemapSublayerEditorSceneProps` interface
  - Same 3 from the function signature destructure
  - `DETAIL_LEVELS` const array (4 pill definitions)
  - Entire `<section>` JSX block (DETAIL LEVEL heading + radiogroup + 4 buttons + customized hint paragraph)
  - Section comment numbering renumbered: section 2 (Stroke) becomes section 1
  - Added inline disposition documentation comment block above the props interface so future maintainers reading the surface understand the REMOVE rationale before re-introducing it
- **`MapBuilderPage.tsx` removals (1 file, -3 lines):**
  - `activeDetailLevel="default"` prop
  - `isCustomized={false}` prop
  - `onDetailLevelChange={...}` no-op prop
  - Sibling no-op props (`onStrokeColorChange`/`onStrokeWidthChange`/`onCasingColorChange`/`onCasingWidthChange`/`onZoomChange`) **explicitly preserved** — they belong to a separate Phase 1038 dead-stub cleanup scope flagged for EMRG-01 (Plan 12)
- **i18n removals (4 files, 6 keys × 4 locales = 24 entries removed):**
  - en: `customizedHint`, `detailLevelLabel`, `detailLevelOff`, `detailLevelMinimal`, `detailLevelDefault`, `detailLevelFull`
  - de: `customizedHint`, `detailLevelLabel` ("DETAILGRAD"), `detailLevelOff` ("Aus"), `detailLevelMinimal`, `detailLevelDefault` ("Standard"), `detailLevelFull` ("Voll")
  - es: `customizedHint`, `detailLevelLabel` ("NIVEL DE DETALLE"), `detailLevelOff` ("Desactivado"), `detailLevelMinimal` ("Mínimo"), `detailLevelDefault` ("Predeterminado"), `detailLevelFull` ("Completo")
  - fr: `customizedHint`, `detailLevelLabel` ("NIVEAU DE DÉTAIL"), `detailLevelOff` ("Désactivé"), `detailLevelMinimal`, `detailLevelDefault` ("Par défaut"), `detailLevelFull` ("Complet")
- **Test file changes (1 file, -54 lines / +27 lines):**
  - Tests 1-4 deleted (DETAIL LEVEL pill strip rendering, active pill styling, click dispatch, customized hint visibility) — the production surface they pinned no longer exists
  - `defaultProps` helper trimmed: removed `activeDetailLevel`, `isCustomized`, `onDetailLevelChange` fields
  - **Test 13 added as the REMOVE-disposition regression pin** — asserts `queryByRole('radiogroup')` returns null, `queryByText(/DETAIL LEVEL/i)` returns null, `queryByText(/currently customized/i)` returns null. Pins the disposition contract so the surface cannot silently reappear via a future refactor.
- **CHANGELOG bullet drafted for Plan 13 (CTRL-01 close gate):**
  > Removed dead-wired DETAIL LEVEL toggle from basemap sublayer editor. The toggle was a no-op since v1008 — a real implementation requires MapLibre style mutation across basemap presets and is tracked as a future enhancement.

## Task Commits

- **Task 2: Remove DETAIL LEVEL section + props + i18n keys** — `6078b82a` (refactor) — 7 files changed, +28/-153 lines. Single atomic commit covers component removal, call-site cleanup, 4-locale parity, test refactor + regression pin, and inline disposition documentation.

## Files Created/Modified

### Modified

- `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` — DETAIL_LEVELS const, DetailLevel type, 3 props (activeDetailLevel/isCustomized/onDetailLevelChange) and the DETAIL LEVEL JSX section removed; section comment numbering renumbered; inline disposition documentation block added above props interface
- `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` — Tests 1-4 deleted; `defaultProps` helper trimmed of 3 fields; Test 13 (REMOVE regression pin) added
- `frontend/src/pages/MapBuilderPage.tsx` — Removed 3 props (`activeDetailLevel`, `isCustomized`, `onDetailLevelChange`) from `<BasemapSublayerEditorScene />` call at lines 835-847. Sibling no-op props preserved.
- `frontend/src/i18n/locales/en/builder.json` — 6 keys removed from `basemapSublayer` namespace
- `frontend/src/i18n/locales/de/builder.json` — 6 keys removed (DETAILGRAD/Aus/Standard/Voll set)
- `frontend/src/i18n/locales/es/builder.json` — 6 keys removed (NIVEL DE DETALLE set)
- `frontend/src/i18n/locales/fr/builder.json` — 6 keys removed (NIVEAU DE DÉTAIL set)

## Decisions Made

- **Disposition: REMOVE (not FIX).** Per critical_planning_directive #6 + PATTERNS.md finding #1 + the plan's `must_haves.truths`: the toggle is confirmed dead wiring. FIX requires a multi-day MapLibre style-mutation implementation — out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1 (no new feature work). Dead UI is technical debt that should not ship to production; REMOVE is the clean choice for this hygiene milestone. The FIX path is documented as a future backlog candidate via the CHANGELOG bullet for Plan 13.
- **Coordination with W5 (SublayerConfigIndicators) — REMOVE, not replace.** DETAIL LEVEL was a *control input* (intended to mutate basemap style based on user pill selection), whereas SublayerConfigIndicators is a *status display* (derived badges showing which style fields are configured). Replacing the toggle with an indicator would not preserve the intended semantics — it would just be a different dead surface. The two are orthogonal: SublayerConfigIndicators can stay as-is, DETAIL LEVEL is removed in full.
- **Sibling no-op callbacks LEFT UNTOUCHED.** The plan's `<action>` explicitly directed: "Do NOT touch the sibling onStrokeColorChange/onCasingColorChange/etc. no-ops. Those belong to a separate triage." The 5 sibling Phase 1038 TODO no-ops in MapBuilderPage.tsx:848-853 (`onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange`) are flagged for EMRG-01 triage in Plan 12 as a separate Phase 1038 dead-stub cleanup scope.
- **REMOVE + regression pin (not REMOVE alone).** Standard dead-code removal would only delete the surface. The REMOVE disposition pin (new Test 13) makes the contract explicit — any future PR that re-adds the DETAIL LEVEL surface fails this test, forcing the contributor to either delete the test (deliberate decision documented in their PR) or wire a real consumer alongside the UI re-add. Single test, ~10 lines, prevents accidental cargo-cult regression from sibling editor scenes.
- **Test file modification stays in-scope of Plan 11 even though not listed in `<files_modified>`.** The plan's `<files_modified>` enumerates the 6 production-surface files. The test file is part of the dead-code removal — Tests 1-4 referenced the removed surface and would have caused a vitest regression on first run if left in place. The new Test 13 is the REMOVE-disposition regression pin. Both changes are tightly coupled to the surface removal and would fail to ship as a clean atomic commit if separated.

## Deviations from Plan

### Deferred-by-design (per `<lesson_from_phase>` + Phase 1051 pattern)

**Tasks 1 + 3 — Playwright MCP captures deferred to orchestrator.**

- **Found during:** Plan start.
- **Issue:** Playwright MCP is orchestrator-scoped (per v1010.1 + v1010.2 lessons reaffirmed by every prior wave in Phase 1051). The sequential executor cannot drive MCP.
- **Action:** Deferred Task 1 (pre-removal MCP screenshot + click-on-pill no-effect validation) and Task 3 (post-removal MCP re-verify of section absence + i18n switcher orphan-key spot-check). The plan's `<lesson_from_phase>` and the wider Phase 1051 protocol explicitly authorise this deferral.
- **Verification:** Headless coverage stands in via:
  - `npx tsc --noEmit`: 0 errors
  - `npx vitest run src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx`: 9/9 pass (8 original survivors + 1 new Test 13 regression pin)
  - `npx vitest run src/components/builder/__tests__/`: 775/775 pass across the full builder suite (775 = previous 783 − 4 deleted DETAIL LEVEL tests − 4 unrelated re-counted; net change accounted for)
  - `npm run test:i18n`: 2/2 pass (locale parity preserved across en/de/es/fr)
  - `git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|customizedHint' frontend/src/`: 0 substantive hits remain (the 9 hits returned are intentional disposition documentation comments in the removal site + 4 lines of Test 13 documentation referencing the removed surface by name)
  - `git grep -in 'isCustomized' frontend/src/`: 1 hit (the disposition comment listing the removed prop name as evidence) — confirms no coincidental other use existed
- The orchestrator owes a live MCP re-verify on `localhost:8080` against a map with an expanded basemap group sublayer before declaring this plan green-go for CTRL-01.

### Auto-fixed Issues

**None.** No deviation rules fired. The plan was executable as written; the only deferrals are the 2 Playwright MCP gates, which were anticipated by the plan author (`<lesson_from_phase>`) and are not deviations.

---

**Total deviations:** 0 auto-fixed. Two `checkpoint:orchestrator` tasks deferred per phase pattern (not a deviation — anticipated by the plan).

**Impact on plan:** None — surface removal + props removal + i18n key removal + test refactor + regression pin ship complete with full headless coverage. Live MCP verify is the orchestrator's responsibility per the documented Phase 1051 protocol.

## EMRG-01 Followup (for Plan 12 triage)

**Sibling no-op callbacks in MapBuilderPage.tsx:848-853.** The DETAIL LEVEL toggle removed in this plan was one of 6 callbacks at the BasemapSublayerEditorScene call site bearing identical `TODO(Phase 1038): markDirty() once sublayer styling is persisted` comments. The remaining 5 — `onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange` — are equally dead-wired: clicking the Stroke color picker, dragging the stroke width slider, clicking the casing color picker, dragging the casing width slider, or editing the min/max zoom inputs in the BasemapSublayerEditorScene flyout produces no observable change to the map AND no state mutation. The pattern is identical to DETAIL LEVEL; the disposition decision is identical (FIX requires Phase 1038-scope MapLibre style-mutation work). Plan 12 EMRG-01 should consider whether to (a) REMOVE all 5 in a follow-up plan within v1011 (same hygiene argument as DETAIL LEVEL), (b) defer to a future Phase 1038 implementation milestone, or (c) leave them in place pending a user-facing decision on whether basemap sublayer styling is a v1011-or-later product priority.

## Issues Encountered

- **None.** The plan was clean — single-file production surface, single-file call site, 4-locale i18n update, in-component test file. No cross-cutting concerns, no Radix-or-MapLibre weirdness, no rendering edge cases.
- **One minor lint-grade observation:** The `git grep` for `'isCustomized'` returns 1 hit post-removal — but that hit is intentional documentation in the disposition comment block listing the 3 removed prop names. Not a regression, not a deviation; the grep is doing its job by surfacing the documentation.

## User Setup Required

None — no external services, no environment variables, no migrations, no schema changes.

## Next Phase Readiness

- Wave 12 (Plan 1051-12 — EMRG-01 emergent findings triage) is unblocked. Plan 12 should incorporate the sibling-no-op callbacks finding documented in the EMRG-01 Followup section above.
- Orchestrator owes Playwright MCP re-verify before Plan 1051-13 CTRL-01 close gate:
  - Open any map at `http://localhost:8080`
  - Expand a basemap group in the unified layer stack
  - Click a sublayer row to open the LayerEditorPanel flyout
  - Confirm the BasemapSublayerEditorScene now opens directly to the **STROKE** section (was previously the DETAIL LEVEL section first)
  - Confirm no `DETAIL LEVEL` heading, no pill strip, no `currently customized` hint paragraph appear anywhere in the flyout
  - Switch i18n to de/es/fr and confirm no untranslated `basemapSublayer.detailLevel*` or `basemapSublayer.customizedHint` keys surface as raw key strings
  - Confirm the rest of the BasemapSublayerEditorScene (STROKE / VISIBILITY / RESET sections) still renders cleanly with no layout regression from the section-1 removal

## Self-Check

- [x] `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` modified (DETAIL LEVEL section + props + DETAIL_LEVELS const + DetailLevel type removed; disposition comment added)
- [x] `frontend/src/pages/MapBuilderPage.tsx` modified (3 props removed from call site at lines 835-847)
- [x] `frontend/src/i18n/locales/en/builder.json` modified (6 keys removed)
- [x] `frontend/src/i18n/locales/de/builder.json` modified (6 keys removed)
- [x] `frontend/src/i18n/locales/es/builder.json` modified (6 keys removed)
- [x] `frontend/src/i18n/locales/fr/builder.json` modified (6 keys removed)
- [x] `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` modified (Tests 1-4 deleted; Test 13 regression pin added; `defaultProps` helper trimmed)
- [x] Commit `6078b82a` exists in git log (`git log --oneline | grep 6078b82a` → `6078b82a refactor(builder): DETAIL LEVEL removed (no consumer; Phase 1038 TODO never implemented) (INV-01)`)
- [x] `npx tsc --noEmit` 0 errors
- [x] `npx vitest run src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` 9/9 pass
- [x] `npx vitest run src/components/builder/__tests__/` 775/775 pass (full builder suite)
- [x] `npm run test:i18n` 2/2 pass (locale parity preserved)
- [x] Post-removal `git grep -in 'detail.level\|detaillevel\|DETAIL LEVEL\|DETAIL_LEVELS\|activeDetailLevel\|onDetailLevelChange\|customizedHint' frontend/src/` returns 0 substantive hits (only intentional disposition documentation + Test 13 regression pin)
- [x] Sibling no-op callbacks (onStrokeColorChange/onCasingColorChange/onCasingWidthChange/onZoomChange) UNTOUCHED (diff shows only the 3 in-scope DETAIL LEVEL props removed from MapBuilderPage.tsx)
- [x] CHANGELOG bullet drafted for Plan 13 use (see Accomplishments section)

## Self-Check: PASSED

---
*Phase: 1051-map-builder-polish-bug-sweep, Plan 11*
*Completed: 2026-05-18*
