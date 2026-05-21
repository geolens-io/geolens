# Quick Task 260424-n9f: Disable "Create > Dataset" when editing flag is false - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Task Boundary

Disable "create > Dataset" option in navbar menu when `enable_dataset_editing` feature flag is set to false. Applies to both desktop `CreateMenu` and mobile `MobileNav` in `frontend/src/components/layout/Navbar.tsx`.

</domain>

<decisions>
## Implementation Decisions

### Hidden vs disabled
- **Hidden**: Remove the Dataset option entirely when `enable_dataset_editing` is false. Matches existing pattern where Import, Collection, and VRT are gated by `can()` permissions.

### Create button visibility
- **Hide the entire Create button** when no menu items are visible (all gated away). Currently Map is always shown so this is a defensive check, but the user wants clean UX with no empty menus.

</decisions>

<specifics>
## Specific Ideas

- Use `useFeatureFlags()` hook (already exists in `frontend/src/hooks/use-settings.ts`)
- Pattern: `featureFlags?.enable_dataset_editing` (matches `DatasetPage.tsx:308`)
- Gate both desktop `CreateMenu` (line 63) and mobile `MobileNav` (line 247) Dataset buttons
- Compute visibility of all items; hide Create button/section if none visible

</specifics>
