# Phase 1007: Durable Builder QA Gate and Closeout - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning
**Source:** Roadmap, v1001 requirements, Phase 1002 implementation inventory, and Phase 1003-1006 summaries/verification.

<domain>
## Phase Boundary

Convert the v1001 builder polish work into repeatable automated QA. This phase should not introduce new builder product behavior unless a test exposes a small deterministic coverage blocker. The durable gate must cover the polished create/edit/style/preview/save/share/public-output workflow without assuming seeded demo maps by default.

## Required Outcomes

- QA-01: focused builder regression suite runs without seeded demo maps unless a test explicitly opts in.
- QA-02: known builder sidebar drag-handle flake is removed or replaced by deterministic behavior coverage.
- QA-03: Playwright asserts desktop, tablet, and mobile builder UI state rather than relying only on screenshots.
- QA-04: accessibility checks cover builder and public saved-map outputs, excluding only MapLibre canvas internals.
- QA-05: screenshot evidence is recorded only where visual judgment is genuinely required.
- QA-06: focused Vitest coverage protects touched builder components, hooks, adapters, and public-output alignment.

</domain>

<decisions>
## Implementation Decisions

### Locked Decisions

- Keep this phase focused on QA gates and closeout artifacts.
- Use API-created temporary maps/datasets for Playwright coverage so demo seed data is optional, not required.
- Replace the pointer-drag sidebar-resize smoke with deterministic keyboard slider coverage. The component already exposes the resize handle as a `role="slider"` with ArrowLeft/ArrowRight behavior.
- Preserve existing Phase 1003-1006 component and adapter tests as the focused Vitest base, adding narrow assertions only where Phase 1007 finds a gap.
- Screenshot artifacts are not a default success condition. Record screenshot paths only if visual judgment is needed during execution.

### Finding Closure Inputs

- F-1002-02: auth shell/token-user-null route state was fixed in Phase 1006; Phase 1007 should keep regression coverage in focused Vitest and/or Playwright gate selection.
- F-1002-06: mobile shell and footer artifacts were fixed in Phase 1006; Phase 1007 should assert mobile sheet state and map context dimensions.
- F-1002-08: basemap recovery copy was fixed in Phase 1006; Phase 1007 should include it in focused a11y/Vitest coverage, not broad visual QA unless failures appear.

</decisions>

<specifics>
## Prior Phase Summary

- Phase 1003: omitted add-layer sort order now appends; Map Stack empty state is data-first; row states expose selected/hidden/locked/disabled/unsupported/error-like signals; inspector focus is visible.
- Phase 1004: style/filter/label/popup controls are grouped and scoped, with recoverable validation and tests preserving `paint`, `style_config`, style JSON, and public render alignment.
- Phase 1005: public/shared/embed viewer layer identity uses stable IDs; shared-token payloads include layer IDs; save/share states communicate saved/unsaved/saving/failed/retry.
- Phase 1006: authenticated map routes restore user before editor chrome, suppress footer artifacts, improve mobile sheet/touch targets, and surface localized basemap recovery copy.

## Candidate Test Surfaces

- `e2e/builder.spec.ts`: focused builder workflow and current flaky sidebar pointer-drag test.
- `e2e/accessibility.spec.ts`: existing axe coverage for builder, to extend with public saved-map/shared output coverage.
- `frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx`: mocked page-shell coverage suitable for deterministic resize assertions.
- Existing focused Vitest suites for Map Stack, style, filters, labels, popups, viewer layer identity, public viewers, share panel, save hook, auth shell, BuilderMap a11y/unit, and i18n resources.

</specifics>

<deferred>
## Deferred Ideas

- Full seeded thematic demo smoke remains opt-in through `E2E_DEMO_SEEDED=1`.
- Full server-side thumbnail generation remains OPS-01/NEXT-04.
- A broad screenshot gallery is out of scope unless a specific visual regression requires human judgment.

</deferred>

---
*Phase: 1007-durable-builder-qa-gate-and-closeout*
*Context gathered: 2026-05-11*
