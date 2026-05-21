---
quick_id: 260514-ajo
description: Run through the smoke checks and fix any issues
created: 2026-05-14
---

# Quick Task 260514-ajo: Run through the smoke checks and fix any issues

## Scope

Execute the GeoLens E2E smoke suites (core + builder + fixtures), identify
failures introduced by the v1008 Map Builder Sidebar Redesign (which deferred
the smoke-test sweep — see milestone v1008 close), and fix them so the suites
return to green.

## Tasks

1. **Inventory failures.** Run each suite, capture failing test names + first
   error per test, and decide per-test whether the underlying feature still
   exists (rewrite to new selectors) or was removed in v1008 (delete the test).

2. **Fix any real product bugs surfaced by the suites.** Distinguish
   "test is stale" from "code is broken" using the on-page error context.

3. **Rewrite stale tests to the new v1008 selectors.**
   - `id="stack-row-{layerId}"` replaces `data-testid="layer-item-{id}"`
   - `data-testid="builder-layer-editor"` flyout replaces tab-based panel
   - Collapsible "Filter"/"Labels"/"Source" sections inside the flyout replace
     the per-tab structure
   - Basemap is a top-of-stack `stack-row-basemap-group` with a flyout-based
     PRESET picker (no inline popover)
   - "Close layer editor" replaces "Back to layers" on desktop; the mobile
     drill-down Sheet keeps "Back to layers"

4. **Delete tests for v1008-removed features.** No collapse-sidebar toggle,
   no resize-handle slider, no per-row "zoom to layer" action.

5. **Confirm green:** Re-run `npm run e2e:smoke` end-to-end.

## Verify

- `npm run e2e:smoke:core` → all pass
- `npm run e2e:smoke:builder` → all pass
- `npm run e2e:smoke:fixtures` → all pass

## Done

All three smoke suites return zero failures on a healthy local stack.
