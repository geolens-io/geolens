---
phase: 256-line-gradient-builder-ui
plan: 02
subsystem: ui
tags: [frontend, map-builder, line-gradient, raw-expression, validation, vitest, playwright, uat]

# Dependency graph
requires:
  - phase: 256-line-gradient-builder-ui
    plan: 01
    provides: LineGradientControls component, DEFAULT_GRADIENT_STOPS, stopsToLineGradientExpression, lineGradientExpressionToStops, style.lineGradient.* i18n block
provides:
  - Raw MapLibre expression editor disclosure inside LineGradientControls (collapsed by default)
  - Exported validateLineGradientExpressionInput(text) -> { ok: true, value: unknown[] } | { ok: false, error: 'parseError' | 'structureError' }
  - KNOWN_MAPLIBRE_OPERATORS allowlist for permissive structural validation
  - Apply / Cancel commit semantics (Apply commits paint + builder ONLY on validation success; Cancel never commits)
  - Round-trip via shared parser: canonical Apply re-hydrates stops; non-canonical Apply commits paint and clears builder so customExpression hint surfaces (no silent flatten)
  - 6 new style.lineGradient.* i18n keys (advanced, advancedHint, applyExpression, cancelExpression, parseError, structureError)
  - .planning/phases/256-line-gradient-builder-ui/256-UAT.md — Playwright MCP + manual fallback visual UAT protocol document
affects: [future raw-expression editors for fill/circle/raster paint, Phase 256 visual UAT closure, GRAD-03 satisfaction]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Disclosure-style raw expression editor (collapsed by default; ChevronDown/ChevronRight + Code lucide icons; mirrors existing AdvancedJsonEditor disclosure pattern at LayerStyleEditor.tsx:786)"
    - "Two-tier validation: parse -> structure (must be array starting with known MapLibre operator). Heavyweight semantic validation deferred to MapLibre's runtime — matches existing AdvancedJsonEditor convention"
    - "Local component state for in-progress editing (advancedText / advancedError) — does NOT mutate paint until user clicks Apply"
    - "Round-trip via shared parser (lineGradientExpressionToStops): canonical Apply hydrates builder.stops; non-canonical Apply clears builder.lineGradient so customExpression hint surfaces — never silently flattened"
    - "Permissive KNOWN_MAPLIBRE_OPERATORS allowlist (interpolate / step / match / case / let / arithmetic / comparison / input operators) — rejects garbage but stays forward-compatible with future MapLibre operators"

key-files:
  created:
    - .planning/phases/256-line-gradient-builder-ui/256-UAT.md
  modified:
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/components/builder/LineGradientControls.tsx
    - frontend/src/components/builder/__tests__/LineGradientControls.test.tsx

key-decisions:
  - "Validation gate runs ONLY on Apply (not on every keystroke) — typing is unconstrained so the user can compose freely; only commit boundaries are gated. Mirrors existing AdvancedJsonEditor convention"
  - "Permissive structural validation (allowlist of MapLibre operators) rather than full semantic validation — keeps the gate cheap and forward-compatible with future operators; MapLibre's runtime errors surface in dev console after commit, identical to existing AdvancedJsonEditor behavior"
  - "Apply commits in dual-write: onPaintProp('line-gradient', value) AND onBuilderChange({ lineGradient: parsedStops != null ? { stops } : undefined }) — when canonical, the stops UI re-renders next render; when non-canonical, customExpression hint surfaces because builder.lineGradient was cleared"
  - "Cancel resets advancedText to '' and clears advancedError. We deliberately do NOT preserve typed-but-unsubmitted text across cancellations — user expects a fresh slate next time they open the disclosure (re-opening reads from current paint)"
  - "validateLineGradientExpressionInput exported from LineGradientControls (not a private helper) so future plans / downstream consumers can reuse the same gate without copy-pasting the operator allowlist"

requirements-completed: [GRAD-03]

# Metrics
duration: 4 min
completed: 2026-05-06
---

# Phase 256 Plan 02: line-gradient-builder-ui Summary

**Raw MapLibre expression editor disclosure with parse + structural validation, Apply/Cancel commit flow, round-trip via shared parser (canonical hydrates stops; non-canonical preserves customExpression hint), and Playwright MCP visual UAT protocol document.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-06T20:38:26Z
- **Completed:** 2026-05-06T20:42:41Z
- **Tasks:** 5 (4 implementation + 1 checkpoint)
- **Files created:** 1
- **Files modified:** 3
- **Total files touched:** 4

## Accomplishments

- Six new i18n keys (`advanced`, `advancedHint`, `applyExpression`, `cancelExpression`, `parseError`, `structureError`) under `style.lineGradient.*`
- `validateLineGradientExpressionInput(text)` exported from `LineGradientControls.tsx` — returns `{ ok: true, value }` for canonical/parseable + structurally-valid input or `{ ok: false, error: 'parseError' | 'structureError' }` for invalid input. Backed by a permissive `KNOWN_MAPLIBRE_OPERATORS` allowlist (interpolate, step, match, case, let, var, arithmetic, comparison, input operators) — sized to reject garbage but stay forward-compatible with future MapLibre operators
- Disclosure UI: collapsed by default; toggle button mirrors AdvancedJsonEditor pattern (ChevronDown/Right + Code icons + `text-xs font-medium text-muted-foreground hover:text-foreground` link styling). On open: textarea seeded with `JSON.stringify(paint['line-gradient'] ?? null, null, 2)`, Apply / Cancel buttons rendered alongside
- Apply commits in dual-write: `onPaintProp('line-gradient', value)` followed by either `onBuilderChange({ lineGradient: { stops: parsedStops } })` (canonical) or `onBuilderChange({ lineGradient: undefined })` (non-canonical). The non-canonical path is what surfaces the existing `customExpression` hint downstream — no silent flatten
- Cancel discards typed text without committing; `advancedText` resets to `''` and `advancedError` clears. The textarea closes; re-opening reads fresh from current paint
- Eight new vitest tests appended to `LineGradientControls.test.tsx` under a new `describe('LineGradientControls — advanced expression editor', () => {...})` block:
  - `advanced: line-gradient advanced disclosure is collapsed by default`
  - `advanced: opening the line-gradient advanced disclosure renders a textarea + Apply + Cancel`
  - `advanced: typing invalid JSON into the line-gradient advanced editor surfaces parseError inline and does NOT commit`
  - `advanced: typing a non-array structure into the line-gradient advanced editor surfaces structureError`
  - `advanced: typing an unknown operator into the line-gradient advanced editor surfaces structureError`
  - `advanced: applying a canonical line-gradient expression commits to paint and re-hydrates the stops panel`
  - `advanced: applying a non-canonical line-gradient expression commits to paint and shows the customExpression hint (no silent flatten)`
  - `advanced: cancelling the line-gradient advanced editor does NOT commit`
- Combined LineGradientControls + LayerStyleEditor + map-sync.line-gradient + layer-adapters: **134 passed / 0 failed** (was 49 in Plan 01; +8 new advanced editor tests + the broader Plan 01 stops-UI suite re-running cleanly)
- Plan-level gates green: `npm test ... --run` -> 134/134, `npm run lint -- --quiet` -> 0 errors, `npm run build` -> success
- `.planning/phases/256-line-gradient-builder-ui/256-UAT.md` (91 lines) documents the Playwright MCP + manual fallback visual UAT protocol for success criterion 4 — five protocol steps (author 3-stop gradient, save/reload, export/import round-trip, raw editor smoke, non-canonical preservation) with explicit pass criteria and pixel-diff thresholds, plus a "Failure Modes To Watch" section mapping common visual regressions back to specific Phase 255/256 contracts (e.g., "Lines render flat" -> Phase 255 GRAD-01 lineMetrics regression)

## Task Commits

Each task was committed atomically (TDD plan splits RED + GREEN):

1. **Task 1: Add i18n keys for raw expression editor** — `86edff95` (feat)
2. **Task 2 RED: Add failing tests for raw expression editor disclosure** — `a0007b13` (test)
3. **Task 2 GREEN: Implement raw line-gradient expression editor disclosure** — `a2221ffb` (feat)
4. **Task 3: Plan-level lint + build verification** — verification-only, no commit (no source modifications)
5. **Task 4: Author Playwright MCP UAT protocol for line-gradient visual identity** — `9884a939` (docs)
6. **Task 5: Visual UAT execution gate** — pending human/Playwright sign-off (Playwright MCP not registered in this run environment)

## Files Created/Modified

### Created
- `.planning/phases/256-line-gradient-builder-ui/256-UAT.md` — 91-line Playwright MCP + manual fallback UAT protocol for success criterion 4. Five protocol steps with explicit pass criteria; failure-mode triage section.

### Modified
- `frontend/src/i18n/locales/en/builder.json` — Appended 6 new keys to the existing `style.lineGradient.*` block (advanced, advancedHint, applyExpression, cancelExpression, parseError, structureError). JSON re-validates clean.
- `frontend/src/components/builder/LineGradientControls.tsx` — Added `KNOWN_MAPLIBRE_OPERATORS` Set, exported `validateLineGradientExpressionInput()`, added local `advancedOpen` / `advancedText` / `advancedError` state, added `openAdvanced` / `cancelAdvanced` / `applyAdvanced` handlers, added disclosure JSX block at the end of the component. 249 lines -> 368 lines.
- `frontend/src/components/builder/__tests__/LineGradientControls.test.tsx` — Appended 8 new vitest cases under a new `describe('LineGradientControls — advanced expression editor')` block. 136 lines -> 260 lines.

## Decisions Made

- **Validation gate runs only on Apply, never on keystroke.** The user types freely; only commit boundaries are gated. Mirrors existing AdvancedJsonEditor convention. Avoids the UX trap of a textarea that visibly rejects characters as the user types (which is hostile to copy-paste workflows that the disclosure exists to enable in the first place).
- **Permissive `KNOWN_MAPLIBRE_OPERATORS` allowlist** rather than running MapLibre's full expression parser at commit time. The goal is to reject obvious garbage (random strings, plain objects, unknown operators) before it touches `paint['line-gradient']`; full semantic validation remains MapLibre's runtime concern. The allowlist is sized to be forward-compatible: it includes the operator categories MapLibre actually exposes (interpolate / step / match / case / let / var / arithmetic / comparison / string / collator / format / input), so a real-world expression a user would paste in is overwhelmingly likely to pass the structural gate.
- **Apply commits in dual-write** (paint + builder), with the builder write conditional on whether the parsed expression matches the canonical interpolate-linear-line-progress shape. This is the load-bearing decision: it's what makes the customExpression hint surface for non-canonical pastes WITHOUT us having to add a separate "the user pasted something exotic" code path. The hint already exists for non-canonical paint expressions (Plan 01); we just needed to make sure Apply doesn't accidentally commit a stale canonical-shape `builder.lineGradient.stops` that contradicts the new non-canonical paint.
- **Cancel resets `advancedText` to `''`** rather than preserving the user's typed-but-unsubmitted text. Re-opening the disclosure reads fresh from current paint. Rationale: if the user explicitly clicked Cancel, they're discarding the edit; they don't expect their abandoned half-finished expression to reappear later. Matches the typical Cancel button convention.
- **`validateLineGradientExpressionInput` is exported** (not a private helper). Future plans or downstream consumers (e.g., a future raw-expression editor for fill / circle / raster paint) can reuse the same parse + structural gate without copy-pasting the operator allowlist. The function is small and well-typed so the export is cheap.

## Deviations from Plan

None - plan executed exactly as written.

The plan's RED/GREEN/REFACTOR cycle for Task 2 ran cleanly: 8 tests added in RED (failed as expected), implementation added in GREEN (15 prior + 8 new = 23 LineGradientControls tests passing). No refactor commit needed — the implementation was minimal and matched the test expectations on the first GREEN pass.

The plan's `<verify>` blocks for Tasks 1, 2, 3, 4 all passed first-time. No deviations from the locked validation rule (D-04), no additions to the operator allowlist beyond what the plan explicitly specified, no changes to the prop interface of LineGradientControls (the new state is component-local; the existing onPaintProp / onBuilderChange callbacks are reused).

**Total deviations:** 0. **Impact:** None — plan was correctly scoped.

## Issues Encountered

None during Tasks 1-4.

**Task 5 (Visual UAT) — Playwright MCP unavailable in this run environment.** Playwright MCP tools (`mcp__playwright__*`) are not registered in my tool surface; only context7 MCP is available. Per the plan's <action> block for Task 5, this routes to the Manual Fallback path:

- Per the directive: write `.planning/phases/256-line-gradient-builder-ui/256-UAT.md` (done in Task 4) and return `## CHECKPOINT REACHED` with the manual UAT flag so the autonomous workflow routes this as `human_needed`.
- The mechanical/automated gates (vitest 134/134, lint 0 errors, build success) ALL pass — only the visual UAT itself remains as a human/Playwright sign-off gate.
- A human running the 5-step UAT protocol from `256-UAT.md` will close success criterion 4. Until then, this plan is functionally complete but UAT-pending.

## Visual UAT

**Status:** Pending human verification (Playwright MCP not available in this run environment).

**Path taken:** Manual Fallback — UAT protocol document checked into `.planning/phases/256-line-gradient-builder-ui/256-UAT.md`; awaiting human run.

**Next action:** A human reviewer runs Steps 1-5 from `256-UAT.md` against the local stack and reports PASS / FAIL. On PASS: success criterion 4 closes. On FAIL: regression test added to `LineGradientControls.test.tsx` or `LayerStyleEditor.test.tsx` capturing the failure mechanically before the next gate.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All 8 success criteria from the plan are mechanically satisfied (i18n keys, validateLineGradientExpressionInput export, KNOWN_MAPLIBRE_OPERATORS, disclosure renders collapsed, Apply/Cancel commit semantics, parse+structure errors block commit, canonical Apply re-hydrates stops, non-canonical Apply preserves customExpression hint).
- Combined test gate (`npm test -- LineGradientControls LayerStyleEditor map-sync.line-gradient layer-adapters --run`) green: 134/134.
- Plan 01 + Plan 02 together close the phase's mechanical contract for GRAD-02 (Plan 01) + GRAD-03 (Plan 02). Phase 256's only remaining gate is the visual UAT (success criterion 4) which is documented and awaiting human/Playwright run.
- No blockers, no architectural deferred items. The exported `validateLineGradientExpressionInput` and the disclosure pattern (ChevronDown/Right + textarea + Apply/Cancel + inline parse/structure error) are ready to be lifted into a future raw-expression editor for fill / circle / raster paint if a follow-up phase wants the same disclosure UX.

---
*Phase: 256-line-gradient-builder-ui*
*Completed: 2026-05-06*

## Self-Check: PASSED

Verified after writing SUMMARY.md:

**Created files exist:**
- FOUND: `.planning/phases/256-line-gradient-builder-ui/256-UAT.md` (91 lines)

**Modified files exist:**
- FOUND: `frontend/src/i18n/locales/en/builder.json` (6 new keys under style.lineGradient.*)
- FOUND: `frontend/src/components/builder/LineGradientControls.tsx` (368 lines, +119 from Plan 01's 249)
- FOUND: `frontend/src/components/builder/__tests__/LineGradientControls.test.tsx` (260 lines, +124 from Plan 01's 136)

**Commits exist in git log:**
- FOUND: `86edff95` (Task 1: feat)
- FOUND: `a0007b13` (Task 2 RED: test)
- FOUND: `a2221ffb` (Task 2 GREEN: feat)
- FOUND: `9884a939` (Task 4: docs — UAT protocol)

**Plan-level gates re-run:**
- `npm test -- LineGradientControls LayerStyleEditor map-sync.line-gradient layer-adapters --run` → 134 passed / 0 failed (4 test files)
- `npm run lint -- --quiet` → exit 0
- `npm run build` → exit 0

**Acceptance criteria from each task — all PASS** (re-verified by greps + tests in this run):
- 6 new i18n keys present under style.lineGradient.* (advanced=1, applyExpression=1, cancelExpression=1, parseError=1, structureError=1, advancedHint=1)
- KNOWN_MAPLIBRE_OPERATORS refs in component: 2
- validateLineGradientExpressionInput refs in component: 2
- advancedOpen state refs: 5 (state declaration + open/cancel/apply handlers + JSX conditional)
- 8 new advanced-editor tests (≥ 7 required)
- Component file 368 lines (≥ 200 required)
- UAT doc 91 lines (≥ 50 required), Playwright MCP refs: 4 (≥ 2), Manual Fallback: 1 (≥ 1), lineMetrics: 3 (≥ 1)

## TDD Gate Compliance

Plan type: `execute` (not `tdd` plan-level), but Task 2 was `tdd="true"`. Task 2 followed the RED/GREEN cycle correctly:
- RED commit `a0007b13` (test): 8 tests added, all failing.
- GREEN commit `a2221ffb` (feat): implementation added, all tests passing (15 prior + 8 new = 23).
- No REFACTOR commit needed — implementation was minimal and matched test expectations on first GREEN pass.
