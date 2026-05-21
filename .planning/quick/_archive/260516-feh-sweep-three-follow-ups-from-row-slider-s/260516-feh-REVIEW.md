---
phase: 260516-feh-sweep-three-follow-ups-from-row-slider-s
reviewed: 2026-05-16T00:00:00Z
depth: quick
files_reviewed: 5
files_reviewed_list:
  - e2e/builder-v1-5.spec.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/lib/__tests__/basemap-utils.test.ts
  - frontend/src/lib/basemap-utils.ts
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# quick-260516-feh: Code Review Report

**Reviewed:** 2026-05-16
**Depth:** quick
**Files Reviewed:** 5
**Status:** clean

## Summary

Reviewed the 4-commit sweep (`eb29a056..HEAD`) covering FEH-01 (popup-config-invalid toast dedupe + duration), FEH-02 (e2e bulk-delete locator update for SP-01 overflow-menu architecture), FEH-03 (boundary `icon-opacity` symmetry stamp), and the `cbfc34e4` test-fixture tsc fix.

All three targeted changes are narrowly scoped, correctly tested, and free of detectable bugs, security issues, or quality defects at the HIGH or MEDIUM confidence level.

### Per-change verification

**FEH-01 (`use-builder-save.ts:380`, `use-builder-save.test.ts:518-541`)**
- `toast.error` now passes `{ id: 'popup-config-invalid', duration: 6000 }`. Grepped the frontend tree — the id `popup-config-invalid` is not used by any other `toast.*` call site (only the production line and the test), so no dedupe collisions.
- Other `toast.*` calls in `use-builder-save.ts` (lines 422, 432, 443, 461, 472, 475, 491, 495, 499) all omit IDs and are unaffected by sonner's dedupe contract.
- The i18n key `toasts.popupConfigInvalid` exists in all 4 locales (en/de/es/fr `builder.json:617`) — translation parity preserved.
- The new vitest case exercises the invalid-popup short-circuit branch (`popup_config.expression='{{missing_column}}'` against `dataset_column_info=[{name:'present_column'}]`) and asserts both the toast call shape and that neither `updateMap` nor `patchMapLayers` mutateAsync was invoked. `vi.clearAllMocks()` runs in `beforeEach` (line 247), so the negative assertions are sound.
- `cbfc34e4` follow-up added `visible_fields: null` — `PopupConfig.visible_fields` is typed `string[] | null` (`types/api.ts:737`), so this is type-correct and the fixture compiles under strict tsc.

**FEH-02 (`builder-v1-5.spec.ts:485-496`)**
- New locator chain (`[data-testid="bulk-action-overflow"]` → `.click()` → `[data-testid="bulk-action-delete"]` → `.click()`) maps to the actual BulkActionBar JSX at `BulkActionBar.tsx:263` and `:313` (both testids are rendered unconditionally when `selectedIds.length > 0`).
- The overflow trigger calls `e.stopPropagation()` on `onPointerDown` (`BulkActionBar.tsx:266`), but Radix `DropdownMenu` opens on pointerdown without requiring bubbling — confirmed by the existing `BulkActionBar.test.tsx` unit tests which use `fireEvent.pointerDown` directly on the same testid. No race introduced.
- The portaled `DropdownMenuContent` carries `data-bulk-action-menu="true"` (`BulkActionBar.tsx:285`), and `UnifiedStackPanel.tsx:659` whitelists this attribute in its outside-click handler, preserving the multi-selection while the menu interaction completes.
- The third click (delete-confirm button at line 526) still uses `.dispatchEvent('click')` deliberately — this is the click that needs to bypass mousedown bubbling, and the existing comment block at lines 517-519 covers it. No behavior regression.

**FEH-03 (`basemap-utils.ts:393-399`, `basemap-utils.test.ts:407-438`)**
- Boundary symbol-layer subtle stamp now includes `'icon-opacity': 0.45` alongside `'text-opacity': 0.45`. `prominenceStamps` registers both keys, so `applyMasterOpacity` composes both with `master`, writing `0.45 * 0.5 = 0.225` for both — matching road-layer symbol symmetry (which already stamped both via the `road_visibility` branch, albeit at 0.45/0.35).
- The fix is targeted: only the symbol branch of the boundary subtle stamp changes. Line geometry (`'line-opacity': 0.4`) is untouched.
- Under `boundary_visibility='full'`, `prominenceStamps` remains empty for these keys, so `applyMasterOpacity` falls through to the `else` branch and writes absolute master for both — preserves the Path R reversibility contract from `quick-260516-9g9` CR-01.
- The test fixture (`boundary_country_label`, `source-layer: 'boundary'`, `type: 'symbol'`, `text-field` + `icon-image`) classifies as boundary via `BOUNDARY_PATTERNS` matching `'boundary'`/`'country'` tokens. It also matches `isTextLabelLayer` (symbol + text-field), but `label_mode` defaults to `'full'` (not specified in test), so the label branch is a no-op and does not overwrite the boundary stamps. Test is meaningful, not trivially passing.
- `toBeCloseTo(0.225, 5)` is the correct float-comparison shape; 5 decimal places is well below the precision needed for `0.45 * 0.5`.

### Scope discipline
`git diff --name-only eb29a056^..HEAD` returns exactly the 5 in-scope files. No out-of-scope creep.

### Test quality
All three new test cases are meaningful and exercise the exact branches modified by the fixes. None are trivially passing (each would fail if the fix were reverted). Test mocks are isolated via `vi.clearAllMocks()` in `beforeEach`.

---

No findings at HIGH or MEDIUM confidence. The sweep is **CLEAR TO MERGE**.

---

_Reviewed: 2026-05-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
