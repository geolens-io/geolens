---
phase: quick-60
plan: 01
subsystem: frontend
tags: [vrt, dialog, ux-consistency]
dependency_graph:
  requires: [VrtCreatorForm, CreateDatasetDialog pattern]
  provides: [VrtCreateDialog]
  affects: [Navbar, DatasetPage, App routes]
tech_stack:
  added: []
  patterns: [Dialog wrapper with key-remount for clean state]
key_files:
  created:
    - frontend/src/components/import/VrtCreateDialog.tsx
  modified:
    - frontend/src/components/layout/Navbar.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/App.tsx
  deleted:
    - frontend/src/pages/VrtNewPage.tsx
decisions:
  - Key-counter remount pattern for dialog form reset (avoids modifying VrtCreatorForm internals)
  - Removed DropdownMenuSeparator before VRT item in CreateMenu for consistency with other items
metrics:
  duration: 3min
  completed: 2026-03-15
---

# Quick Task 60: Make VRT New Page a Modal (Consistent with Other Create Actions)

VrtCreateDialog wraps VrtCreatorForm in a Dialog with key-remount pattern for clean state on each open; all create dropdown items now open modals.

## What Changed

### Task 1: Created VrtCreateDialog component
- New `VrtCreateDialog.tsx` following the `CreateDatasetDialog` pattern
- Props: `open`, `onOpenChange`, optional `initialSourceId`
- Uses key-counter pattern to remount VrtCreatorForm on each open (clean state without modifying form internals)
- `sm:max-w-2xl` with `max-h-[90vh] overflow-y-auto` for the wider source picker layout
- **Commit:** `50dcd714`

### Task 2: Wired dialog into all entry points, removed /vrt/new route
- **Navbar CreateMenu:** Replaced `<Link to="/vrt/new">` with `onClick={() => setVrtOpen(true)}`; removed `DropdownMenuSeparator`
- **Navbar MobileNav:** Replaced `<NavLink to="/vrt/new">` with button that opens dialog; removed `<Separator>`
- **DatasetPage:** Replaced `<Button asChild><Link to="/vrt/new?source=...">` with `<Button onClick>` and `<VrtCreateDialog initialSourceId={dataset.id}>`
- **App.tsx:** Removed `VrtNewPage` lazy import and `/vrt/new` route
- **Deleted:** `frontend/src/pages/VrtNewPage.tsx`
- **Commit:** `26cdac73`

## Verification

- TypeScript compiles with zero errors
- All 8 VrtCreatorForm tests pass
- No references to `/vrt/new` remain in the codebase
- No references to `VrtNewPage` remain in the codebase
- VrtCreateDialog follows same interface pattern as CreateDatasetDialog, CollectionCreateDialog, MapCreateDialog

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- VrtCreateDialog.tsx: FOUND
- VrtNewPage.tsx: CONFIRMED DELETED
- Commit 50dcd714: FOUND
- Commit 26cdac73: FOUND
