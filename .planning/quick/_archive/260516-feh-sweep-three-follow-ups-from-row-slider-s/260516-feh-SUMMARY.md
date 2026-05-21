---
phase: quick-260516-feh
plan: 01
subsystem: frontend/builder + e2e
tags: [builder, toast, sonner, e2e, playwright, basemap-utils, master-opacity]
requires:
  - .planning/quick/260516-feh-sweep-three-follow-ups-from-row-slider-s/260516-feh-RESEARCH.md
provides:
  - dedupe-id + 6s duration on popupConfigInvalid toast
  - bulk-delete e2e wired to SP-01 portaled overflow-menu architecture
  - boundary symbol icon-opacity stamp symmetry under subtle + master dim
affects:
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - e2e/builder-v1-5.spec.ts
  - frontend/src/lib/basemap-utils.ts
  - frontend/src/lib/__tests__/basemap-utils.test.ts
tech_stack_added: []
patterns_used:
  - Sonner toast.error options object (id for dedupe, duration override)
  - Playwright data-testid bridge over [role=toolbar] descendant selector (SP-01 portal-safe)
  - applyBasemapLayerConfig prominence stamp dict for symbol layers
key_files:
  created: []
  modified:
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    - e2e/builder-v1-5.spec.ts
    - frontend/src/lib/basemap-utils.ts
    - frontend/src/lib/__tests__/basemap-utils.test.ts
decisions:
  - "Picked 0.45 (matching text-opacity) for icon-opacity stamp rather than road-icon 0.35; boundary glyphs are small admin symbols, lockstep keeps label+glyph visually coherent"
  - "FEH-02 uses real .click() (not dispatchEvent) — SP-01 whitelists [data-bulk-action-menu] in outside-click handler, natural click is safe"
  - "FEH-01 ships defensive hardening (dedupe id + 6s duration + test coverage) rather than chasing a phantom bug; RESEARCH falsified all three hypotheses from the originating memory"
metrics:
  duration_minutes: 12
  completed_date: 2026-05-16
requirements_satisfied:
  - FEH-01
  - FEH-02
  - FEH-03
---

# Quick 260516-feh: Row-Slider Follow-up Sweep — Summary

Closed three follow-ups surfaced by the 260516-9g9 row-slider session, each as its own atomic commit with verifiable test coverage. Zero architecture churn.

## What Shipped

### FEH-01 — Defensive hardening of `toasts.popupConfigInvalid`
- `frontend/src/components/builder/hooks/use-builder-save.ts:380`: changed `toast.error(t('toasts.popupConfigInvalid'))` to `toast.error(t('toasts.popupConfigInvalid'), { id: 'popup-config-invalid', duration: 6000 })`.
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`: new `it('surfaces popupConfigInvalid toast with dedupe id + extended duration when layer has invalid popup expression', ...)` asserts the call shape (key + objectContaining {id, duration}) AND that neither `updateMap` nor `patchMapLayers` mutation fires when the early-return triggers.
- **Commit:** `eb29a056`

### FEH-02 — Bulk-delete e2e to SP-01 portaled overflow-menu
- `e2e/builder-v1-5.spec.ts:485-493`: replaced the `[role="toolbar"] button[aria-label*="Delete"]` descendant selector + `dispatchEvent('click')` workaround with the SP-01-aware `data-testid` bridge: open `[data-testid="bulk-action-overflow"]`, then click `[data-testid="bulk-action-delete"]` from the portal. Real `.click()` throughout — SP-01 already whitelists `[data-bulk-action-menu="true"]` in the outside-click handler, so the actionability bypass is no longer needed.
- Zero production code modified.
- **Commit:** `3a07d0e2`

### FEH-03 — Boundary symbol icon-opacity symmetry
- `frontend/src/lib/basemap-utils.ts:393-397`: boundary branch subtle dict for symbols now stamps both `text-opacity: 0.45` and `icon-opacity: 0.45` (was only `text-opacity: 0.45`). Pre-fix, `applyMasterOpacity` fell back to writing absolute master on icon-opacity because no stamp existed, leaving text dimmed while icon stayed full.
- `frontend/src/lib/__tests__/basemap-utils.test.ts`: new `it('dims boundary symbol icons in lockstep with text under subtle + master opacity', ...)` inside the existing `applyBasemapConfigToStyle master opacity` describe block. Asserts both `text-opacity` and `icon-opacity` close to `0.225` (0.45 stamp × 0.5 master).
- **Commit:** `33892115`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture omitted `visible_fields: null` from `PopupConfig` literal**
- **Found during:** Cross-cutting `tsc -b` verify gate after all 3 task commits.
- **Issue:** The new FEH-01 test fixture used `popup_config: { enabled: true, expression: '{{missing_column}}' }`. `PopupConfig` (frontend/src/types/api.ts:734-738) requires `visible_fields: string[] | null` (not optional). Vitest passed (runtime doesn't care), but `tsc -b` failed: `TS2741: Property 'visible_fields' is missing`.
- **Fix:** Added `visible_fields: null` to the fixture literal. No production code touched. New `tsc -b` exits 0.
- **Files modified:** `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`
- **Commit:** `cbfc34e4` (separate hygiene commit — the regression was introduced by FEH-01 but only surfaced at the cross-cutting gate; per protocol new commit rather than amend)

No other deviations — plan executed exactly as written.

## Verification

### Per-task
- **FEH-01:** `cd frontend && vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts` → 36/36 pass (35 pre-existing + 1 new).
- **FEH-02:** `npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium` → 1/1 + setup pass. Followup full-spec run: `npx playwright test e2e/builder-v1-5.spec.ts --project=chromium` → 5/5 pass (tests 1-3 not regressed).
- **FEH-03:** `cd frontend && vitest run src/lib/__tests__/basemap-utils.test.ts` → 41/41 pass (40 pre-existing + 1 new).

### Cross-cutting gate
- `cd frontend && ./node_modules/.bin/tsc -b` → exit 0 (after Rule-1 fixup commit `cbfc34e4`).
- `cd frontend && vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts src/lib/__tests__/basemap-utils.test.ts` → 77/77 pass.

## Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| FEH-01 | `eb29a056` | `fix(quick-260516-feh): dedupe + extend popup-config-invalid toast (FEH-01)` |
| FEH-02 | `3a07d0e2` | `test(quick-260516-feh): update bulk-delete e2e to SP-01 overflow-menu architecture (FEH-02)` |
| FEH-03 | `33892115` | `fix(quick-260516-feh): stamp icon-opacity on boundary subtle to match text dim (FEH-03)` |
| Rule-1 | `cbfc34e4` | `test(quick-260516-feh): add visible_fields: null to FEH-01 popup_config fixture for tsc` |

## Threat Model Compliance

All three items were classified `accept` in the plan's `<threat_model>`:
- **T-feh-01 (Tampering — Sonner id collision):** Verified pre-commit `grep -rn "popup-config-invalid" frontend/src/` returned zero matches. New id is unique.
- **T-feh-02 (Information Disclosure — test selectors):** `data-testid="bulk-action-overflow"` and `data-testid="bulk-action-delete"` were already present in production DOM (SP-01 commit `bbde1a5d`); no new attributes added.
- **T-feh-03 (DoS — extra setPaintProperty):** One additional call per boundary symbol layer per applyBasemap pass — boundary symbol layers per style are O(few). Negligible.

No new threat surface introduced.

## Self-Check

- [x] `frontend/src/components/builder/hooks/use-builder-save.ts:380` passes `{ id: 'popup-config-invalid', duration: 6000 }` to `toast.error` — FOUND.
- [x] `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` contains `popup-config-invalid` — FOUND.
- [x] `e2e/builder-v1-5.spec.ts` contains `bulk-action-overflow` — FOUND.
- [x] `e2e/builder-v1-5.spec.ts` no longer contains `dispatchEvent('click')` in the bulk-delete trigger block (legacy workaround removed) — VERIFIED.
- [x] `frontend/src/lib/basemap-utils.ts:393-397` boundary subtle dict for symbols contains `'icon-opacity': 0.45` — FOUND.
- [x] `frontend/src/lib/__tests__/basemap-utils.test.ts` contains `boundary symbol icons in lockstep` — FOUND.
- [x] Commits `eb29a056`, `3a07d0e2`, `33892115`, `cbfc34e4` exist on main — FOUND.

## Self-Check: PASSED
