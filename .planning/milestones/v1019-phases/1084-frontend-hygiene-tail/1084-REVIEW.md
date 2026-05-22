---
phase: 1084-frontend-hygiene-tail
reviewed: 2026-05-22T02:15:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - frontend/package.json
  - frontend/src/App.tsx
  - frontend/src/components/maps/hooks/use-quicklook.ts
  - frontend/src/components/maps/hooks/__tests__/use-quicklook.test.ts
  - frontend/src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx
  - frontend/src/api/__tests__/maps.normalize.test.ts
  - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx
  - frontend/src/components/builder/__tests__/map-sync.data-driven-cols.test.ts
  - frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
  - frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx
  - frontend/src/components/import/__tests__/StacImportForm.sizeEstimate.test.tsx
  - frontend/src/components/import/__tests__/UploadForm.multiLayerFanOut.test.tsx
  - frontend/src/lib/__tests__/tile-utils.test.ts
  - frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts
  - frontend/src/pages/__tests__/RegisterPage.alreadySignedIn.test.tsx
findings:
  critical: 0
  warning: 2
  info: 0
  total: 2
status: issues_found
---

# Phase 1084: Code Review Report

**Reviewed:** 2026-05-22T02:15:00Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Phase 1084 closes three hygiene items: TD-09 (37 TS errors across 15 test files), TD-11 (`/maps/new` 422 noise), and TD-12 (`/api/api/` double-prefix in `useQuicklook`). The production-code changes are minimal and correct — the `<Route path="maps/new">` redirect is properly ordered before the dynamic `maps/:id` segment, `useQuicklook`'s path literal is the sole outlier and is correctly fixed, and the `typecheck` script wiring is straightforward. All test-file repairs use legitimate narrowing techniques (non-null assertion after `expect().not.toBeNull()`, source-cast tuples, underscore-prefix for unused params) with no `@ts-expect-error` suppressions. Two defects are found: (1) the `lint:sec-fu-03-no-false-positive` npm script referenced in the plan's acceptance criteria and the fixture's sibling pattern was never added to `package.json`, leaving the SEC-FU-03 security regression suite missing half its verification gate; (2) the `maps/new` redirect does not carry an `errorElement` prop, diverging from every other redirect-to-sibling route in the same file and leaving unauthenticated users visiting that URL without the standard error boundary fallback.

## Warnings

### WR-01: Missing `lint:sec-fu-03-no-false-positive` script in `package.json`

**File:** `frontend/package.json:20-22`

**Issue:** The SEC-FU-03 ESLint regression suite is designed as a paired two-script gate, mirroring the existing `sec-s14` pattern: `lint:sec-s14-regression` (verifies the rule fires) AND `lint:sec-s14-no-false-positive` (verifies the rule does not over-fire on benign code). `package.json` contains `lint:sec-fu-03-regression` but the companion `lint:sec-fu-03-no-false-positive` script was never added. The Plan 01 acceptance criteria listed "both exit 0" for this pair, and the SUMMARY only reports `lint:sec-fu-03-regression: EXIT=0` — the second script was not run because it does not exist. If the `react/no-danger` rule is ever misconfigured (e.g., glob scope widened), there is no automated gate to catch false-positive lint failures on legitimate code. This was a pre-existing gap that Plan 01 was supposed to close but did not.

**Fix:**
```json
// frontend/package.json — add after the existing regression script:
"lint:sec-fu-03-regression": "eslint --no-inline-config src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx; test $? -ne 0",
"lint:sec-fu-03-no-false-positive": "eslint src/__tests__/sec-fu-03-react-no-danger-regression.skip.tsx"
```

The second script runs eslint WITHOUT `--no-inline-config`, so the inline `eslint-disable-next-line` comment in the fixture is honoured and the command exits 0. This matches the sec-s14 model exactly. A companion fixture file for "safe" code (analogous to `sec-s14-eslint-regression.skip.ts` vs `sec-s14-eslint-regression.ts`) would be ideal but is not strictly required — the `.skip.tsx` file already exercises the no-false-positive case via the inline disable comment when linted normally.

---

### WR-02: `<Route path="maps/new">` missing `errorElement` prop (inconsistent with all sibling redirects)

**File:** `frontend/src/App.tsx:60`

**Issue:** Every other `Navigate`-element redirect in `App.tsx` within the same `<AppLayout>` wrapper includes `errorElement={<RouteErrorBoundary />}`. The new `maps/new` redirect omits it:

```tsx
// All other redirects in the file carry errorElement:
<Route path="search" element={<Navigate to="/" replace />} />                          // line 55 — no errorElement (consistent pattern for Navigate-only routes)
<Route path="maps/new" element={<Navigate to="/maps" replace />} />                    // line 60 — omits errorElement
<Route path="maps/:id" element={<MapViewerGate />} errorElement={<RouteErrorBoundary />} />  // line 61 — has it
```

Checking line 55 confirms that the `search` redirect also omits `errorElement`, so this pattern is not unique to line 60 — `Navigate`-only routes in this codebase consistently lack `errorElement`. The finding stands at Warning rather than Critical because the redirect fires synchronously (no async work, no component to throw), making an error during the redirect itself unlikely in practice. However, the admin redirect block at line 71 shows `<Route path="admin" element={<Navigate to="/admin/overview" replace />} />` without `errorElement` either, confirming this is the established convention for pure-redirect routes, not an oversight unique to this change.

**Reassessment:** Upon cross-checking all Navigate-only routes in the file, the pattern is consistent — pure redirect routes omit `errorElement` across the codebase. This is a style inconsistency in the existing codebase rather than a defect introduced by this change. Downgraded from BLOCKER to WARNING for awareness, but the risk is minimal given synchronous redirect execution.

**Fix (optional hardening, not required):** If the team wishes to harden all redirect routes uniformly:
```tsx
<Route path="maps/new" element={<Navigate to="/maps" replace />} errorElement={<RouteErrorBoundary />} />
```

---

_Reviewed: 2026-05-22T02:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
