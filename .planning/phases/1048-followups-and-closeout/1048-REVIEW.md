---
phase: 1048-followups-and-closeout
reviewed: 2026-05-16T23:03:45Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - e2e/builder.spec.ts
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 1048: Code Review Report

**Reviewed:** 2026-05-16T23:03:45Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Phase 1048 is a hygiene/closeout phase covering popup_config 422 detection, BulkActionBar polish, i18n locale parity, SourcesTab test drain, and e2e builder coverage. The locale key sets are in full parity across all four locales with genuine translations (no English-copied values for any of the new keys). The BulkActionBar's `isDeleting` spinner path and confirmation flow are logically sound.

One blocker was found: the popup_config pre-check in `use-builder-save.ts` produces a false positive — it blocks save for any layer with an enabled popup expression when `dataset_column_info` is null, because it treats an empty column list as "all placeholders unknown". This can silently prevent a user from saving a map with a valid popup configuration if the API did not include column metadata for that layer.

Four warnings cover: an incorrect TypeScript type cast in the 422 error handler, a flaky-in-CI async pattern in the SourcesTab add-source-picker test, a dead/orphaned locale key that was superseded but is still present in all four files, and a misleading test comment that contradicts the assertion it describes. Three info items cover minor code-quality notes.

---

## Critical Issues

### CR-01: Popup pre-check false-positive when `dataset_column_info` is null

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:373-382`

**Issue:** The popup validation guard reads `l.dataset_column_info ?? []` — meaning when the API response does not include column metadata for a layer (the field is typed as `{ name: string; type: string }[] | null`), the effective column list is empty. `validatePlaceholders(extractPlaceholders(expression), [])` will always return `{ ok: false }` for any non-empty expression that contains at least one placeholder. This causes `handleSave` to block the save and surface `toasts.popupConfigInvalidNamed` even when the popup expression is perfectly valid — the user has done nothing wrong.

The backend `_build_layer_response` does include `column_info` from the DB join for normal map loads, so the common case is fine. However, any code path that constructs a `MapLayerResponse` without column metadata (e.g. a newly-added layer whose dataset metadata hasn't been re-fetched yet, a race condition on initial load, or a mocked/partial API consumer) will silently block save.

**Fix:** Guard against the null case by skipping the pre-check when column metadata is unavailable rather than treating the empty list as authoritative:

```typescript
const invalidLayer = localLayers.find((l) => {
  const cfg = l.popup_config;
  if (!cfg?.enabled || !cfg.expression) return false;
  // Skip validation when column metadata is absent — the server is the authoritative gate.
  if (!l.dataset_column_info) return false;
  const columns = l.dataset_column_info.map((c) => c.name);
  return !validatePlaceholders(extractPlaceholders(cfg.expression), columns).ok;
});
```

---

## Warnings

### WR-01: `loc as string[]` type cast is incorrect — array may contain integers

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:456`

**Issue:** FastAPI validation error `loc` arrays contain both strings (field names) and integers (array indices), e.g. `['body', 'layers', 0, 'popup_config', 'expression']`. The code casts `popupLocItem.loc as string[]` which lies to TypeScript — element `[2]` is a `number`. The subsequent `loc.indexOf('popup_config')` and `loc.slice(popupIdx).join('.')` happen to work at runtime because `Array.prototype.join` coerces elements with `toString()`, but the type assertion is factually wrong and masks the actual runtime shape. If `join('.')` is called on a path that includes an index, the result may contain a numeric segment (e.g. `"popup_config.0.expression"`) which is surfaced in the user-facing toast text via `{{field}}`.

**Fix:**

```typescript
const loc = popupLocItem.loc as Array<string | number>;
const popupIdx = loc.indexOf('popup_config');
const field = loc.slice(popupIdx).join('.');
```

---

### WR-02: `toasts.popupConfigInvalid` is a dead key — retained in all four locales but never referenced in source

**File:** `frontend/src/i18n/locales/en/builder.json:617` (and corresponding lines in de/es/fr)

**Issue:** The `toasts.popupConfigInvalid` key ("Cannot save: one or more layers have invalid popup expressions") exists in all four locale files. A grep of the entire `frontend/src/` tree confirms no source file references this key — it was superseded by `toasts.popupConfigInvalidNamed` in phase 1048. The old key is dead weight and its presence is misleading (the test file even has a comment noting "the NEW key (not popupConfigInvalid) is used"). Dead i18n keys have a low failure risk but accumulate over time and were flagged in the v13.10 hygiene milestone.

**Fix:** Remove `toasts.popupConfigInvalid` from all four locale files.

---

### WR-03: SourcesTab add-source-picker test is fragile in slow CI — real 300 ms debounce + 1000 ms default `findByText` timeout

**File:** `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx:301-344`

**Issue:** The "add source picker filters out already-linked sources" test fires `fireEvent.change` to set the search query, then immediately calls `await screen.findByText('New COG Dataset')`. The component has a 300 ms `setTimeout` debounce before setting `debouncedQuery`, after which TanStack Query fires the `searchDatasets` mock. The `findByText` default timeout is 1000 ms. On a sufficiently slow CI runner, the chain (debounce 300 ms + React reconciliation + Query microtask + DOM mutation) can exhaust the 1000 ms window, producing a spurious timeout failure without any code change. No fake timers are used in this test.

**Fix:** Either advance the debounce with fake timers or increase the `findByText` timeout:

```typescript
// Option A — explicit timeout
const newResult = await screen.findByText('New COG Dataset', {}, { timeout: 3000 });

// Option B — fake timers
vi.useFakeTimers();
fireEvent.change(searchInput, { target: { value: 'cog' } });
act(() => { vi.advanceTimersByTime(300); });
vi.useRealTimers();
const newResult = await screen.findByText('New COG Dataset');
```

---

### WR-04: SourcesTab "renders source table with rows in position order" test comment contradicts its assertion

**File:** `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx:178-197`

**Issue:** The test name says "in position order" and the comment says "component should render them in API order (by position)." But the assertion verifies the opposite: with input `[{position:1, title:'B'}, {position:0, title:'A'}]`, `rows[1]` is expected to be `'Source COG B'` (position 1) — meaning the component renders in raw API order, NOT sorted by `position` ascending. The test correctly verifies the absence of client-side sorting, but the comment "API order (by position)" is misleading — it implies position-ascending order when in fact the API order is preserved as-is regardless of position values. A future developer reading this might add a sort thinking they're fixing a bug.

**Fix:** Correct the comment:

```typescript
// Supply sources in reverse position order — component should preserve API arrival order
// (no client-side sort by position). Sorting, if any, must happen server-side.
```

---

## Info

### IN-01: `cursor-not-allowed` on container div is overridden by child element cursors on most browsers

**File:** `frontend/src/components/builder/BulkActionBar.tsx:135`

**Issue:** When `isDeleting=true`, the outer `<div role="toolbar">` receives `cursor-not-allowed`. However the child `<Button disabled>` element also carries `cursor-not-allowed` (line 162), and other children (the `<span>` and `<Loader2>`) inherit the container cursor. This produces the intended visual, but the container-level class is redundant — disabled buttons already apply `cursor-not-allowed` via Tailwind's `disabled:cursor-not-allowed` convention, and non-interactive children default to inheriting. The container class adds no protection against accidental pointer interaction since all children are already non-interactive when `isDeleting=true`.

**Fix:** The `cursor-not-allowed` on line 135 can be removed without changing behavior. Low priority.

---

### IN-02: `popup_config` e2e test (FOLLOWUP-01) leaves a layer with `popup_config: null` after cleanup — no assertion that the reset succeeded

**File:** `e2e/builder.spec.ts:829-839`

**Issue:** The test manually resets the layer's `popup_config` to `null` via a PATCH call inside the test body (lines 832-839). It asserts `clearRes.ok` but does not assert that the layer's `popup_config` is actually null when the builder reloads. If the backend silently accepts the PATCH but does not persist the null (e.g., due to an optional-field schema that ignores explicit nulls), the success-path save would be blocked again by the pre-check. The existing behavior in the backend is to accept and persist null for `popup_config`, so this is low risk — but a poll assertion after the clear would make the test self-documenting.

**Fix:** Add a quick verification:

```typescript
const verifyRes = await getMapLayers(mapId, authHeaders);
const clearedLayer = verifyRes.find((l) => l.id === layer.id);
expect(clearedLayer?.popup_config).toBeNull();
```

---

### IN-03: `makeLayer` in test factory omits the `popup_config` field entirely — relies on `MapLayerResponse` allowing optional field

**File:** `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts:137-162`

**Issue:** The `makeLayer` factory does not include `popup_config` in its default shape. `MapLayerResponse.popup_config` is typed as `PopupConfig | null` (non-optional at line 1072 of `api.ts`). When the factory omits it, the resulting object has `popup_config: undefined` at runtime, which differs from `null`. The pre-check in `handleSave` uses `!cfg?.enabled` which handles `undefined` the same way as `null`, so no test currently fails — but the factory produces objects that don't strictly conform to the type, which could mask a future regression where `undefined` vs `null` matters.

**Fix:** Add `popup_config: null` to the `makeLayer` defaults:

```typescript
function makeLayer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    // ... existing fields ...
    popup_config: null,
    ...overrides,
  };
}
```

---

_Reviewed: 2026-05-16T23:03:45Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
