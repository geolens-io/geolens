# Phase 1015: Duplicate Rendering And RenderAs Hardening - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1003 requirements, v1002 implementation, and current test inventory.

<domain>
## Phase Boundary

Phase 1015 proves duplicate renderings and v1 renderAs behavior from both sidebar and Add Dataset entry points. Existing unit/component tests already cover the pure renderAs option map, field patch discipline, row action wiring, dataset-rendering headers, and modal `another rendering` handler wiring.

The phase-owned gap is browser-level proof that the wired UI actions create real sibling `MapLayer` rows against the backend.
</domain>

<decisions>
## Implementation Decisions

### Browser Coverage
- Extend `e2e/builder.spec.ts` rather than adding a new spec, because the builder smoke already creates a temporary map/layer and cleans it up.
- Use the existing authenticated Playwright storage state and API token helper for API-level assertions before/after UI actions.
- Keep assertions behavior-oriented: layer count increases, sibling `dataset_id` matches, dataset-rendering header count updates, and no UI error toasts appear.

### RenderAs Coverage
- Reuse existing focused unit/component coverage for renderAs option support and no `is_3d` writes.
- Do not add broad browser coverage for every renderAs option in this phase; browser renderAs save/reload belongs with deeper styling coverage if gaps appear.
</decisions>

<specifics>
## Specific Checks

- Row overflow `Duplicate rendering` creates a second map layer with the same `dataset_id`.
- Add Dataset modal `another rendering` creates a third map layer with the same `dataset_id`.
- The Data group shows a dataset-rendering header with `2 renderings` then `3 renderings`.
- Unsupported renderers remain covered by `renderAs.test.ts`.
</specifics>

<deferred>
## Deferred Ideas

- Basemap/terrain save-reload proof belongs to Phase 1016.
- Modal filter/row expansion depth belongs to Phase 1017.
- Full saved-map/public round-trip belongs to Phase 1018.
</deferred>

---
*Phase: 1015-duplicate-rendering-and-renderas-hardening*
*Context gathered: 2026-05-12*
