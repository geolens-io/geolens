---
milestone: v1003
milestone_name: Builder v1 Hardening
status: passed
audited: 2026-05-12T14:07:01Z
phases: [1014, 1015, 1016, 1017, 1018]
requirements: 24
requirements_complete: 24
recommendation: GO
---

# v1003 Milestone Audit: Builder v1 Hardening

## Result

Status: `passed`

The milestone goal is satisfied: the v1002 builder sidebar and Add Dataset redesign now has real-browser, accessibility, save/reload, and viewer compatibility coverage without schema changes, renderer additions, or new catalog/import capabilities.

## Phase Completion

| Phase | Status | Plans | Verification |
|-------|--------|-------|--------------|
| 1014 Browser baseline and responsive shell | Complete | 1/1 | Vitest, builder smoke, accessibility Playwright, lint, build, Playwright MCP passed |
| 1015 Duplicate rendering and renderAs hardening | Complete | 1/1 | duplicate-rendering Playwright, focused Vitest, builder smoke passed |
| 1016 Basemap and terrain integration hardening | Complete | 1/1 | basemap persistence Playwright, focused terrain/basemap Vitest, builder smoke, lint, Playwright MCP passed |
| 1017 Add Dataset modal state hardening | Complete | 1/1 | modal-state Playwright, focused modal Vitest, builder smoke, lint passed |
| 1018 Saved map roundtrip and closeout | Complete | 1/1 | zoom-range round-trip Playwright, save/viewer Vitest, builder smoke, lint, build, Playwright MCP passed |

## Requirement Coverage

| Group | Requirements | Status |
|-------|--------------|--------|
| Browser baseline and responsive shell | BQA-01..05 | 5/5 complete |
| Duplicate rendering and renderAs behavior | DUP-01..05 | 5/5 complete |
| Basemap and terrain integration | MAPCTL-01..05 | 5/5 complete |
| Add Dataset modal state hardening | ADDH-01..05 | 5/5 complete |
| Saved-map round trip and closeout | ROUND-01..04 | 4/4 complete |

Total: 24/24 v1003 requirements complete.

## Key Accomplishments

1. Added browser-backed baseline coverage for the redesigned builder shell, Add Dataset modal, tablet sidebar clamp, and scoped accessibility checks.
2. Proved duplicate renderings from both layer row overflow and Add Dataset modal entry points.
3. Proved Add Dataset basemap swap state syncs with the sidebar and persists through save/reload without creating basemap layer rows.
4. Proved modal tab/filter/row expansion/import routing contracts in the real builder.
5. Added a saved-map round-trip test for layer zoom-range layout plus map/layer response key stability.
6. Strengthened builder save and public/shared viewer tests for basemap and terrain compatibility.

## Verification Summary

- Focused Vitest suites passed across all phases.
- Builder smoke passed at closeout: `26 passed`.
- Scoped accessibility Playwright checks passed in Phase 1014.
- Frontend lint passed.
- Frontend production build passed with the existing large `map-vendor` chunk warning.
- Playwright MCP inspected the live authenticated builder after closeout with 0 console errors and 0 warnings.

## Known Caveats

- Backend pytest, SDK/OpenAPI drift checks, CLI tests, and packaging/release gates were not rerun. They are outside v1003's frontend builder hardening scope.
- Browser DEM terrain provisioning remains covered by deterministic component/unit tests rather than a seeded DEM E2E fixture.
- The build still emits the pre-existing `map-vendor` chunk-size warning.

## Recommendation

GO. v1003 is complete and can be archived/tagged when the user wants to run the milestone completion workflow.
