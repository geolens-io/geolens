---
milestone: v1002
milestone_name: Layer Sidebar + Add Dataset Redesign
status: tech_debt
audited: 2026-05-12T11:55:00Z
phases: [1008, 1009, 1010, 1011, 1012, 1013]
requirements: 37
requirements_complete: 37
recommendation: COMPLETE_WITH_BROWSER_ENV_REVIEW
---

# v1002 Milestone Audit: Layer Sidebar + Add Dataset Redesign

## Result

Status: `tech_debt`

The milestone goal is satisfied: the layer sidebar and Add Dataset modal were redesigned over the existing schema with zero migrations, no new persisted entities, and no new renderer capabilities. The only closeout caveat is environmental: live Playwright execution could not run locally because the full stack was unavailable and Docker commands were unresponsive.

## Phase Completion

| Phase | Status | Plans | Verification |
|-------|--------|-------|--------------|
| 1008 Sidebar view-model and renderAs foundation | Complete | 1/1 | focused Vitest, lint, build passed |
| 1009 Layer row and dataset-rendering sidebar | Complete | 1/1 | focused Vitest, lint, build passed |
| 1010 RenderAs actions and duplicate renderings | Complete | 1/1 | focused Vitest, lint, build passed |
| 1011 Basemap and terrain inline rows | Complete | 1/1 | focused Vitest, lint, build passed |
| 1012 Add Dataset modal redesign | Complete | 1/1 | focused Vitest, lint, build passed |
| 1013 Builder sidebar/modal QA closeout | Complete | 1/1 | focused Vitest/lint/build passed; Playwright specs load; live browser execution blocked by local stack |

## Requirement Coverage

| Group | Requirements | Status |
|-------|--------------|--------|
| Schema and Architecture | ARCH-01..04 | 4/4 complete |
| Sidebar and Stack | STACK-01..05 | 5/5 complete |
| RenderAs and Duplicate Renderings | RENDER-01..08 | 8/8 complete |
| Basemap and Terrain | BASE-01..04, TERRAIN-01..02 | 6/6 complete |
| Add Dataset Modal | ADD-01..08 | 8/8 complete |
| Quality Gates | QA-01..06 | 6/6 complete |

Total: 37/37 v1002 requirements complete.

## Key Accomplishments

1. Established a pure renderAs utility and preserved the existing Map Stack view-model contract.
2. Reworked layer rows with renderAs, opacity, zoom range, duplicate-rendering, and terrain actions while preserving existing map-layer fields.
3. Added collapsible dataset-rendering headers when multiple layers share a dataset id, with no schema change.
4. Wired renderAs changes to existing `layer_type`, `style_config`, `paint`, and `layout` fields, with tests proving `is_3d` is never written.
5. Consolidated basemap and terrain controls inline while writing only map-level basemap and terrain fields.
6. Redesigned Add Dataset around current search APIs, supported filters, row expansion, basemap swap/in-use states, Add/added/another-rendering states, and ImportPage routing.
7. Added Playwright coverage for the redesigned modal/sidebar states and Add Dataset modal accessibility.

## Verification Summary

- Focused Vitest rerun passed with a single worker: 5 files / 61 tests.
- Frontend lint passed.
- Frontend build passed with the existing large `map-vendor` chunk warning.
- Playwright spec loading passed: `npx playwright test e2e/builder.spec.ts e2e/accessibility.spec.ts --project=chromium --list` listed 26 tests, including the new Add Dataset modal and modal accessibility checks.
- Initial default Vitest run hit fork worker startup timeouts before four files could start; a single-worker rerun passed, so this is recorded as runner instability rather than a test failure.

## Known Caveats

- Live Playwright browser execution was blocked in this environment:
  - `curl --max-time 3 http://localhost:8080` returned `000`.
  - `curl http://localhost:8000/health` returned `000` / connection refused.
  - `docker ps` and `docker compose ps` hung and were killed.
  - Playwright MCP navigation to `http://localhost:8080/maps` timed out after 60s.
- Full release gates, SDK/OpenAPI checks, backend suites, and full E2E smoke were not rerun. This is acceptable for v1002 because the milestone is frontend-only and schema-preserving, but live browser smoke should be rerun once the local stack is healthy.

## Recommendation

COMPLETE_WITH_BROWSER_ENV_REVIEW. Archive v1002 and tag it, with the explicit follow-up that builder/accessibility Playwright specs should be executed on a healthy local stack or CI runner.
