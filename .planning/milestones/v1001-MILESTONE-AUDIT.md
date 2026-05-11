---
milestone: v1001
milestone_name: Map Builder UI/UX Polish Sweep
status: passed
audited: 2026-05-11T22:20:00Z
phases: [1002, 1003, 1004, 1005, 1006, 1007]
requirements: 38
requirements_complete: 38
recommendation: GO
---

# v1001 Milestone Audit: Map Builder UI/UX Polish Sweep

## Result

Status: passed

The milestone goal is satisfied: the Map Builder is more coherent, efficient, and trustworthy across create, add-data, edit-layer, style, preview, save, share, public output, desktop, tablet, and mobile workflows. All six phases have summaries and passed verification artifacts.

## Phase Completion

| Phase | Status | Plans | Verification |
|-------|--------|-------|--------------|
| 1002 Kepler-guided builder workflow audit and triage | Complete | 1/1 | passed |
| 1003 Map Stack inspector interaction polish | Complete | 2/2 | passed |
| 1004 Styling and cartography control polish | Complete | 2/2 | passed |
| 1005 Preview, save, share, and output parity | Complete | 1/1 | passed |
| 1006 Responsive, accessibility, and copy hardening | Complete | 1/1 | passed |
| 1007 Durable builder QA gate and closeout | Complete | 1/1 | passed |

## Requirement Coverage

| Group | Requirements | Status |
|-------|--------------|--------|
| Workflow Sweep | FLOW-01..06 | 6/6 complete |
| Map Stack and Inspector | STACK-01..06 | 6/6 complete |
| Styling and Cartography | STYLE-01..08 | 8/8 complete |
| Preview, Save, Share, and Output | OUTPUT-01..06 | 6/6 complete |
| Responsive, Accessibility, and Copy | A11Y-01..06 | 6/6 complete |
| Durable QA Gate | QA-01..06 | 6/6 complete |

Total: 38/38 v1001 requirements complete.

## Key Accomplishments

1. Audited the full builder workflow against Kepler-guided behavior and produced a routed implementation inventory with evidence.
2. Stabilized Map Stack ordering, row states, data-first empty map behavior, and inspector keyboard focus.
3. Polished style, filter, label, popup, raster, and validation controls while preserving `paint`, `style_config`, and style JSON contracts.
4. Aligned builder preview, saved map, shared-token, authenticated public, and embed output around stable layer identity and clearer save/share states.
5. Hardened authenticated route shell state, mobile sheet context, touch targets, i18n copy, and basemap recovery feedback.
6. Converted the polish sweep into durable QA gates: focused Vitest, builder Playwright, builder smoke, and builder/public accessibility coverage.

## Verification Summary

- All phase `*-VERIFICATION.md` artifacts are `status: passed`.
- Phase 1007 focused Vitest passed: 22 files / 215 tests.
- Frontend lint passed.
- Builder Playwright passed: `e2e/builder.spec.ts` 18/18.
- Accessibility Playwright passed: `e2e/accessibility.spec.ts` 8/8.
- Builder-styling Playwright passed: 5/5.
- Builder smoke passed: `npm run e2e:smoke:builder` 22/22.

## Known Caveats

- Full `npm run e2e:smoke` was attempted but the core segment stopped on a collections Add-button seed/UI drift (`collections.spec.ts:91`) before reaching builder smoke: 26 passed / 1 failed / 2 did not run. The builder smoke segment was run directly and passed.
- Demo-themed map smoke remains opt-in with `E2E_DEMO_SEEDED=1`; this is intentional and matches the Phase 1007 requirement.
- No screenshot evidence was recorded for Phase 1007 because automated state and accessibility assertions were sufficient. Prior Phase 1002 visual evidence remains archived for the audit inventory.

## Recommendation

GO. Close v1001 and archive roadmap/requirements artifacts.
