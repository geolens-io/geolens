---
quick_id: 260514-ajo
description: Run through the smoke checks and fix any issues
created: 2026-05-14
completed: 2026-05-14
status: complete
---

# Quick Task 260514-ajo: Smoke check sweep

## Outcome

All three smoke suites pass on a healthy local stack:

| Suite | Result |
|---|---|
| `npm run e2e:smoke:core` | 29/29 pass (41.6s) |
| `npm run e2e:smoke:builder` | 21/21 pass (~1.1m) |
| `npm run e2e:smoke:fixtures` | 6/6 pass (23.6s) |

The smoke-test sweep deferred at v1008 close is now done.

## What changed

### Real product bug (1 fix)

`frontend/src/components/builder/SidebarRail.tsx:91` — the Add data Plus button
wired `onClick={onAddDataClick}`, which passed the React SyntheticEvent as the
`initialQuery` string into `handleAddDataClick`. The event object then flowed
through `setAddDataInitialQuery(event)` and into
`DatasetSearchPanel.useState<string>(initialQuery ?? '')`, so `query` became
the event and `debouncedQuery.trim()` threw
`debouncedQuery.trim is not a function`, taking the page to the error
boundary. Manifested only in rail mode (<1100px viewport), which is why
desktop tests passed and tablet failed.

Fixed by wrapping: `onClick={() => onAddDataClick()}` — mirrors how
`UnifiedStackPanel` already calls it.

### Stale tests rewritten for the v1008 unified-stack + flyout pattern (8 tests)

`e2e/builder-styling.spec.ts`:
- `colors preserved after closing and reopening the layer editor` — configure
  styling within the test (zustand state doesn't survive a page reload), then
  close the flyout via "Close layer editor" and re-open via the stack row.
- `filter editor remains reachable after returning to the map stack` — expand
  the Filter collapsible section by clicking the section button (name matches
  `/^Filter/i` so it skips trailing hint text and "Add filter").
- `label toggle persists after returning to the map stack` — toggle the
  `Enable labels` switch, close, re-open, expand Labels, re-assert.

`e2e/builder.spec.ts`:
- `duplicates dataset renderings from row overflow and Add Dataset modal` —
  use `#stack-row-{id}` + the kebab `[data-kebab-trigger]`, click the
  `Duplicate` menu item, drop the obsolete `dataset-rendering-group` count
  assertion.
- `swaps basemap from Add Dataset modal and persists after save` — assert on
  `#stack-row-basemap-group` containing `Basemap · Dark` (derived preset name
  after stripping the `openfreemap-` prefix) instead of a "Basemap" heading.
- `round-trips layer zoom range without schema drift` — zoom range moved into
  the LayerEditorPanel's Visibility section; fill `Minimum zoom` /
  `Maximum zoom` inputs after clicking the stack row.
- `switches basemap without losing overlay layers` — open the basemap-group
  flyout, click a non-active preset in the PRESET grid, assert overlay
  `stack-row-*` rows are preserved.
- `mobile drill-down opens layer editor sheet and returns via back button`
  (renamed from "mobile sidebar can reach layer editor tabs") — at 390x844
  the rail layer button opens a Sheet (`role="dialog"`) holding the
  LayerEditorPanel; scope assertions to the dialog because
  `data-testid="builder-layer-editor"` is desktop-only.
- `filter condition field remains readable in the default inspector width` —
  open the editor via stack-row click, expand the Filter section, then check
  the existing `filter-field-row` / `filter-value-row` geometry.

### Tests deleted for v1008-removed features (4 tests)

The v1008 redesign replaced the user-toggled collapsible sidebar with a
viewport-driven rail (64px <1100px). These features no longer exist:

- `sidebar collapses with inert attribute and reopens` (was line 277)
- `sidebar resize slider persists keyboard resizing` (was line 793)
- `sidebar collapsed state persists across reload` (was line 840)
- `keeps basemap swap options scoped to the popover` (was line 649) — the
  inline `Swap to ...` popover was replaced by the basemap-group flyout
  PRESET picker
- `zoom to layer changes map viewport` (was line 770) — no row-level
  `Zoom to layer` action in the new StackRow kebab

(Net: 4 deleted tests, 8 rewritten tests; the new suite is 21 tests vs 26
before.)

## Files changed

- `frontend/src/components/builder/SidebarRail.tsx` (+1/-1)
- `e2e/builder-styling.spec.ts` (3 tests rewritten)
- `e2e/builder.spec.ts` (5 tests rewritten, 4 deleted)

## Follow-ups (not in scope)

- The unit-test sweep for v1008 is also outstanding — `LayerPanel`,
  `LayerItem`, and `MapBuilderPage.header-actions.test.tsx`'s
  `builder-sidebar-resize-handle` reference are dead code paths from the
  pre-v1008 builder. They don't run in smoke but should be cleaned up in a
  separate pass.
