# Phase 1003: Map Stack Inspector Interaction Polish - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Source:** Roadmap, STACK-01..STACK-06, Phase 1002 implementation inventory

<domain>
## Phase Boundary

Make the existing GeoLens Map Stack and layer inspector more predictable, scannable, and operable across pointer, keyboard, desktop, tablet, and mobile workflows.

This phase does not replace the builder architecture, add Kepler.gl as a dependency, or redesign styling/output parity. It builds on the v1000 Map Stack shell and closes the Phase 1002 findings routed to Phase 1003:

- F-1002-01: omitted add-layer `sort_order` creates duplicate layer order.
- F-1002-03: empty builder is not data-first.

</domain>

<decisions>
## Implementation Decisions

### Backend Layer Order
- When add-layer callers omit `sort_order`, GeoLens should assign the next available order for that map.
- Explicit `sort_order` payloads remain honored for import and advanced callers.
- Stable order should be verified with backend coverage for multiple omitted insertions and duplicate dataset insertion.

### Stack Empty State
- Empty maps should present Add Data as the first authoring affordance without removing Surface, Relief, Basemap, Labels, or Interactions from the Map Stack model.
- Technical basemap and terrain controls can remain available, but they should not drown out the first-step data workflow.

### Row State Readability
- Stack rows must make selected, hidden, locked, unsupported, disabled, and error-like states scannable through badges, icons, stable dimensions, and visible focus.
- Duplicate layer disambiguation must remain visible through existing Copy N of M metadata.

### Inspector Operability
- The existing sidebar-local inspector remains the interaction model for desktop and mobile.
- Layer inspector tab focus should be visibly keyboard-operable; tab buttons should be clear controls with stable sizes.
- Primary row actions must remain reachable: selection/inspector, visibility, rename, reorder, legend toggle, zoom, dataset link, and remove.

### Claude's Discretion
- Use minimal changes in existing builder components and tests.
- Prefer focused Vitest/backend tests over broad E2E unless the touched path requires browser-only behavior.
- Keep output parity and public legend stable-ID fixes available for Phase 1005 unless they are necessary to close omitted `sort_order` warnings in Phase 1003.
</decisions>

<specifics>
## Specific Ideas

- Add a compact data-first empty stack prompt above or inside the stack when there are no user layers.
- Suppress or de-emphasize heavy terrain/basemap editor controls on a completely empty map so Add Data is the dominant first step.
- Add row-level selected and state badges/classes without changing existing `layer-item-*` test IDs or the `Expand options` accessible name.
- Add tests for duplicate dataset layer labels, hidden row states, empty prompt ordering, and keyboard-visible inspector/tab affordances.
</specifics>

<deferred>
## Deferred Ideas

- Phase 1004 owns deeper filter/style grouping, validation copy, and cartography controls.
- Phase 1005 owns saved/shared/embed output parity and stable public viewer legend identity if any duplicate legacy maps remain.
- Phase 1006 owns broader auth-shell, mobile sheet height, copy/i18n, and full accessibility hardening.
- Phase 1007 owns durable builder QA and screenshot evidence gates.
</deferred>

---

*Phase: 1003-map-stack-inspector-interaction-polish*
*Context gathered: 2026-05-11 from roadmap, requirements, and Phase 1002 inventory*
