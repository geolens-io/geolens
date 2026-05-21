---
phase: 260424-n9f
plan: 01
subsystem: frontend/navigation
tags: [feature-flag, navbar, dataset-editing, conditional-rendering]
dependency_graph:
  requires: [useFeatureFlags, usePermissions]
  provides: [feature-flag-gated-create-menu]
  affects: [Navbar, CreateMenu, MobileNav]
tech_stack:
  patterns: [feature-flag-gating, defensive-UI-hiding]
key_files:
  modified:
    - frontend/src/components/layout/Navbar.tsx
decisions:
  - "Used IIFE pattern in MobileNav JSX for inline variable scoping (matches plan guidance)"
  - "Used ?? false nullish coalescing to match existing DatasetPage.tsx pattern"
metrics:
  duration: 1m
  completed: 2026-04-24
---

# Quick Task 260424-n9f: Disable Create Dataset Option in Navbar

Feature-flag-gated Dataset menu item in both desktop CreateMenu and mobile MobileNav using enable_dataset_editing flag from useFeatureFlags() hook.

## What Changed

### Task 1: Gate Dataset item and add Create visibility guard
**Commit:** `ba3b82dc`

- Added `useFeatureFlags` import from `@/hooks/use-settings`
- **CreateMenu (desktop):** Added `canCreateDataset` boolean derived from `featureFlags?.enable_dataset_editing ?? false`; wrapped Dataset `DropdownMenuItem` in conditional render; added `hasAnyCreateItems` guard that hides entire Create button when no items are visible
- **MobileNav (mobile):** Added same feature flag consumption; wrapped Dataset button in conditional render; wrapped entire Create section (separator + label + items) in `hasAnyCreateItems` guard
- Dialog renders (`CreateDatasetDialog`, etc.) left unconditional -- harmless when trigger is hidden, avoids unmount issues

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- TypeScript compilation: passed (only pre-existing baseUrl deprecation warning, unrelated)
- Manual verification: requires `enable_dataset_editing: false` in admin feature flags settings

## Self-Check: PASSED
