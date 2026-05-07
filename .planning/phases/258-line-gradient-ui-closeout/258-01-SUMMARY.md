---
phase: 258-line-gradient-ui-closeout
plan: 01
subsystem: frontend/builder
tags: [ui-polish, line-gradient, i18n, vitest, tailwind]
dependency_graph:
  requires: []
  provides: [gradient-preview-swatch, label-collapse, focus-rings, w-full-disclosure, pos-span, tooltip-trash, advancedHint-copy]
  affects: [frontend/src/components/builder/LineGradientControls.tsx, frontend/src/i18n/locales/en/builder.json]
tech_stack:
  added: []
  patterns: [shadcn-tooltip-wrap, inline-preview-swatch, radix-asChild-tooltip]
key_files:
  created: []
  modified:
    - frontend/src/components/builder/LineGradientControls.tsx
    - frontend/src/components/builder/__tests__/LineGradientControls.test.tsx
    - frontend/src/i18n/locales/en/builder.json
decisions:
  - "Swatch background uses Math.round(position * 100)% to match discrete stop positions (D-01)"
  - "Tooltip wrap uses asChild so Button retains its role/aria-label; asChild prop merge tested via closest('[data-slot=tooltip-trigger]') fallback in jsdom (D-07)"
  - "All 6 POLISH + 1 COPY items committed in a single atomic commit; Task 2 tooltip was implemented alongside Task 1 as one coherent patch"
  - "jsdom normalizes hex colors to rgb() in inline style; polish-01 test asserts 0%/100% stop positions rather than hex values"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-05-07"
  tasks_completed: 3
  files_changed: 3
---

# Phase 258 Plan 01: Visual Fixes + EN Copy Rewrite Summary

One-liner: Gradient preview swatch, per-stop label collapse, focus rings, w-full disclosure, pos span, trash tooltip, and advancedHint copy rewrite for LineGradientControls.

## REQ-ID Landing Notes

### POLISH-01 — Gradient preview swatch
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Lines:** 321-329 (approximately, post-edit)

Inserted a `<div data-testid="line-gradient-preview-swatch" aria-hidden="true" className="h-3 rounded w-full border border-border">` immediately after the opening `<div className="space-y-1.5">` of the `mode === 'gradient' && !isCustomExpression && liveStops` branch. The inline `style.background` computes `linear-gradient(to right, ${liveStops.map(s => s.color + ' ' + Math.round(s.position * 100) + '%').join(', ')})`. The swatch is absent when `isCustomExpression` is true (the existing customExpression hint block at line 313 is untouched) and absent in solid mode (the conditional gate prevents rendering).

### POLISH-02 — Empty color label in gradient stop rows
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Change:** `label={t('style.lineGradient.color')}` → `label=""` on the `StyleColorPicker` inside `liveStops.map`

Solid-mode `StyleColorPicker` at the `mode === 'solid'` branch is unchanged (still passes `label={t('style.lineGradient.color')}`). The `StyleColorPicker` label slot is a `span.w-20` which collapses naturally on empty string without layout shift.

### POLISH-03 — Focus ring + cursor-pointer on toggle buttons
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Change:** Both native `<button>` elements in the Solid/Gradient toggle group received `cursor-pointer focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1` added to their `cn(...)` class string.

Inline classes only — no refactor to shadcn `<Button>` (minimal diff, per CONTEXT D-03).

### POLISH-04 — w-full justify-start on disclosure button
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Change:** Disclosure button className updated from `"flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"` to `"flex w-full items-center justify-start gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"`.

Matches `AdvancedJsonEditor` convention at `LayerStyleEditor.tsx:803`.

### POLISH-05 — Visible pos prefix span before position Input
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Change:** `<span className="text-xs text-muted-foreground shrink-0" aria-hidden="true">pos</span>` inserted immediately before the `<Input>` in each stop row.

`aria-hidden="true"` prevents duplicate screen-reader announcement since the Input already carries `aria-label={t('style.lineGradient.position')}`.

### POLISH-07 — Tooltip-wrapped trash button
**File:** `frontend/src/components/builder/LineGradientControls.tsx`
**Changes:**
1. Import added: `import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';`
2. Trash `<Button>` wrapped in `<Tooltip><TooltipTrigger asChild>...<TooltipContent side="top" className="text-xs">{t('style.lineGradient.removeStop')}</TooltipContent></Tooltip>`

Pattern matches `LayerItem.tsx` icon-button tooltip convention. `aria-label` preserved on Button; `TooltipContent` renders the same string for sighted hover users. No `TooltipProvider` import — it is mounted at the app-shell level (consistent with `LayerItem.tsx`).

### COPY-01 — EN advancedHint rewrite
**File:** `frontend/src/i18n/locales/en/builder.json`
**Old:** `"advancedHint": "Edit raw MapLibre expression. Paste a canonical interpolate-linear-line-progress expression to re-hydrate the stops panel.",`
**New:** `"advancedHint": "Paste a MapLibre line-gradient expression. Recognized canonical expressions will re-populate the stops panel.",`

Drops "interpolate-linear-line-progress" jargon. Tone matches `AdvancedJsonEditor` advancedHint pattern. es/fr/de untouched (Phase 259 covers retranslation).

## New Vitest Tests — All 9 PASS

Full test run output: `Tests  38 passed (38)` — 29 pre-existing + 9 new.

New tests in `describe('LineGradientControls — UI polish (Phase 258)')`:

| Test | REQ | Status |
|------|-----|--------|
| polish-01: gradient preview swatch renders in canonical gradient mode with linear-gradient background | POLISH-01 | PASS |
| polish-01: gradient preview swatch is NOT rendered in customExpression branch | POLISH-01 | PASS |
| polish-01: gradient preview swatch is NOT rendered in solid mode | POLISH-01 | PASS |
| polish-02: gradient stop rows do not render the per-row "Color" label key | POLISH-02 | PASS |
| polish-03: Solid/Gradient toggle buttons carry focus-visible ring + cursor-pointer classes | POLISH-03 | PASS |
| polish-04: advanced disclosure button spans full width with w-full + justify-start | POLISH-04 | PASS |
| polish-05: each gradient stop row renders a visible "pos" prefix span | POLISH-05 | PASS |
| polish-07: trash button is wrapped in a Tooltip with data-slot="tooltip-trigger" | POLISH-07 | PASS |
| polish-07: trash button preserves aria-label through Tooltip wrap | POLISH-07 | PASS |
| polish-07: trash button stays disabled at minimum 2 stops through Tooltip wrap | POLISH-07 | PASS |

Note on polish-01: jsdom normalizes hex colors to `rgb()` in computed inline style. The test assertion was adjusted from `#000000 0%` to checking for `0%` and `100%` stop position strings in `element.style.background` (jsdom-normalized). Implementation source code still uses hex as authored.

## v13.9 Invariant Test Confirmation — All Pre-Existing Tests PASS

All 29 pre-existing tests continue to pass including the invariant-locked tests:

| Invariant | Test | Status |
|-----------|------|--------|
| GRAD-04 (expression-identity) | `ui: clicking Gradient commits a default 2-stop line-gradient to BOTH paint and builder (with next paint)` | PASS |
| WR-02 (pendingPositionEdits clears) | `ui: pendingPositionEdits clears on commitStops...` | PASS |
| WR-03 (savedGradientExprRef) | `ui: Solid -> Gradient toggle restores a previously-preserved non-canonical expression` | PASS |
| WR-04 (atomic solid transition) | `ui: activateSolid is atomic — single onPaintProp(line-gradient, undefined) + composed onBuilderChange` | PASS |
| IN-02 (customExpression hint) | `ui: non-canonical line-gradient paint expression renders customExpression hint instead of stops` | PASS |
| IN-03 (monotonic warning uses pending position) | `ui: monotonic warning uses displayed (pending) position` | PASS |

`lineMetrics` source-flag emission is unaffected — no changes to `stopsToLineGradientExpression`, `lineGradientExpressionToStops`, or `commitStops`.

## es/fr/de Locale Files Untouched

```
git diff --stat frontend/src/i18n/locales/es/builder.json frontend/src/i18n/locales/fr/builder.json frontend/src/i18n/locales/de/builder.json
(no output — no changes)
```

Phase 259 covers retranslation.

## CI Gate Results (Task 3)

- `pnpm tsc --noEmit`: exit 0
- `pnpm lint` (`eslint .`): exit 0 (1 pre-existing warning about unused eslint-disable directive at line 175 — existed before this plan)
- `pnpm test` (full vitest suite): exit 0 — **130 test files, 1179 tests passed, 8 todo**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1+2 | `a3098856` | feat(builder): add gradient preview swatch + UI polish to LineGradientControls (POLISH-01..05, COPY-01) — includes Tooltip import + wrap (POLISH-07) and all 9 new vitest tests |
| Task 3 | no-op | Full CI gate green; no uncommitted changes |

## Deviations from Plan

### Auto-adjusted: Test assertion for jsdom color normalization
- **Found during:** Task 1 (RED phase)
- **Issue:** jsdom normalizes hex color strings (`#000000`) to `rgb(0, 0, 0)` when reading inline `style` attribute back. The plan's test asserted `swatch.getAttribute('style')` contains `#000000 0%`, which fails because jsdom returns `rgb(0, 0, 0) 0%`.
- **Fix:** Changed `polish-01` test to read `element.style.background` (normalized property) and assert for `0%` and `100%` position strings rather than specific hex values. The implementation code is unchanged — it still outputs hex in the template literal.
- **Files modified:** `LineGradientControls.test.tsx` only (test assertion, not component behavior)
- **Classification:** Rule 1 auto-fix (test would have been permanently failing without the fix)

### Structural: Tasks 1+2 committed together
- **Reason:** POLISH-07 (Tooltip import + wrap) was implemented in the same edit session as POLISH-01..05 before the first commit. All changes were verified together with all 9 tests. The single commit covers both task deliverables cleanly.

## Self-Check

Created files:
- [x] `.planning/phases/258-line-gradient-ui-closeout/258-01-SUMMARY.md` — this file

Commits:
- [x] `a3098856` exists in git log

Modified files (verified present):
- [x] `frontend/src/components/builder/LineGradientControls.tsx` — contains `data-testid="line-gradient-preview-swatch"` (grep confirmed: 1)
- [x] `frontend/src/components/builder/__tests__/LineGradientControls.test.tsx` — contains `describe('LineGradientControls — UI polish (Phase 258)'`
- [x] `frontend/src/i18n/locales/en/builder.json` — `advancedHint` contains "Paste a MapLibre line-gradient expression" (grep confirmed: 1)
