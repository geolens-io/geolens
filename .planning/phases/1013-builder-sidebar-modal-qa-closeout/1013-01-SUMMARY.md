---
phase: 1013-builder-sidebar-modal-qa-closeout
plan: 01
status: complete_with_browser_env_caveat
completed: 2026-05-12
requirements: [QA-01, QA-02, QA-03, QA-04, QA-05, QA-06]
commits: []
---

# Phase 1013 Summary: Builder Sidebar/Modal QA Closeout

## Completed

- Aligned `e2e/builder.spec.ts` with the redesigned sidebar:
  - Added desktop/tablet Add Dataset dialog checks for search, All/Vector/Raster/Basemap tabs, basemap `in use` / `swap`, and Import data routing.
  - Updated basemap switching to use the new inline `Swap basemap` popover.
  - Replaced the old collapsed basemap-list DOM assertion with a popover-scoped option assertion.
- Added `e2e/accessibility.spec.ts` coverage for the Add Dataset dialog with axe scoped to `[role="dialog"]`.
- Re-ran focused unit/component coverage for renderAs, stack grouping, sidebar row behavior, duplicate renderings, basemap/terrain writes, and Add Dataset modal states.

## Requirement Coverage

- **QA-01:** Covered by `renderAs.test.ts` supported/punted option checks.
- **QA-02:** Covered by `map-stack.test.ts` and `MapStackPanel.test.tsx` for dataset headers, basemap grouping, terrain grouping, and zoom writes.
- **QA-03:** Covered by `use-builder-layers.test.ts`, `MapStackPanel.test.tsx`, and `DatasetSearchPanel.test.tsx`; `is_3d` is asserted absent from renderAs patches.
- **QA-04:** Covered by `DatasetSearchPanel.test.tsx` for `swap`, `in use`, `Add to map`, `(added)`, and `another rendering` states.
- **QA-05:** Repeatable Playwright coverage now exists for desktop/tablet modal/sidebar checks and Add Dataset modal a11y. Live execution is blocked locally because the app stack is not reachable.
- **QA-06:** Focused Vitest, lint, and build pass; the broader browser smoke blocker is documented below.

## Verification

- `cd frontend && npm run test -- DatasetSearchPanel MapStackPanel map-stack renderAs use-builder-layers --run`
  - Result: failed due Vitest fork worker startup timeouts before four files could start; one file passed. Treated as runner environment instability.
- `cd frontend && npx vitest run --passWithNoTests src/components/builder/__tests__/renderAs.test.ts src/components/builder/__tests__/map-stack.test.ts src/components/builder/__tests__/MapStackPanel.test.tsx src/components/builder/__tests__/DatasetSearchPanel.test.tsx src/components/builder/hooks/__tests__/use-builder-layers.test.ts --pool=threads --maxWorkers=1`
  - Result: passed — 5 files, 61 tests.
- `cd frontend && npm run lint`
  - Result: passed.
- `cd frontend && npm run build`
  - Result: passed; existing large `map-vendor` chunk warning remains.
- `npx playwright test e2e/builder.spec.ts e2e/accessibility.spec.ts --project=chromium --list`
  - Result: passed — specs load and list 26 tests including the new Add Dataset modal and modal a11y checks.
- Local browser execution readiness:
  - `curl --max-time 3 http://localhost:8080` returned `000`.
  - `curl http://localhost:8000/health` returned `000` / connection refused.
  - `docker ps` and `docker compose ps` hung and were killed.
  - Playwright MCP navigation to `http://localhost:8080/maps` timed out after 60s.

## Caveat

The browser specs were updated and syntactically validated, but the live Playwright smoke could not be executed in this environment because the full local app stack is unavailable and Docker is unresponsive. This is an environment/runbook blocker, not an observed UI regression.
