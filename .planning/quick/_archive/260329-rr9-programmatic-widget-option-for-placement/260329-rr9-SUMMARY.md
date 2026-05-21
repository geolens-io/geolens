---
phase: 260329-rr9
plan: 01
subsystem: map-widgets
tags: [widget-system, type-refactor, sidebar, animation]
dependency_graph:
  requires: []
  provides: [widget-placement-api, widget-sidebar-panel]
  affects: [map-builder, widget-registrations]
tech_stack:
  added: []
  patterns: [discriminated-union-placement, css-translate-animation, always-render-slide-over]
key_files:
  created:
    - frontend/src/components/map-widgets/WidgetSidebar.tsx
  modified:
    - frontend/src/components/map-widgets/types.ts
    - frontend/src/components/map-widgets/register-widgets.ts
    - frontend/src/components/map-widgets/WidgetHost.tsx
    - frontend/src/components/map-widgets/index.ts
decisions:
  - "WidgetSidebar always renders when sidebar registrations exist (avoids mount/unmount animation issues)"
  - "WidgetErrorBoundary exported from WidgetHost (not extracted to separate file) for simplicity"
  - "WidgetSidebar export deferred to Task 2 in index.ts to keep Task 1 tsc-clean"
metrics:
  duration: 2min
  completed: 2026-03-29
  tasks: 2
  files: 5
---

# Quick Task 260329-rr9: Programmatic Widget Placement Summary

**One-liner:** WidgetSlot replaced by WidgetAnchor + WidgetPlacement discriminated union with new WidgetSidebar slide-over panel using CSS translate animation.

## What Was Built

Replaced the flat `slot: WidgetSlot` field on `WidgetDefinition` with a structured `placement: WidgetPlacement` discriminated union supporting two modes:

- `{ mode: 'floating', anchor: WidgetAnchor }` — renders widget in an absolute map corner (existing behavior)
- `{ mode: 'sidebar', side: 'left' | 'right' }` — renders widget in a new `WidgetSidebar` slide-over panel

The new `WidgetSidebar` component uses Tailwind `transition-transform duration-200 ease-out` with `translate-x-full` / `-translate-x-full` to animate the panel in/out. The container always mounts when sidebar widget registrations exist, avoiding mount/unmount animation flash. The panel becomes `pointer-events-none` when translated off-screen.

## Tasks Completed

| Task | Name | Commit |
|------|------|--------|
| 1 | Migrate type system and update registrations | 391784b6 |
| 2 | Create WidgetSidebar and update WidgetHost rendering | dbe5847d |

## Decisions Made

- **Always-render pattern:** `WidgetSidebar` renders when `allSidebarWidgets.length > 0` regardless of active state. This enables CSS transition on open — otherwise the panel would snap into position on first mount.
- **WidgetErrorBoundary exported from WidgetHost:** Adding `export` to the existing class was simpler than extracting to a new file. No behavioral change.
- **`_allSidebarWidgets` param kept:** The prop is required by the always-render pattern in WidgetHost but the component itself doesn't need it internally — prefixed with `_` to document intent without lint warning.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written, with the plan-checker constraint applied (WidgetSidebar export deferred to Task 2 to keep Task 1 tsc-clean).

## Known Stubs

None — no placeholder data or hardcoded values.

## Verification

- `npx tsc --noEmit` passes with zero errors
- 817 tests pass across 86 test files (vitest)
- No remaining `WidgetSlot` references in codebase
- Measurement widget: `placement: { mode: 'floating', anchor: 'top-left' }`
- Legend widget: `placement: { mode: 'floating', anchor: 'bottom-left' }`

## Self-Check: PASSED

Files exist:
- frontend/src/components/map-widgets/WidgetSidebar.tsx: FOUND
- frontend/src/components/map-widgets/types.ts: FOUND
- frontend/src/components/map-widgets/WidgetHost.tsx: FOUND

Commits exist:
- 391784b6: FOUND
- dbe5847d: FOUND
