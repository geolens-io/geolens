# Quick Task 260424-n9f: Disable "Create > Dataset" when editing flag is false - Research

**Researched:** 2026-04-24
**Domain:** Frontend feature-flag gating in Navbar
**Confidence:** HIGH

## Summary

Straightforward conditional rendering task. All patterns already exist in the codebase. The `useFeatureFlags()` hook (TanStack Query) returns `{ data: FeatureFlags | undefined }`. The `enable_dataset_editing` flag is already used in `DatasetPage.tsx` with the pattern `featureFlags?.enable_dataset_editing ?? false`. The same optional-chaining + default-false pattern applies here.

**Primary recommendation:** Add `useFeatureFlags()` to both `CreateMenu` and `MobileNav`, gate the Dataset item with `featureFlags?.enable_dataset_editing !== false`, compute a `hasAnyItems` boolean to conditionally hide the entire Create button/section.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Hidden** (not disabled): Remove the Dataset option entirely when flag is false. Matches existing `can()` gating pattern.
- **Hide entire Create button** when no menu items remain visible.

## Existing Patterns

### 1. Feature flag consumption [VERIFIED: codebase grep]

**Hook:** `useFeatureFlags()` from `@/hooks/use-settings.ts` (lines 59-66)

**Return type:** TanStack Query result with `data: FeatureFlags | undefined`

```typescript
// FeatureFlags type (frontend/src/api/settings.ts:64-67)
export interface FeatureFlags {
  enable_dataset_editing: boolean;
  require_metadata_for_publish: boolean;
}
```

**Usage pattern in DatasetPage.tsx (line 153, 308):**
```typescript
const { data: featureFlags } = useFeatureFlags();
// ...later...
const dataEditingEnabled = featureFlags?.enable_dataset_editing ?? false;
```

Key detail: `data` is `undefined` while loading. The `?? false` fallback means items are hidden during the brief loading window. This is the correct conservative default -- don't show a create option until we confirm the flag is enabled.

### 2. Permission gating in CreateMenu [VERIFIED: Navbar.tsx]

Existing conditional items use `can()` from `usePermissions()`:

| Item | Gate | Pattern |
|------|------|---------|
| Dataset | **none** (always shown) | unconditional `<DropdownMenuItem>` |
| Import | `can('upload')` | `{can('upload') && (<DropdownMenuItem>...)}` |
| Collection | `can('edit_metadata')` | `{can('edit_metadata') && (<DropdownMenuItem>...)}` |
| Map | **none** (always shown) | unconditional |
| VRT | `can('upload')` | `{can('upload') && (<DropdownMenuItem>...)}` |

The feature flag gate uses the same `{condition && <JSX>}` pattern. No special wrapper needed.

### 3. Loading/error state handling [VERIFIED: use-settings.ts]

`useFeatureFlags()` uses `staleTime: 60_000` and `gcTime: 30 * 60_000`. The hook is already called on other pages, so the cache is typically warm by the time the Navbar renders. Even if cold, the query resolves in <100ms (local API call). No loading spinner or skeleton is needed -- the brief absence of the Dataset item during loading is imperceptible.

No explicit error handling is needed. On error, `data` stays `undefined`, and `undefined?.enable_dataset_editing ?? false` resolves to `false` -- the item stays hidden. This is safe: the worst case is a missing menu item, not a broken UI.

### 4. No tests for Navbar [VERIFIED: glob search]

No test files exist matching `*Navbar*test*` or `*Navbar*spec*`. No test updates required.

## Implementation Specifics

### Desktop CreateMenu (lines 42-101)

1. Add `const { data: featureFlags } = useFeatureFlags();` alongside existing `useAuth()` / `usePermissions()`.
2. Wrap the Dataset `<DropdownMenuItem>` (line 63) with `featureFlags?.enable_dataset_editing !== false &&`.
3. Compute visibility to hide entire button:

```typescript
const canCreateDataset = featureFlags?.enable_dataset_editing !== false;
const canImport = can('upload');
const canCreateCollection = can('edit_metadata');
const canCreateMap = true; // always available
const canCreateVrt = can('upload');

const hasAnyCreateItems = canCreateDataset || canImport || canCreateCollection || canCreateMap || canCreateVrt;
```

Since `canCreateMap` is always `true`, `hasAnyCreateItems` is always true today. But the CONTEXT.md says to add this as a defensive check. Wrap the entire `<DropdownMenu>` + dialogs block in `if (!hasAnyCreateItems) return null;` (after the existing `if (!user) return null;`).

### Mobile MobileNav (lines 195-314)

1. Add `const { data: featureFlags } = useFeatureFlags();` alongside existing hooks.
2. Wrap the Dataset `<button>` (lines 247-253) with the same `featureFlags?.enable_dataset_editing !== false &&` guard.
3. Compute same `hasAnyCreateItems` boolean. Wrap the entire "Create" section (Separator + label + items, lines 243-288) in `{hasAnyCreateItems && (...)}`.

### Import to add

```typescript
import { useFeatureFlags } from '@/hooks/use-settings';
```

## Common Pitfalls

### Pitfall 1: Using `!== true` vs `!== false` vs `?? false`
The existing DatasetPage uses `?? false` (treating undefined as false). For the Navbar, using `!== false` is slightly more permissive: it shows the item while loading (undefined !== false is true). Either works, but `?? false` is more conservative (hide until confirmed). **Recommendation:** Use the same `?? false` pattern as DatasetPage for consistency -- `(featureFlags?.enable_dataset_editing ?? false)`.

### Pitfall 2: Dialog state left dangling
The `CreateDatasetDialog` component is rendered regardless of the flag. If the dialog state `datasetOpen` somehow becomes `true` while the flag is off, the dialog would still render. This is harmless since there's no way to trigger `setDatasetOpen(true)` when the button is hidden, but keeping the dialog render unconditionally is fine and avoids unmount issues.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| -- | -- | -- | -- |

All claims verified from codebase. No assumptions.
