---
phase: 1044-cross-cutting-closeout
reviewed: 2026-05-14T00:00:00Z
depth: quick
files_reviewed: 8
files_reviewed_list:
  - e2e/builder-v1-5.spec.ts
  - e2e/builder.spec.ts
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx
  - frontend/src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - package.json
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 1044: Code Review Report

**Reviewed:** 2026-05-14T00:00:00Z
**Depth:** quick
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 1044 delivers i18n locale fill (de/es/fr), a11y contract tests for UnifiedStackPanel and MapBuilderPage, four new Playwright e2e scenarios covering drag-from-catalog and multi-select bulk-delete, and a smoke script update. All 770 keys are present and structurally consistent across all four locales — no missing keys were found.

The primary concerns are: a `page.waitForTimeout` hard wait in the fallback path of Test 1 (a known antipattern for Playwright reliability), a realistic flakiness scenario in the same test's keyboard-to-pointer fallback (incorrect final count assertion if the keyboard drag partially succeeded), and `dispatchEvent('click')` bypassing Playwright actionability checks in Test 4. The `console.warn` in Test 2 writes to Node stdout (not the browser gate) — this is acceptable. The `XXX` grep hit in `MapBuilderPage.a11y.test.tsx:281` is a comment variable placeholder, not a debug artifact.

Translation quality looks professional. The `search.added` asymmetry (en: `"Added"` bare vs de/es/fr: parenthetical `"(hinzugefügt)"` etc.) is a pre-existing intentional choice, not a phase 1044 regression.

## Warnings

### WR-01: Hard wait `page.waitForTimeout(200)` in Test 1 fallback path

**File:** `e2e/builder-v1-5.spec.ts:220`
**Issue:** `page.waitForTimeout(200)` is a fixed sleep inserted after pressing Escape to cancel an in-progress keyboard drag before the pointer fallback begins. Fixed sleeps are fragile: on slow CI they may not be long enough, and they unconditionally slow the suite on fast machines. Playwright guidance is to replace sleeps with deterministic state assertions.
**Fix:** Replace with a condition wait that asserts the drag state has settled. For example, wait for the row count to stabilize or for an aria-live "drop cancelled" announcement:
```typescript
// Instead of: await page.waitForTimeout(200);
await expect(
  page.locator('[data-testid="dnd-announcement"]'),
).not.toContainText(/picked up/i, { timeout: 2_000 }).catch(() => {});
// or simply: await expect(overlayRows).toHaveCount(initialCount, { timeout: 3_000 });
```

### WR-02: Keyboard-to-pointer fallback can assert wrong final count if keyboard drag silently succeeded

**File:** `e2e/builder-v1-5.spec.ts:185-250`
**Issue:** If the keyboard drag actions (Space → ArrowDown x5 → Space) add a layer but the subsequent `toHaveCount(initialCount + 1)` assertion times out (e.g., slow DOM update) before the 10-second deadline, the `catch` block fires, `addedByKeyboard` stays `false`, and the test falls through to the pointer fallback. At that point `countAfterKeyboardAttempt` would be `initialCount + 1` (layer already added), so the pointer drag would add a second unexpected layer. The test would then assert `initialCount + 2`, not `initialCount + 1`, producing a false-positive result while leaving the map in a 4-layer state that could confuse Tests 3 and 4 if they run in the same serial describe. (The describe is `test.describe.serial`, so state does bleed between tests.)
**Fix:** After the `catch` and before the pointer fallback, explicitly verify the row count did not already increase:
```typescript
} catch {
  // Keyboard cross-context drop failed — fall back to pointer simulation
}

if (!addedByKeyboard) {
  // Guard: ensure keyboard attempt did not silently add a layer.
  // If count already increased, treat as success to avoid double-add.
  const countBeforeFallback = await overlayRows.count();
  if (countBeforeFallback > initialCount) {
    // Keyboard drag succeeded despite the assertion timeout — skip pointer fallback
    addedByKeyboard = true;
  }
}

if (!addedByKeyboard) {
  // ... pointer fallback ...
}
```

### WR-03: `dispatchEvent('click')` bypasses Playwright actionability checks in Test 4

**File:** `e2e/builder-v1-5.spec.ts:478, 507`
**Issue:** Two `dispatchEvent('click')` calls are used to avoid the mousedown race with the outside-click selection-clear handler. While the surrounding `toBeVisible` assertions are present (lines 477, 506), `dispatchEvent` also bypasses enabled/interactable checks. If the button is present but disabled (e.g., race between state updates), the dispatch fires a click on a disabled button and the test continues with no error, producing a false-positive. The comment accurately documents the intent, but the risk is silent mis-behavior under race conditions.
**Fix:** Add an explicit enabled state check before dispatching, or use `locator.click({ force: true })` which bypasses the mousedown activation distance while still respecting visibility (though it also bypasses actionability). The safest option with least regression risk:
```typescript
await expect(deleteBtn).toBeEnabled({ timeout: 3_000 });
await deleteBtn.dispatchEvent('click');
// ...
await expect(deleteConfirmBtn).toBeEnabled({ timeout: 3_000 });
await deleteConfirmBtn.dispatchEvent('click');
```

## Info

### IN-01: `search.added` format differs between English and translated locales

**File:** `frontend/src/i18n/locales/de/builder.json:395`, `frontend/src/i18n/locales/es/builder.json:395`, `frontend/src/i18n/locales/fr/builder.json:394`
**Issue:** The English source has `"added": "Added"` (title-case, no parentheses), while all three translated locales use a parenthetical form: `"(hinzugefügt)"`, `"(agregado)"`, `"(ajouté)"`. This is a pre-existing inconsistency (introduced in commit `fdf5dc6c`) not created in phase 1044, but phase 1044 is the first time translated locales have been filled for this key. The parenthetical form in translations suggests they were modeled on an older English value.
**Fix:** Align all locales to a consistent format. Either update English to `"(Added)"` or update translations to drop parens. Coordinate with UX on which form the UI spec intends.

### IN-02: `XXX` marker in comment at `MapBuilderPage.a11y.test.tsx:281` triggers grep-based lint gates

**File:** `frontend/src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx:281`
**Issue:** The string `a11y.XXX` appears in a documentation comment describing the pattern `t('a11y.XXX', ...)`. Quick-scan lint tools and CI grep gates that flag `XXX` as a debug artifact will produce a false positive here.
**Fix:** Rephrase to avoid the literal token:
```typescript
// The handlers call announce(t('a11y.<event>', ...)) which updates the aria-live region
```

---

_Reviewed: 2026-05-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
