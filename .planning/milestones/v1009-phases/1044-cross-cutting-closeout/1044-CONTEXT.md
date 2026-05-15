---
phase: 1044
phase_name: cross-cutting-closeout
status: ready_for_planning
generated: auto (workflow.skip_discuss=true)
date: 2026-05-15
---

# Phase 1044: cross-cutting-closeout — Context

**Gathered:** 2026-05-15
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Close the v1009 milestone with i18n locale fill for every new v1.5 string (en/de/fr/es), accessibility verification for the two new keyboard paths (drag-from-catalog + multi-select), a Playwright UAT spec covering happy + negative paths for both features, and final builder smoke green with the UAT spec added to the smoke set.

**Requirements:** POL-22, POL-23, POL-24, POL-25

**Success Criteria:**
1. Switching browser locale to en/de/fr/es and walking the builder shows all new v1.5 strings translated; `i18n-check` smoke green.
2. Keyboard-only drag-from-catalog flow (Space pick → Arrow nav → Space drop, Escape cancel) and multi-select flow (Shift+ArrowUp/Down + Space); listbox advertises `aria-multiselectable`.
3. `e2e/builder-v1-5.spec.ts` covers drag-from-catalog happy path, multi-select bulk-delete happy path, Escape-cancels-mid-drag negative path, mixed basemap+overlay bulk-delete blocked.
4. `npm run e2e:smoke:builder` shows 21 existing tests + new builder-v1-5.spec all green.

**Depends on:** Phases 1040, 1041, 1042, 1043 (all merged).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion (`workflow.skip_discuss=true`).

### Hard Constraints (v1009)
- No saved-map shape changes
- No public viewer / shared / embed surface changes
- Sketch-findings tokens only
- No new backend endpoints
- Existing Playwright + smoke patterns

### i18n locale fill scope
- Fill de/es/fr placeholders for ALL new v1009 keys: `bulkActions.*`, `a11y.*`, `toasts.datasetAdded`, `toasts.basemapChanged`, `search.dragHandle`, `search.retry`, all phase 1043 error/empty/source/settings keys, all `basemapGroup.toggleExpand` and `basemapSublayer.*` keys
- Use professional translations (not machine-translation placeholders); align with existing en patterns and tone
- Per memory: existing locale parity gate via `frontend/src/i18n/__tests__/resources.test.ts` — must remain green

### a11y verification
- Verify: aria-multiselectable="true" on listbox; data-row-id on rows; Shift+Arrow keyboard nav; Space toggle; Escape clearing
- Add axe smoke check on the builder route if not already there
- Document keyboard-only walkthrough for both new features

### Playwright UAT
- New file: `frontend/e2e/builder-v1-5.spec.ts`
- 4 scenarios: drag-from-catalog happy, multi-select bulk-delete happy, drag Escape-cancel negative, basemap+overlay mixed bulk-delete blocked negative
- Add to `npm run e2e:smoke:builder` set

### Smoke green
- Final `npm run e2e:smoke:builder` must report 21 + 1 = 22 passing
- typecheck + vitest baseline maintained (843+)

</decisions>

<code_context>
## Existing Code Insights

Surfaces touched:
- `frontend/src/i18n/locales/{de,es,fr}/builder.json` (locale fill)
- `frontend/src/components/builder/UnifiedStackPanel.tsx` (a11y verify)
- `frontend/src/pages/MapBuilderPage.tsx` (a11y aria-live)
- `frontend/e2e/builder-v1-5.spec.ts` (NEW Playwright spec)
- `frontend/e2e/` smoke configuration (add new spec to smoke set)
- `frontend/src/i18n/__tests__/resources.test.ts` (parity gate)
- Existing builder e2e tests for pattern reference

</code_context>

<specifics>
## Specific Ideas

### i18n keys to fill (per phase commits, not yet exhaustive — pattern mapper will enumerate)
- Phase 1040: `toasts.datasetAdded`, `toasts.basemapChanged`, `search.dragHandle`, `a11y.dragPickup`, `a11y.dragDropped`, `a11y.dragCancelled`, `a11y.dragPosition`
- Phase 1041: `bulkActions.*` (22 keys), `unifiedStack.listboxLabel`
- Phase 1042: (no new locale keys; just dedup of duplicate block)
- Phase 1043: `search.retry`, `search.added`, EmptyStackState starter-help, `errors.*`, `source.noColumns`, `settings.*` (22 keys), `basemapGroup.toggleExpand`, `basemapSublayer.*` (4 keys), `search.metadata.*` (5 keys), other `search.*` keys

### Playwright spec structure
```
test.describe('Builder v1.5 (drag-from-catalog + multi-select)', () => {
  test('drag-from-catalog happy: vector dataset onto stack', ...)
  test('drag-from-catalog negative: Escape cancels mid-drag', ...)
  test('multi-select bulk delete happy: 2 rows', ...)
  test('multi-select negative: basemap + overlay mixed selection blocked', ...)
});
```

### a11y check
- Existing axe smoke or new check on `/builder` route after navigating to a map
- Verify keyboard walkthrough manually + document in spec comment block

</specifics>

<deferred>
## Deferred Ideas

- New i18n locales beyond de/es/fr — out of scope
- Visual snapshot testing — only basic e2e behavior coverage
- Performance benchmarks — out of scope

</deferred>
