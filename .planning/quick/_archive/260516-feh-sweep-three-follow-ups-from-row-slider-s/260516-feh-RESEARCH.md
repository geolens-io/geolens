---
name: Row-Slider Followups Research
quick_id: 260516-feh
created: 2026-05-16
mode: verification
---

# Research: Row-Slider Three-Item Followup Sweep

This is a **verification research**, not a discovery research. The originating memory (`project_open_followups_from_row_slider_sweep.md`) supplied file paths, line numbers, and suspected root causes. Each item below confirms the current state of the code against those hints and recommends a single concrete fix.

Note on line-number drift: the memory was written hours before the verification. A couple of references shifted by 1-3 lines. The narratives are still accurate.

---

## Item 1 — Toast `popupConfigInvalid` doesn't surface on save

### Current state (verified)

`frontend/src/components/builder/hooks/use-builder-save.ts`:

- Line 6: `import { toast } from 'sonner';` — Sonner default export, no wrapper.
- Line 334 (inside `useBuilderSave`): `const { t } = useTranslation('builder');` — namespace `'builder'`.
- Lines 369-382: `handleSave` validates `popup_config.expression` against `dataset_column_info`, finds the invalid layer, calls `toast.error(t('toasts.popupConfigInvalid'));` and returns.

Memory said lines 382-391; actual is **lines 369-382**. The control flow is exactly as memory described — single call site, plain `toast.error`, no swallowing wrapper.

Same file uses `toast.success(t('toasts.mapSaved'))` at line 422 and 432 — and those DO surface in production (verified by 260516-9g9 UAT: Save button transitions to "Saved"). So the Toaster mount itself works fine.

i18n key resolution (`grep -rn popupConfigInvalid frontend/src/i18n/locales/`):
- `en/builder.json:617` — "Cannot save: one or more layers have invalid popup expressions"
- `de/builder.json:617` — German translation present
- `es/builder.json:617` — Spanish translation present
- `fr/builder.json:617` — French translation present

All four locales resolve to non-empty strings. The `'builder'` namespace is loaded (other `toasts.*` keys from the same namespace surface fine in production).

Toaster mount (`frontend/src/main.tsx:5,20-23,37`):
```tsx
import { Toaster } from 'sonner';
function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} />;
}
// rendered at the app root inside <TooltipProvider>, sibling to <RouterProvider>
```

Single Toaster, no `position`/`offset`/`hidden` props, no `richColors=false` override. Default position is top-right; default theme follows `resolvedTheme`.

There is **no existing test** for the `popupConfigInvalid` branch — `grep popupConfigInvalid frontend/src/components/builder/hooks/__tests__/` returns zero matches. The test scaffolding in `use-builder-save.test.ts:59` mocks `useTranslation: () => ({ t: (key) => key })` — perfect for asserting which key was passed to `toast.error`.

### Confirmed root cause

The memory has three hypotheses (toast not routed, toast invisible, key not resolving). All three are **falsified** by the verification:

1. ~~`toast.error` not routed to Sonner~~ — same `toast` from `'sonner'`, same Toaster, and `toast.success` from the SAME file at lines 422/432 surfaces fine.
2. ~~Toast rendered but invisible~~ — Sonner Toaster has no clipping; same Toaster shows success toasts at the same screen position.
3. ~~i18n key not resolving~~ — all 4 locales have non-empty strings at the same namespace + key path, and the namespace is already loaded by the same hook (other `toasts.*` keys work).

**The actual likely root cause is that the original reporter never actually hit the branch.** The repro in the memory is:
> Click Save (or ⌘S) — Save button stays "Unsaved changes". No toast appears. No network request fires.

The "no network request" part is the giveaway: that confirms the early `return;` at line 381 fired (otherwise `updateMap.mutateAsync` would have run). So the validation branch DID fire and `toast.error` WAS called. If the toast still doesn't appear, the most likely actual cause is:

- **A) Stale orchestrator log interpretation.** The memory cites `260516-9g9-SUMMARY.md`, but that summary's "Follow-up surfaced" note says only "popup-config toast doesn't surface — separate UX bug". There is no inline screenshot, console trace, or `getComputedStyle` evidence; it's a one-line observation. The actual MCP Playwright session from that quick task may have been observing a different map state where the toast queue was suppressed (e.g., user had previously dismissed it during the same session — Sonner has a 4s default `duration` but no dedupe key, and `toast.error` calls without an explicit `id` stack rather than replace).

- **B) The `toasts.popupConfigInvalid` toast IS firing but renders for 4s then disappears.** If the reporter clicked Save then alt-tabbed to the dev tools to inspect, the toast would have aged out by the time they looked. Sonner's default duration is 4000ms.

There is **NO verifiable bug in the code path** under the existing hypotheses. The fix should be a **defensive hardening + test** rather than a fix for a confirmed defect:

- Add explicit `id: 'popup-config-invalid'` to the toast call so repeated saves dedupe to one toast (prevents stacking).
- Add a longer `duration` (e.g. 6000) — this is a blocking validation error, not a transient confirmation.
- Add a vitest case that asserts `toast.error` was called with the right key when the invalid-popup branch fires.

If after this hardening the user STILL cannot see the toast on the repro map, the next investigation step is a Playwright MCP trace with `page.on('console')` and `DOM querySelector('[data-sonner-toaster]')` polling — not in scope of this RESEARCH.

### Recommended fix

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts` line 380.

Change:
```ts
toast.error(t('toasts.popupConfigInvalid'));
return;
```
to:
```ts
toast.error(t('toasts.popupConfigInvalid'), {
  id: 'popup-config-invalid',
  duration: 6000,
});
return;
```

The `id` dedupes repeated Cmd-S presses to a single visible toast. The `duration: 6000` gives a blocking validation error more on-screen time than the default 4s.

### Test plan

**File:** `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`

Add a new test after the existing save-validation block:

```ts
import { toast } from 'sonner';
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

it('surfaces popupConfigInvalid toast when layer has invalid popup expression', async () => {
  const state = makeSaveState({
    localLayers: [
      makeLayer({
        popup_config: { enabled: true, expression: '{{missing_column}}' },
        dataset_column_info: [{ name: 'present_column', type: 'text' }],
      }),
    ],
  });
  const { result } = renderHook(() => useBuilderSave(state));
  await result.current.handleSave();
  expect(toast.error).toHaveBeenCalledWith(
    'toasts.popupConfigInvalid',  // key passes through the test t() mock
    expect.objectContaining({ id: 'popup-config-invalid' }),
  );
  expect(state.mockUpdateMapMutateAsync).not.toHaveBeenCalled();
});
```

Run:
```bash
cd frontend
./node_modules/.bin/vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts
```

### Risk

- **Sonner `id` collision:** if any other call site uses `id: 'popup-config-invalid'`, it will dedupe with this toast. `grep -rn "popup-config-invalid" frontend/src/` → 0 matches today. Safe.
- **Existing test `t() => key` passthrough means the assertion is on the key, not the resolved string.** That's intentional — locale verification is a separate concern (already confirmed in the verification above).
- **No regression risk on the success path.** Only the error branch is touched.

---

## Item 2 — `builder-v1-5.spec.ts` "multi-select bulk delete happy: 2 rows" — NOT a flake, structurally broken

### Current state (verified)

`e2e/builder-v1-5.spec.ts:448-537` — Test 4 from the v1.5 multi-select spec.

The test was authored at commit `d088cc13` (2026-05-14) under the **inline-Delete-button** architecture of `BulkActionBar`. SP-01 (`bbde1a5d`, 2026-05-15) **moved Delete behind a portaled DropdownMenu overflow trigger**. The test file has not been updated since.

Key facts:

1. **Test locator (line 490):** `page.locator('[role="toolbar"] button[aria-label*="Delete"]')` — a CSS-style descendant selector. This selector requires the Delete button to be a DOM descendant of the `[role="toolbar"]` element.

2. **Current BulkActionBar structure** (`frontend/src/components/builder/BulkActionBar.tsx`):
   - Non-confirming state renders inline: Visibility, Opacity, then a `<DropdownMenu>` overflow trigger (`MoreHorizontal` icon, lines 254-327).
   - `DropdownMenuContent` (lines 274-326) holds the Delete `<DropdownMenuItem>` with `aria-label={t('bulkActions.deleteAriaLabel', { count: N })}` (line 315).
   - `DropdownMenuContent` is wrapped in `<DropdownMenuPrimitive.Portal>` by default (`frontend/src/components/ui/dropdown-menu.tsx:43`).

3. **Portal implication:** when the menu is open, the Delete item is rendered as a child of `document.body`, NOT a descendant of `[role="toolbar"]`. The test's locator therefore cannot match it.

4. **Outside-click handler** (`frontend/src/components/builder/UnifiedStackPanel.tsx:653-665`): a `document.addEventListener('mousedown', ...)` handler that clears the multi-selection if the mousedown target is outside `stackPanelRef` AND outside `[data-bulk-action-menu="true"]`. The handler is correctly excluded for the bulk-action menu portal subtree (line 659) — i.e., the SP-01 commit already handled the mousedown-race-vs-portal case.

5. **BulkActionBar root** (`BulkActionBar.tsx:132-133`) has React-handler `onPointerDown={(e) => e.stopPropagation()}` and `onClick={(e) => e.stopPropagation()}`. This stops React's synthetic event bubbling but does **not** prevent the native `document.mousedown` listener from firing (React attaches at the root; the document listener is a sibling-level capture). However, this is fine because the document listener checks `stackPanelRef.contains(target)` — and the toolbar is **outside** stackPanelRef (toolbar is rendered at line 1024, stackPanelRef wraps lines 862-1019). So a mousedown directly on the toolbar would trigger the clear, except that the test uses `dispatchEvent('click')` (line 493) which fires only `click`, no `mousedown`.

### Confirmed root cause

The memory's diagnosis ("mousedown race between toolbar and outside-click clear") is **wrong for the current code**. The mousedown race was the pre-SP-01 problem; SP-01 fixed it by (a) moving Delete into a portal'd menu, (b) marking the menu with `data-bulk-action-menu` so the outside-click handler whitelists it, and (c) keeping the test's `dispatchEvent('click')` strategy alive.

The **actual current cause** is: the test's selector `[role="toolbar"] button[aria-label*="Delete"]` cannot match a portal-rendered DropdownMenuItem. The test never reaches the toolbar-confirm state because `await expect(deleteBtn).toBeVisible({ timeout: 3_000 })` (line 491) times out — Playwright finds zero matches.

The memory's "passes most of the time" claim is **likely inaccurate** — the `260516-9g9-SUMMARY.md` line "24/24 builder e2e smoke (1 pre-existing flake = bulk-delete mousedown race, unrelated)" is probably a copy-paste from an older run. With the current code+test, this test should fail every time. To confirm, run:

```bash
cd /Users/ishiland/Code/geolens
npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium
```

Expected: fails on line 491 with "expected to be visible" timeout.

### Recommended fix

**Single test-side fix** (no production change). Insert an overflow-menu-open step before the Delete lookup, and switch to `data-testid` for unambiguous targeting (the production code already exposes `data-testid="bulk-action-overflow"` at line 263 and `data-testid="bulk-action-delete"` at line 313).

**File:** `e2e/builder-v1-5.spec.ts:485-493`

Replace:
```ts
// Click Delete button (opens confirm dialog — does NOT delete immediately).
// The button's aria-label is "Delete N selected layers" (from bulkActions.deleteAriaLabel).
// Use dispatchEvent to bypass Playwright actionability checks (avoids mousedown race with
// the outside-click selection-clear handler on document). dispatchEvent fires only 'click'
// without preceding mousedown/pointerdown, so the outside-click handler does not trigger.
const deleteBtn = page.locator('[role="toolbar"] button[aria-label*="Delete"]');
await expect(deleteBtn).toBeVisible({ timeout: 3_000 });
await expect(deleteBtn).toBeEnabled({ timeout: 3_000 });
await deleteBtn.dispatchEvent('click');
```
with:
```ts
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
```

Use real `click()` rather than `dispatchEvent('click')` — SP-01 explicitly whitelists `[data-bulk-action-menu="true"]` in the document mousedown handler, so the natural click path is now safe and there's no need to bypass actionability.

### Test plan

After applying the fix, run:
```bash
cd /Users/ishiland/Code/geolens
npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium
# Verify it passes 3x consecutively (no retries needed):
for i in 1 2 3; do
  npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium || break
done
```

Also re-run the full v1.5 spec to confirm no regression in tests 1-3:
```bash
npx playwright test e2e/builder-v1-5.spec.ts --project=chromium
```

### Risk

- **`bulkActions.delete` i18n key text contains "Delete"** but the test now matches on `data-testid`, not text — so locale changes don't break the test.
- **The overflow trigger's `data-testid` is stable** (added by SP-01 commit `bbde1a5d`).
- **No production change** — pure test-side fix. Cannot regress runtime behavior.
- The `dispatchEvent('click')` workaround is removed entirely; the test now exercises the real click path, which is a better integration test.

---

## Item 3 — Boundary symbol icon-opacity asymmetry under master-opacity dim

### Current state (verified)

`frontend/src/lib/basemap-utils.ts`:

- Line 393-397 — the boundary branch in `applyBasemapLayerConfig`:
  ```ts
  if (boundaryLayer) {
    const subtle = next.type === 'line' ? { 'line-opacity': 0.4 } : { 'text-opacity': 0.45 };
    next = applyProminence(next, config.boundary_visibility, subtle);
    if (config.boundary_visibility === 'subtle') Object.assign(prominenceStamps, subtle);
  }
  ```
  Memory said lines 367-371; actual is **393-397**. The shape matches: subtle paint for symbol case stamps only `text-opacity: 0.45`, no `icon-opacity`.

- Line 386-392 — the road branch for comparison:
  ```ts
  if (roadLayer) {
    const subtle = next.type === 'line'
      ? { 'line-opacity': 0.35 }
      : { 'text-opacity': 0.45, 'icon-opacity': 0.35 };
    ...
  }
  ```
  Road symbols stamp BOTH `text-opacity` (0.45) AND `icon-opacity` (0.35). Boundary symbols stamp only text. That's the asymmetry.

- Lines 336-366 — `applyMasterOpacity` is the absolute-writer from CR-01:
  ```ts
  const stamp = prominenceStamps[key];
  if (typeof stamp === 'number' && Number.isFinite(stamp)) {
    nextPaint[key] = stamp * masterOpacity;
  } else {
    ...
    nextPaint[key] = masterOpacity;  // when no stamp exists, write absolute master
  }
  ```
  For symbol type, `keys = ['text-opacity', 'icon-opacity']` (line 317). For a boundary symbol in subtle mode today:
  - `text-opacity`: stamp=0.45 found → writes `0.45 * master`
  - `icon-opacity`: stamp=**undefined** → writes `master` directly (absolute)
  
  Net: text dims to `0.45*M`, icon stays at `M`. Confirmed asymmetry.

- Line 401-409 — the label branch is **guarded** behind `!sublayerHidden` (line 401) and only fires when `isTextLabelLayer(next)` matches. Critically, this branch composes via `Object.assign(prominenceStamps, subtle)` — so if a layer matches BOTH `isBoundaryLayer` AND `isTextLabelLayer`, the LAST stamp wins on overlapping keys. Today the boundary stamp `text-opacity: 0.45` would be overwritten by the label stamp `text-opacity: 0.55`. That's a separate (lesser) issue — call it out for awareness, but not in scope for this fix.

- Lines 217-228 — `isBoundaryLayer` matches `type === 'line' || 'symbol'` AND tokens (id/source/source-layer) include any of `['boundary', 'admin', 'country', 'state', 'province']`. `isTextLabelLayer` matches `type === 'symbol'` AND `layout['text-field'] != null` OR `layerTokens(layer).includes('label')`.

Existing vitest coverage (`frontend/src/lib/__tests__/basemap-utils.test.ts` `applyBasemapConfigToStyle master opacity` block, lines 311-407):
- Raster master opacity ✓
- Line subtle + master multiply ✓
- Opacity=1 absolute reset ✓ (CR-01 regression)
- Reversibility ✓ (CR-01 regression)
- Compound drag (0.5 → 0.8 = 0.8 not 0.4) ✓ (CR-01 regression)
- Expression-valued opacity left untouched ✓

**Zero tests for boundary-symbol-layer master opacity.** One must be added.

### Confirmed root cause

Exactly as the 260516-9g9 REVIEW.md WR-01 described: the boundary subtle paint dict is missing `icon-opacity`. `applyMasterOpacity` for symbol layers iterates BOTH `text-opacity` and `icon-opacity`, and without a stamp for icon, it writes absolute master — producing the asymmetry where text dims but icon stays full.

The risk is narrow: OFM boundary symbol layers that ship an icon (administrative boundary glyphs — small set). It's a visual nit, not a functional bug.

### Recommended fix

**File:** `frontend/src/lib/basemap-utils.ts` line 394.

Change:
```ts
const subtle = next.type === 'line' ? { 'line-opacity': 0.4 } : { 'text-opacity': 0.45 };
```
to:
```ts
const subtle = next.type === 'line'
  ? { 'line-opacity': 0.4 }
  : { 'text-opacity': 0.45, 'icon-opacity': 0.45 };
```

Pick `0.45` (matching text) rather than `0.35` (matching road icons) — boundary glyphs are typically smaller administrative symbols; matching the boundary text opacity keeps the label+glyph pair visually coherent.

### Test plan

**File:** `frontend/src/lib/__tests__/basemap-utils.test.ts`

Add inside the existing `describe('applyBasemapConfigToStyle master opacity', ...)` block:

```ts
it('dims boundary symbol icons in lockstep with text under subtle + master opacity', () => {
  const style: StyleSpecification = {
    version: 8,
    sources: { v: { type: 'vector', tiles: ['x'] } },
    layers: [
      {
        id: 'boundary_country_label',
        type: 'symbol',
        source: 'v',
        'source-layer': 'boundary',
        layout: { 'text-field': ['get', 'name'], 'icon-image': 'border-dot' },
        paint: {},
      },
    ],
  };
  const next = applyBasemapConfigToStyle(style, {
    boundary_visibility: 'subtle',
    opacity: 0.5,
  });
  const layer = next.layers[0] as unknown as {
    paint: { 'text-opacity': number; 'icon-opacity': number };
  };
  // Both keys should dim to 0.45 * 0.5 = 0.225 — symmetric, no asymmetry between text and icon.
  expect(layer.paint['text-opacity']).toBeCloseTo(0.225, 5);
  expect(layer.paint['icon-opacity']).toBeCloseTo(0.225, 5);
});
```

Run:
```bash
cd frontend
./node_modules/.bin/vitest run src/lib/__tests__/basemap-utils.test.ts
```

Expected before fix: `icon-opacity` would be `0.5` (absolute master), test fails.
Expected after fix: both keys equal `0.225`, test passes.

### Risk

- **Pre-SP-01 fixture compatibility:** The test fixture in `frontend/src/lib/__tests__/basemap-utils.test.ts:159-178` (`'wraps remote style numeric filters...'`) uses an `id: 'boundary_3'` line layer — that already matches `isBoundaryLayer` for the line branch. Adding `icon-opacity` to the symbol branch does NOT affect line layers. No risk to that test.
- **Downstream consumers of `applyBasemapConfigToStyle`:** the result is fed to `applyBasemapConfigToMap` in `map-sync.ts`, which diffs paint keys and calls `setPaintProperty`. A new `icon-opacity` value on boundary symbol layers will produce an extra `setPaintProperty` call per such layer per applyBasemap pass — negligible.
- **The compose-with-label-branch overlap** (boundary AND text label layer) still has the lesser issue noted above: the label branch overwrites the boundary stamp on `text-opacity`. That's pre-existing and **out of scope** for this fix. The Item-3 fix doesn't make it worse.
- **No backend/API impact.** Pure frontend paint stamping.

---

## Cross-cutting notes

### Sequencing
The three items are independent. Recommended commit order matches user-impact ordering from the memory:
1. Item 1 (toast hardening + test) — `fix(builder): dedupe + extend popup-config-invalid toast`
2. Item 2 (e2e test fix) — `test(builder): update bulk-delete e2e to SP-01 overflow-menu architecture`
3. Item 3 (boundary symbol symmetry) — `fix(builder): stamp icon-opacity on boundary subtle to match text dim`

### Memory accuracy assessment
Two of the three memory claims required revision after verification:
- **Item 1:** memory framed root cause as "toast not firing"; the verification shows the toast IS firing — the bug (if real) is either Sonner duration aging out before the user looks, or a one-off observation that couldn't be reproduced. Recommended fix is hardening (dedupe id + longer duration + test coverage) rather than chasing a phantom bug.
- **Item 2:** memory framed as a "mousedown race flake." Verification shows the test is structurally broken vs SP-01 architecture, not flaky — its selector `[role="toolbar"] button[aria-label*="Delete"]` cannot match the portal-rendered DropdownMenuItem. The "passes most of the time" line in the memory contradicts the code state and is likely stale.
- **Item 3:** memory description was accurate (with a 26-line offset). 1-line fix as recommended.

### Test infrastructure
- Item 1: vitest exists, mock pattern established at `use-builder-save.test.ts:59`. Pure additive.
- Item 2: Playwright test exists; pure additive (no fixture or helper changes needed).
- Item 3: vitest exists at `basemap-utils.test.ts:311`; pure additive (new `it()` inside existing describe block).

### Rebuild requirements
- Item 1: frontend only; Vite HMR picks up the change. No Docker rebuild needed.
- Item 2: test-only change. No build needed.
- Item 3: frontend only; Vite HMR. No Docker rebuild.

Backend untouched across all three items.

### Combined verify gate
```bash
cd /Users/ishiland/Code/geolens/frontend
./node_modules/.bin/tsc -b
./node_modules/.bin/vitest run \
  src/components/builder/hooks/__tests__/use-builder-save.test.ts \
  src/lib/__tests__/basemap-utils.test.ts
cd /Users/ishiland/Code/geolens
npx playwright test e2e/builder-v1-5.spec.ts -g "multi-select bulk delete happy: 2 rows" --project=chromium
```

Expected: `tsc -b` exit 0, vitest green, playwright passes (post-Item-2 fix).
