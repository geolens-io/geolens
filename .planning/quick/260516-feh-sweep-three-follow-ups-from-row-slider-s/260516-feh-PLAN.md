---
phase: quick-260516-feh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - e2e/builder-v1-5.spec.ts
  - frontend/src/lib/basemap-utils.ts
  - frontend/src/lib/__tests__/basemap-utils.test.ts
autonomous: true
requirements:
  - FEH-01  # Item 1: popup-config-invalid toast hardening (dedupe id + duration + test)
  - FEH-02  # Item 2: builder-v1-5 multi-select bulk-delete e2e fix to SP-01 portal architecture
  - FEH-03  # Item 3: boundary symbol icon-opacity symmetry under master dim
must_haves:
  truths:
    - "popup-config-invalid toast call site (use-builder-save.ts ~line 380) passes options object with id='popup-config-invalid' and duration=6000"
    - "vitest covers the popupConfigInvalid branch by asserting toast.error is called with the i18n key and the id option, and that updateMap mutation does NOT fire"
    - "builder-v1-5 bulk-delete e2e (lines 485-493) opens the SP-01 overflow menu by [data-testid='bulk-action-overflow'] click before locating [data-testid='bulk-action-delete']"
    - "e2e test no longer uses dispatchEvent('click') and no longer locates Delete inside [role='toolbar']"
    - "basemap-utils.ts boundary branch (line 394) stamps both text-opacity:0.45 and icon-opacity:0.45 for symbol layers"
    - "vitest covers boundary symbol master-opacity symmetry: both text-opacity and icon-opacity dim to 0.225 when subtle + master=0.5"
    - "All production changes are localized to single-line/single-call-site edits — no helpers, refactors, or scope creep introduced"
    - "Item 2 is purely a test-side change — zero production code modified"
  artifacts:
    - path: "frontend/src/components/builder/hooks/use-builder-save.ts"
      provides: "popup-config-invalid toast with id + duration options"
      contains: "id: 'popup-config-invalid'"
    - path: "frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts"
      provides: "regression test for popupConfigInvalid toast branch"
      contains: "popup-config-invalid"
    - path: "e2e/builder-v1-5.spec.ts"
      provides: "bulk-delete e2e using SP-01 overflow-menu architecture"
      contains: "bulk-action-overflow"
    - path: "frontend/src/lib/basemap-utils.ts"
      provides: "boundary symbol subtle paint with icon-opacity stamp"
      contains: "'icon-opacity': 0.45"
    - path: "frontend/src/lib/__tests__/basemap-utils.test.ts"
      provides: "regression test for boundary symbol icon/text master-dim symmetry"
      contains: "boundary symbol icons in lockstep"
  key_links:
    - from: "use-builder-save.ts handleSave validation branch"
      to: "Sonner toast"
      via: "toast.error(key, { id, duration })"
      pattern: "toast\\.error\\(t\\('toasts\\.popupConfigInvalid'\\)"
    - from: "e2e bulk-delete test"
      to: "BulkActionBar portaled DropdownMenu"
      via: "data-testid bridge (bulk-action-overflow → bulk-action-delete)"
      pattern: "data-testid=\"bulk-action-overflow\""
    - from: "applyBasemapLayerConfig boundary branch (symbol case)"
      to: "applyMasterOpacity prominenceStamps consumer"
      via: "subtle dict includes icon-opacity stamp"
      pattern: "'icon-opacity': 0\\.45"
---

<objective>
Sweep three follow-ups surfaced by the 260516-9g9 row-slider session, applying the minimal change described in RESEARCH.md for each. The research was a verification pass — file paths, line numbers, root causes, and exact diffs are confirmed. No discovery work remains.

Items (ordered by user impact, each its own atomic commit):

1. **Item 1 — Defensive hardening of `toasts.popupConfigInvalid`.** Research falsified all three "toast not firing" hypotheses; the toast IS routed and IS rendering, but likely ages out (Sonner default 4s) or stacks on repeated Cmd-S. Add `id: 'popup-config-invalid'` (dedupe) + `duration: 6000` (longer on-screen for a blocking validation error) + a vitest case that asserts the call shape.

2. **Item 2 — Test-only fix for `builder-v1-5.spec.ts` "multi-select bulk delete happy: 2 rows".** SP-01 (commit `bbde1a5d`, 2026-05-15) moved Delete behind a portaled DropdownMenu overflow trigger. The test's selector `[role="toolbar"] button[aria-label*="Delete"]` cannot match a portal-rendered menu item; the test is structurally broken vs current production code, not flaky. Switch to `data-testid` bridge (`bulk-action-overflow` → `bulk-action-delete`) and drop the `dispatchEvent('click')` workaround (SP-01 already whitelists the menu portal in the outside-click handler).

3. **Item 3 — Boundary symbol icon-opacity symmetry.** `applyBasemapLayerConfig`'s boundary branch stamps only `text-opacity: 0.45` for symbols; `applyMasterOpacity` then writes the absolute master to `icon-opacity` (no stamp found), leaving icons full while text dims. One-line paint fix: stamp `icon-opacity: 0.45` alongside `text-opacity: 0.45` in the boundary subtle dict. Add a vitest that asserts both keys dim in lockstep under subtle + master=0.5.

Purpose: close out the three open follow-ups from `project_open_followups_from_row_slider_sweep.md` with three atomic commits and verifiable test coverage, no architecture churn.

Output: 3 commits on main, each with vitest/playwright green for its respective scope, plus a clean `tsc -b` cross-cutting check.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260516-feh-sweep-three-follow-ups-from-row-slider-s/260516-feh-RESEARCH.md

<!-- The RESEARCH.md is the single source of truth for this plan. It contains: -->
<!--   - Verified file paths and current line numbers (memory had 1-26 line drift) -->
<!--   - Exact before/after diffs for each item -->
<!--   - Test code (drop-in vitest cases for Item 1 and Item 3) -->
<!--   - Root-cause confirmations and falsified hypotheses -->
<!--   - Risk analysis per item -->

<interfaces>
<!-- Key facts the executor needs upfront, lifted from RESEARCH.md verification: -->

use-builder-save.ts (Item 1 target):
- Line 6: `import { toast } from 'sonner';`
- Line 334: `const { t } = useTranslation('builder');`
- Line 380: `toast.error(t('toasts.popupConfigInvalid'));` — the call to harden
- Line 422, 432: `toast.success(t('toasts.mapSaved'))` — proof the toaster works

use-builder-save.test.ts (Item 1 test target):
- Line 59: existing `useTranslation` mock returns `t: (key) => key` (passthrough — assert on key)
- Existing scaffolding includes `makeSaveState`, `makeLayer`, `renderHook` patterns

BulkActionBar.tsx (Item 2 production reference — DO NOT MODIFY):
- Line 263: `data-testid="bulk-action-overflow"` on the MoreHorizontal trigger button
- Line 313: `data-testid="bulk-action-delete"` on the Delete DropdownMenuItem
- DropdownMenuContent is portaled via `DropdownMenuPrimitive.Portal` (ui/dropdown-menu.tsx:43)

UnifiedStackPanel.tsx (Item 2 production reference — DO NOT MODIFY):
- Lines 653-665: outside-click handler whitelists `[data-bulk-action-menu="true"]` subtree → portal-clicks are safe

builder-v1-5.spec.ts (Item 2 target):
- Lines 485-493: the broken locator + dispatchEvent block (the only change site for Item 2)

basemap-utils.ts (Item 3 target):
- Line 394: `const subtle = next.type === 'line' ? { 'line-opacity': 0.4 } : { 'text-opacity': 0.45 };`
- Line 386-392: road branch reference (already has `icon-opacity: 0.35` — confirms the pattern is supported)
- Lines 336-366: `applyMasterOpacity` — symbol type iterates BOTH text-opacity and icon-opacity (line 317)

basemap-utils.test.ts (Item 3 test target):
- Lines 311-407: existing `describe('applyBasemapConfigToStyle master opacity', ...)` block — add new `it()` inside
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1 (FEH-01): Harden popupConfigInvalid toast with dedupe id + extended duration</name>
  <files>frontend/src/components/builder/hooks/use-builder-save.ts, frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts</files>
  <behavior>
    - Test (vitest, added to existing test file inside the validation describe block): when handleSave runs on a state whose only layer has popup_config.enabled=true with an expression referencing a column not present in dataset_column_info, the hook calls toast.error with the i18n key 'toasts.popupConfigInvalid' AND an options object containing id: 'popup-config-invalid' AND duration: 6000. The hook must NOT invoke the updateMap mutation in this branch (early return at line 381 — per RESEARCH.md test plan it asserts via `state.mockUpdateMapMutateAsync` not having been called; use whatever mock handle the existing scaffolding exposes for the updateMap mutation, do not invent new mock plumbing).
    - The test relies on the existing `vi.mock('sonner', ...)` pattern (mock toast.error + toast.success). If the existing test file does not already mock 'sonner' at the top level, add the mock alongside other top-level mocks — do not re-import or duplicate.
    - Existing tests in this file must continue to pass with no fixture changes.
  </behavior>
  <action>
    Per RESEARCH.md Item 1 recommended fix and test plan:

    (a) In `frontend/src/components/builder/hooks/use-builder-save.ts` at ~line 380 inside `handleSave`, change the single call:
      `toast.error(t('toasts.popupConfigInvalid'));`
    to:
      `toast.error(t('toasts.popupConfigInvalid'), { id: 'popup-config-invalid', duration: 6000 });`
    Leave the surrounding control flow (the layer-loop, the early `return;` at line 381) untouched. Do not extract a helper. Do not change any other call to `toast.error` or `toast.success` in the file.

    (b) In `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`, add a new `it(...)` case following the existing save-validation tests. The new case must construct a saveState whose `localLayers` contains exactly one layer with `popup_config: { enabled: true, expression: '{{missing_column}}' }` and `dataset_column_info: [{ name: 'present_column', type: 'text' }]` (reuse the existing `makeSaveState` and `makeLayer` factories — match their actual signatures from the file rather than the RESEARCH.md illustrative snippet). Render the hook, await `result.current.handleSave()`, and assert:
      - `toast.error` was called with `'toasts.popupConfigInvalid'` as the first arg
      - The second arg matches `expect.objectContaining({ id: 'popup-config-invalid', duration: 6000 })`
      - The updateMap mutation mock (whichever variable the existing tests use to spy on `updateMap.mutateAsync`) was NOT called

    If the existing test file already has a `vi.mock('sonner', ...)` block, use the existing mock surface. If it does not, add a minimal one mocking `toast.error` and `toast.success` as `vi.fn()` exports — match the import shape `import { toast } from 'sonner'` used by the production file.

    Commit message: `fix(quick-260516-feh): dedupe + extend popup-config-invalid toast (FEH-01)`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && ./node_modules/.bin/vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts</automated>
  </verify>
  <done>
    use-builder-save.ts line ~380 passes the options object with id 'popup-config-invalid' and duration 6000. New vitest case is green. All previously passing tests in the file remain green. No other call site or file was modified. Single atomic commit created with the message above.
  </done>
</task>

<task type="auto">
  <name>Task 2 (FEH-02): Update bulk-delete e2e to SP-01 portaled overflow-menu architecture</name>
  <files>e2e/builder-v1-5.spec.ts</files>
  <action>
    Per RESEARCH.md Item 2 recommended fix. This is a TEST-ONLY change — do not modify any production file.

    In `e2e/builder-v1-5.spec.ts`, locate the "multi-select bulk delete happy: 2 rows" test (Test 4, around lines 448-537). Replace ONLY the locator + click block at lines 485-493 (the comment + `deleteBtn` declaration + `toBeVisible`/`toBeEnabled` waits + `dispatchEvent('click')`) with the SP-01-aware replacement:

      // SP-01 (Phase 1045): Delete moved into a portaled overflow DropdownMenu.
      // 1) Open the overflow menu via its testid trigger.
      // 2) Click the Delete menuitem from the portal (not from the toolbar subtree).
      // The outside-click handler whitelists `[data-bulk-action-menu="true"]` so
      // the selection survives the menu interaction.
      const overflowBtn = page.locator('[data-testid="bulk-action-overflow"]');
      await expect(overflowBtn).toBeVisible({ timeout: 3_000 });
      await overflowBtn.click();

      const deleteBtn = page.locator('[data-testid="bulk-action-delete"]');
      await expect(deleteBtn).toBeVisible({ timeout: 3_000 });
      await deleteBtn.click();

    Use the new code's real `.click()` calls — do NOT keep the legacy `dispatchEvent('click')` workaround. SP-01's outside-click whitelist makes the natural click path safe.

    Leave every other line of the test file untouched: the multi-select setup (lines before 485), the post-click confirm dialog handling (lines after 493), and tests 1-3 of the spec must not be modified. Do not touch any production source file under `frontend/src/`.

    Commit message: `test(quick-260516-feh): update bulk-delete e2e to SP-01 overflow-menu architecture (FEH-02)`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium</automated>
  </verify>
  <done>
    Lines 485-493 in `e2e/builder-v1-5.spec.ts` now drive the overflow menu via `[data-testid="bulk-action-overflow"]` click and then `[data-testid="bulk-action-delete"]` click — no `[role="toolbar"]` descendant selector and no `dispatchEvent('click')`. The targeted Playwright test passes. The full `npx playwright test e2e/builder-v1-5.spec.ts --project=chromium` run shows no regression in tests 1-3 (run only if Task 2's targeted test passes). Zero production files modified. Single atomic commit created with the message above.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3 (FEH-03): Stamp icon-opacity on boundary subtle paint to match text dim</name>
  <files>frontend/src/lib/basemap-utils.ts, frontend/src/lib/__tests__/basemap-utils.test.ts</files>
  <behavior>
    - Test (vitest, added inside the existing `describe('applyBasemapConfigToStyle master opacity', ...)` block in basemap-utils.test.ts ~lines 311-407): when `applyBasemapConfigToStyle` is invoked with `boundary_visibility: 'subtle'` and `opacity: 0.5` on a style whose only layer is a boundary symbol layer (`id: 'boundary_country_label'`, `type: 'symbol'`, `'source-layer': 'boundary'`, `layout: { 'text-field': ['get','name'], 'icon-image': 'border-dot' }`, empty paint), the resulting layer's `paint['text-opacity']` and `paint['icon-opacity']` are BOTH approximately `0.225` (0.45 stamp × 0.5 master), assertable via `toBeCloseTo(0.225, 5)`.
    - The new `it()` must be additive only — no existing test in the file is changed or removed.
  </behavior>
  <action>
    Per RESEARCH.md Item 3 recommended fix and test plan:

    (a) In `frontend/src/lib/basemap-utils.ts` at line 394 inside the boundary branch of `applyBasemapLayerConfig`, change:
      `const subtle = next.type === 'line' ? { 'line-opacity': 0.4 } : { 'text-opacity': 0.45 };`
    to:
      `const subtle = next.type === 'line'
        ? { 'line-opacity': 0.4 }
        : { 'text-opacity': 0.45, 'icon-opacity': 0.45 };`

    Pick 0.45 (matching text) rather than 0.35 — boundary glyphs are small administrative symbols; matching the boundary text opacity keeps the label+glyph pair visually coherent. Do not modify the road branch (lines 386-392), the label branch (lines 401-409), `applyMasterOpacity`, or any other function. The compose-with-label overlap noted in RESEARCH.md is explicitly OUT OF SCOPE.

    (b) In `frontend/src/lib/__tests__/basemap-utils.test.ts`, add a new `it('dims boundary symbol icons in lockstep with text under subtle + master opacity', ...)` test inside the existing `describe('applyBasemapConfigToStyle master opacity', ...)` block. Use the StyleSpecification fixture exactly as written in RESEARCH.md Item 3 test plan (single boundary symbol layer with `text-field` + `icon-image`). Call `applyBasemapConfigToStyle(style, { boundary_visibility: 'subtle', opacity: 0.5 })`. Cast the result's `layers[0]` to `{ paint: { 'text-opacity': number; 'icon-opacity': number } }` and assert:
      - `expect(layer.paint['text-opacity']).toBeCloseTo(0.225, 5);`
      - `expect(layer.paint['icon-opacity']).toBeCloseTo(0.225, 5);`

    Match the import style used by the surrounding tests in the file (do not introduce a new top-level import unless `StyleSpecification` is already imported — if not, use the same pattern as the nearby `'wraps remote style numeric filters...'` test at lines 159-178 which already uses a typed style fixture).

    Commit message: `fix(quick-260516-feh): stamp icon-opacity on boundary subtle to match text dim (FEH-03)`
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && ./node_modules/.bin/vitest run src/lib/__tests__/basemap-utils.test.ts</automated>
  </verify>
  <done>
    basemap-utils.ts line 394 boundary subtle dict for symbol layers contains both `'text-opacity': 0.45` and `'icon-opacity': 0.45`. New vitest case is green; all pre-existing tests in `basemap-utils.test.ts` (raster master, line subtle, opacity=1 reset, reversibility, compound drag, expression-untouched) remain green. No other function in basemap-utils.ts modified. Single atomic commit created with the message above.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | All three items are internal frontend changes (Items 1, 3) or test-only (Item 2); no new trust boundary is crossed. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-feh-01 | Tampering | Sonner toast id collision | accept | RESEARCH.md verified `grep -rn "popup-config-invalid" frontend/src/` returns zero existing uses; new id is unique. No third-party untrusted input flows into the id. |
| T-feh-02 | Information Disclosure | e2e test selector via `data-testid` | accept | `data-testid` attributes are already exposed in production DOM by SP-01 (commit bbde1a5d) for QA tooling; this plan does not add new test ids. |
| T-feh-03 | Denial of Service | applyBasemapConfigToStyle perf with extra `icon-opacity` setPaintProperty call per boundary symbol layer | accept | RESEARCH.md notes this is "negligible" — a single additional setPaintProperty call per boundary symbol layer per applyBasemap pass. Boundary symbol layers per style are O(few). |
</threat_model>

<verification>
After all three tasks complete and individually verify, run the cross-cutting type + test gate from RESEARCH.md:

```bash
cd /Users/ishiland/Code/geolens/frontend && ./node_modules/.bin/tsc -b
cd /Users/ishiland/Code/geolens/frontend && ./node_modules/.bin/vitest run \
  src/components/builder/hooks/__tests__/use-builder-save.test.ts \
  src/lib/__tests__/basemap-utils.test.ts
cd /Users/ishiland/Code/geolens && npx playwright test e2e/builder-v1-5.spec.ts --project=chromium
```

Expected: `tsc -b` exits 0; vitest green on both files; playwright green on all v1.5 spec tests (1-4).
</verification>

<success_criteria>
- [ ] Three atomic commits on `main`, in order: FEH-01 (Item 1), FEH-02 (Item 2), FEH-03 (Item 3).
- [ ] `frontend/src/components/builder/hooks/use-builder-save.ts` line ~380 passes `{ id: 'popup-config-invalid', duration: 6000 }` to `toast.error`.
- [ ] `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` has a new test asserting the toast.error call shape and no updateMap mutation.
- [ ] `e2e/builder-v1-5.spec.ts` "multi-select bulk delete happy: 2 rows" passes via the SP-01 overflow-menu data-testid path with real `.click()` (no `dispatchEvent`).
- [ ] `frontend/src/lib/basemap-utils.ts` line 394 boundary subtle dict for symbols includes `'icon-opacity': 0.45`.
- [ ] `frontend/src/lib/__tests__/basemap-utils.test.ts` has a new test asserting boundary symbol text+icon dim in lockstep to 0.225 under subtle + master=0.5.
- [ ] `cd frontend && ./node_modules/.bin/tsc -b` exits 0.
- [ ] Full `npx playwright test e2e/builder-v1-5.spec.ts --project=chromium` passes (no regression in tests 1-3).
- [ ] No production code modified for Item 2.
- [ ] No new helpers, refactors, or out-of-scope changes anywhere.
</success_criteria>

<output>
Create `.planning/quick/260516-feh-sweep-three-follow-ups-from-row-slider-s/260516-feh-SUMMARY.md` when done.
</output>
