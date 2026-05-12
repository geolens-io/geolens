# Phase 1017: Add Dataset Modal State Hardening - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1003 requirements, Phase 1012 implementation, and current modal test inventory.

<domain>
## Phase Boundary

Phase 1017 proves the Add Dataset modal behaves as a stateful, schema-preserving catalog picker over existing APIs. Existing component tests already cover supported search filters, Add/added/another-rendering states, basemap swap/in-use states, inline row expansion, and `/import` link rendering.

The phase-owned gap is browser-level proof that the modal exposes those affordances in the real builder: tab contract, unsupported scope-chip absence, keyboard-expandable rows, metadata/action visibility, and routing to the existing ImportPage.
</domain>

<decisions>
## Implementation Decisions

### Browser Coverage
- Extend `e2e/builder.spec.ts` because it already creates an authenticated temporary map and ensures at least one dataset exists.
- Keep the browser test read-only except for navigation to `/import`; mutation-heavy Add/another-rendering flows are already covered by Phase 1015.
- Query by accessible roles and names so keyboard and screen-reader contracts stay visible in the test.

### Filter Contract
- Assert unsupported scope chips (`Curated`, `Your imports`, `Public`) are absent by role/name.
- Reuse `DatasetSearchPanel.test.tsx` as the source of truth for supported `record_type`, `source_organization`, and `keywords` search params.
</decisions>

<specifics>
## Specific Checks

- Add Dataset tabs remain `All`, `Vector`, `Raster`, and `Basemap`.
- Unsupported scope chips are absent.
- A dataset row can be expanded from the keyboard.
- Expanded row shows metadata and a primary row action.
- Footer `Import data...` link navigates to `/import`.
- Existing component tests continue to prove filter params and state transitions without a full page reload.
</specifics>

<deferred>
## Deferred Ideas

- Exact drag-from-modal insertion remains punted from v1.
- Curated/Your imports/Public chips remain deferred until backend API contract exists.
- Saved-map/public round-trip closeout belongs to Phase 1018.
</deferred>

---
*Phase: 1017-add-dataset-modal-state-hardening*
*Context gathered: 2026-05-12*
