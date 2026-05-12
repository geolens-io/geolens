# Phase 1013: Builder sidebar/modal QA closeout - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1002 requirements, completed Phases 1008-1012, current focused Vitest and Playwright specs

<domain>
## Phase Boundary

Phase 1013 closes v1002 by proving the implementation is repeatably testable and by updating browser checks that still reflect the pre-redesign UI.

The phase owns QA-01..06:
- RenderAs supported and punted options.
- Dataset-rendering headers, basemap row, terrain row, and zoom-range writes.
- Duplicate rendering from sidebar and modal.
- Add Dataset modal action states.
- Desktop/tablet, keyboard, and accessibility coverage.
- Focused lint, build, and test results.
</domain>

<current_state>
## Current Coverage

- `renderAs.test.ts` covers supported v1 renderAs options, unsupported punted renderers, mutation patches, and the `is_3d` read-only contract.
- `use-builder-layers.test.ts` covers renderAs mutation dispatch and duplicate-rendering input shape.
- `map-stack.test.ts` and `MapStackPanel.test.tsx` cover stack grouping, row anatomy, dataset-rendering headers, basemap/terrain rows, zoom-range writes, and sidebar duplicate actions.
- `DatasetSearchPanel.test.tsx` covers modal tabs, supported filters, Add/added/another rendering, swap/in-use basemap states, row expansion, and ImportPage routing.
- `e2e/builder.spec.ts` already covers builder desktop/tablet shell and keyboard navigation, but its basemap tests need to be aligned with the new inline basemap row.
- `e2e/accessibility.spec.ts` covers the builder page itself; the Add Dataset dialog needs explicit modal coverage.
</current_state>

<decisions>
## Implementation Decisions

### Keep QA focused
- Do not add new feature code unless a test exposes a scoped v1002 regression.
- Prefer component tests for schema/mutation guarantees.
- Use Playwright for browser-level layout, keyboard, and modal accessibility checks.

### Browser verification
- Update existing builder E2E assertions to target the new accessible controls (`Swap basemap`, Add Dataset tabs, Import data link) instead of old DOM-specific basemap selectors.
- Add a modal axe check in the existing accessibility spec so Add Dataset is covered separately from the builder page shell.
- Use Playwright MCP for a manual desktop/tablet accessibility snapshot when a local app is reachable.
</decisions>

<verification>
## Planned Gates

- `cd frontend && npm run test -- DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`
- `npm run e2e:smoke:builder` or a narrowed Playwright builder spec if the local stack is running
- A focused accessibility Playwright run for the builder/Add Dataset modal when the local stack is running
</verification>

<deferred>
## Deferred

- Full release gates and SDK/OpenAPI checks remain out of scope because v1002 is frontend-only and schema-preserving.
- Any unrelated seeded-data E2E failures should be documented rather than folded into v1002.
</deferred>

---

*Phase: 1013-builder-sidebar-modal-qa-closeout*
*Context gathered: 2026-05-12 from current code and v1002 requirements*
