# Phase 1014: Browser Baseline And Responsive Shell - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning
**Source:** v1003 requirements, v1002 Playwright MCP follow-up, and current repository state.

<domain>
## Phase Boundary

Phase 1014 establishes browser-backed confidence for the v1002 sidebar/Add Dataset redesign. It owns responsive shell behavior, Add Dataset modal visibility at desktop/tablet widths, focused accessibility coverage, and the post-v1002 tablet persisted-sidebar fix.

This phase is hardening and verification. It should not add schema fields, new renderers, catalog endpoints, or import workflows.
</domain>

<decisions>
## Implementation Decisions

### Browser Baseline
- Use the existing app stack at `http://localhost:8080` and existing Playwright auth setup.
- Prefer existing specs: `e2e/builder.spec.ts`, `e2e/builder-styling.spec.ts`, and focused builder accessibility checks in `e2e/accessibility.spec.ts`.
- Use Playwright MCP for manual evidence that is hard to capture in assertions: current Map Stack state, Add Dataset modal state, tablet layout metrics, and console health.

### Responsive Shell
- Keep the v1002 follow-up decision from commit `003a03ea`: persisted desktop sidebar width remains in localStorage, but rendered width is capped on tablet/narrow desktop to leave at least 320px of map canvas.
- Treat the tablet persisted-width case as a first-class regression because it was discovered by Playwright MCP manual verification.

### QA Scope
- Phase-owned gates are focused frontend gates, builder smoke, scoped builder accessibility, and Playwright MCP manual checks.
- Full backend, SDK, CLI, and release gates are outside this phase unless a phase-owned frontend change requires them.
</decisions>

<specifics>
## Specific Checks

- Force `localStorage.geolens-builder-sidebar-width = "600"` at `834x1112` and verify rendered sidebar width is capped to `470px` with a `320px` map canvas.
- Confirm Add Dataset modal tabs are visible and fit at tablet width.
- Confirm Basemap tab shows inactive rows as `swap` and active current basemap as `in use`.
- Confirm browser console has no errors/warnings beyond expected React DevTools development info.
</specifics>

<deferred>
## Deferred Ideas

- Duplicate-rendering interaction depth belongs to Phase 1015.
- Basemap/terrain save-reload integration belongs to Phase 1016.
- Add Dataset state transitions beyond baseline modal visibility belong to Phase 1017.
- Saved-map/public-viewer round trips belong to Phase 1018.
</deferred>

---
*Phase: 1014-browser-baseline-and-responsive-shell*
*Context gathered: 2026-05-12*
