---
gsd_state_version: 1.0
milestone: v13.11
milestone_name: Map Builder Polish & Quality Sweep
status: completed
stopped_at: "279-02 complete: ADMIN-03 (server-driven enterprise-tabs registry — backend frozenset extended to {branding,appearance} + new GET /admin/settings/enterprise-tabs/ + frontend useEnterpriseOnlyTabs hook + AdminSidebar fallback) in 49a43c78 + 299aef9e; ADMIN-04 (FORMAT_HANDLERS dispatcher replaces 501 → 502 audit-export gate) in 49a43c78; 6-test backend static-analysis regression suite in 9a6c256f; 4-test frontend regression suite in 299aef9e. Sibling plans: 279-01 in flight, 279-03 pending, 279-04 complete."
last_updated: "2026-05-07T22:54:00.000Z"
last_activity: "2026-05-07 — 279-02 complete: ADMIN-03 server-driven enterprise-tabs + ADMIN-04 unified audit-export FORMAT_HANDLERS dispatcher; 8 new tests (6 backend + 4 frontend, 2 incl. existing); zero regressions"
progress:
  total_phases: 14
  completed_phases: 4
  total_plans: 29
  completed_plans: 31
  percent: 100
---

# State

## Current Position

Phase: 258 — Line-Gradient UI Closeout
Plan: 258-02 complete (Phase 258 all plans shipped)
Status: Phase 258 complete — Plans 01+02 shipped
Last activity: 2026-05-07 — 258-02 complete: POLISH-06 stable per-stop UUID keys; type extension + memoized hydration + key={stop.id} + 4 regression tests

Progress: [██████████] 100%

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-07)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v13.11 Map Builder Polish & Quality Sweep — Phase 258 (ready to plan)

## Last Shipped Milestone

**Version:** v13.10 GH Issues Hygiene
**Shipped:** 2026-05-07
**Phases:** 257 (1 phase, 3 plans, 0 source-file changes)
**Requirements:** 8/8 satisfied (AUDIT-01..02, CLOSE-01..02, LEFTOVER-01..02, TRACKER-01..02)
**Archive:** `.planning/milestones/v13.10-ROADMAP.md`

## v13.11 Phase List

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 258 | Line-Gradient UI Closeout | POLISH-01..07, COPY-01 | Complete (2 plans) |
| 259 | i18n Translations | COPY-02 | Not started |
| 260 | Builder Quality Sweep | QUALITY-01..04 | Not started |
| 261 | Layer Visibility Debug & Audit | LAYER-01..02 | Not started |
| 262 | Milestone Closeout | CLOSE-01..02 | Not started |

**Total:** 5 phases, 17/17 requirements mapped

## Accumulated Context

- BUILDER-POLISH-01 promoted from deferred (PROJECT.md Out of Scope) to v13.11 active scope (2026-05-07).
- Phase 256 UI audit source: `.planning/milestones/v13.9-phases/256-line-gradient-builder-ui/256-UI-REVIEW.md` — 18/24 score, 1 BLOCKER (gradient preview swatch) + 6 minor findings, all in `LineGradientControls.tsx`.
- Phase 261 (LAYER-01..02) carries the highest investigation risk — unknown root cause; treat as debug + audit; may surface sibling regressions.
- Phase 262 depends on all other phases; must run last.
- 259 and 260 are independent of each other and can run in parallel after Phase 258 completes.

## Pending Todos

- `2026-05-05-recreate-public-repo-before-launch.md` — pre-launch repo strategy (still pending)
- `2026-05-07-phase-256-ui-audit-blocker-backlog-gradient-preview-swatch.md` — BUILDER-POLISH-01 (will be closed by Phase 262)

## v13.13 Side-Track Activity

Plan 276-03 (OSS-side overlay-dispatch tests for Branding/Auth/Audit Extensions, CODE-03) executed 2026-05-07 alongside v13.11 winddown. Single commit `d9a20890`. Closes M-11 / M-54 audit findings inline.

Plan 276-01 (architecture LOC cap + service_diff comment + Identity quoting, CODE-01/CODE-09/CODE-14) executed 2026-05-07 alongside v13.11 winddown. Commits `57d02014` (test RED), `d968f567` (test GREEN), `0029a98d` (Identity quoting comment). CODE-09 docstring edit orphan-attributed to commit `2483cc31` (functional state correct at HEAD; race with concurrent Plan 276-05 executor). Closes M-09 / L-08 / L-55. New architecture-guard at `backend/tests/test_layering.py:804`.

Plan 276-05 (auth-store version+migrate + 3 cross-feature store relocations, CODE-04/CODE-05) executed 2026-05-07 alongside v13.11 winddown. Three commits: `2483cc31` (Task 1 — auth-store version: 1 + migrate scaffold, 4 new tests), `08642d8d` (Task 2 finish — moved-store test self-import paths), `caf4cd83` (Task 3 — DOM-level smoke substitute for Playwright MCP UAT, 9 new tests). The bulk of Task 2's work (6 store renames + 32 consumer-import updates) landed in side-effect commit `53392993` due to multi-active parallel-agent commit-race; functional state at HEAD is correct (1216 vitest tests passing; bundle sizes unchanged; zero stale imports). Closes M-41 / M-42 / L-41. Task 3 Playwright MCP UAT deferred to manual reviewer verification — see `.planning/phases/276-backend-frontend-code-quality/276-05-SUMMARY.md` "Playwright UAT" section for the 4-flow checklist.

Plan 276-04 (broad-except annotation sweep + architecture-guard, CODE-08) executed 2026-05-07 alongside v13.11 winddown. Two commits: `927a6770` (Task 1 — chore: 113 sites annotated across 59 files with theme-clustered `# broad: <reason>` rationales; 0 sites tightened to specific exception classes; total broad-except site count preserved at 139), `0303398f` (Task 2 — test: new `test_no_unjustified_broad_except_sites` architecture-guard at `backend/tests/test_layering.py` mirrors Phase-226 grep-based pattern; negative-control verified via `git add -f` sandbox file). Closes L-09. Annotation theme distribution: 26 cache, 22 SDK boundary, 19 PostGIS fallback, 14 ingest pipeline, 12 geometry parse, 8 sandbox/sweeper, 7 cleanup, 5 SSE generator. Wider behavior verification: ~330 DB-backed integration tests passed across 16 test files exercising the modified modules. Pre-existing `test_no_catalog_imports_processing` failure (`backend/app/modules/catalog/maps/service_public.py:186` comment-line mention) confirmed pre-existing; not blocking.

Phase 276 progress: 4/7 plans complete (276-01, 276-03, 276-04, 276-05). STATE remains pinned to v13.11 milestone; a future v13.13 milestone-start will repoint STATE and re-anchor the progress bar.

Plan 278-04 (frontend test cleanup — SourcesTab it.todo migration + VrtCreatorForm setTimeout → waitFor, TEST-07/TEST-08) executed 2026-05-07 alongside v13.11 winddown. Single new commit `ab2ba3e8` (refactor — VrtCreatorForm selectSource helper compound waitFor against input-cleared + dropdown-button-absent). TEST-07 was preemptively shipped by parallel agent in `ced17b2f` (commit titled "refactor(278-03): … (TEST-05)"); zero-diff at HEAD for SourcesTab.test.tsx and `.planning/backlog/SourcesTab-test-todos.md` when 278-04 began. Commit `ab2ba3e8` also inadvertently included `e2e/dataset-detail.spec.ts` from a concurrent 278-06 (TEST-10) agent — orphan attribution; functional state at HEAD correct (mirrors v13.12 Phase 269 race-condition pattern). Closes TEST-07 + TEST-08. Phase 278 progress: 4/6 plans complete (278-02, 278-03, 278-04, 278-06).

Plan 278-05 (mock-assertion sample-audit + pytest.skip migration, TEST-06/TEST-09) executed 2026-05-07 alongside v13.11 winddown. Two commits: `79560030` (refactor — TEST-06: 6/6 mock-call-count assertions in `test_phase_273_startup_warnings.py` converted to behavior-style `assert_not_called`/`assert_called_once_with` matching against canonical structlog event names + verbatim message kwargs; one-shot regression guard preserved by re-asserting `assert_called_once_with` after second invocation) and `95d619ec` (refactor — TEST-09: 29 inline `pytest.skip` calls migrated to `@pytest.mark.skipif` decorators across 6 backend files via 9 module-level constants; 9 inline skips retained with `# pytest.skip kept inline:` justification comments — all module-level `allow_module_level=True`, runtime-interpolated reasons, or after-meaningful-work). Backend collection topology byte-identical at 2541/2555 tests; pass/skip/fail topology delta is a strict improvement (2 vrt_titiler tests previously errored on async DB fixture before reaching their inline `_check_titiler()` skip; with the gather-time decorator gate they now correctly skip — 7 errors → 5 errors, 1 skip → 3 skips, total preserved at 45). Reusable behavior-assertion template documented in SUMMARY for the remaining ~84 mock-assertion sites elsewhere in the codebase. Closes TEST-06 + TEST-09. Phase 278 progress: 5/6 plans complete (278-02, 278-03, 278-04, 278-05, 278-06).

Plan 278-01 (coverage threshold ratchets, TEST-01/TEST-02) executed 2026-05-07 alongside v13.11 winddown. Two commits: `18aef1aa` (chore — TEST-01: backend `fail_under` raised 58.5 → 60 with inline rationale comment citing TEST-01/Phase 278 + ratchet methodology; baseline actual 77.02% leaves 17pt headroom — further ratchet deferred to follow-up round once unrelated test-collection errors `test_tile_cache.py` cachetools import + `test_phase_272_compose.py` setup are resolved) and `4d13ad3d` (chore — TEST-02: frontend coverage thresholds ratcheted 32/27/27/32 → 41/39/37/42 statements/branches/functions/lines with inline rationale + actuals + per-dim deltas; plan-prescribed `+2` buffer (43/41/39/44) failed all 4 dims because actuals 41.51/39.42/37.99/42.69 sit < 1pt above their integer floors and the plan's `+1` fallback would also fail for the same reason — landed at `+0` (= floor(actual)) with explicit rationale comment so next ratchet round understands the choice). All 1239 frontend tests + 2333 backend tests passing at new thresholds; gate-fail loud on >1.5pt regression. Closes TEST-01 + TEST-02. Phase 278 progress: 6/6 plans complete (278-01, 278-02, 278-03, 278-04, 278-05, 278-06).

Plan 279-04 (CI + Docker hygiene, ADMIN-10/11/12/13) executed 2026-05-07 alongside v13.11 winddown. Four commits: `50b28b0b` (feat — ADMIN-10 + ADMIN-12: MinIO bumped from RELEASE.2025-04-22T22-12-26Z to RELEASE.2025-09-07T16-13-09Z and pinned by `@sha256:14cea493...`; mc bumped from RELEASE.2025-04-22T03-17-43Z to RELEASE.2025-08-13T08-35-41Z and pinned by `@sha256:a7fe349e...`; `docker compose --profile cloud-dev pull` + healthcheck verified against new digests), `a146fc83` (fix — ADMIN-11: stale `--ignore-vuln CVE-2026-4539` removed from `.github/workflows/ci.yml` pip-audit step; verified locally that `pip-audit --strict --desc` produces zero matches for that CVE — pip is now patched; remaining two carve-outs CVE-2026-3219 + CVE-2026-6357 stay pending pip 26.1 base-image refresh), `9001c485` (feat — ADMIN-13: non-blocking `license-check` job added to ci.yml that runs `npx license-checker --json` against the frontend dependency tree and uploads a 30-day-retention `license-report` artifact; `continue-on-error: true` on the run step + zero `needs:` dependents so license-list changes can't block PR merge; aligned to repo conventions actions/upload-artifact@v7 + actions/setup-node@v6 + node-version: 22), `3cc9ec68` (test — 5 static-analysis regression tests in `backend/tests/test_phase_279_compose_ci.py` locking all four invariants: minio/mc digest pin shape + date > 2025-04-22, no `--ignore-vuln CVE-2026-4539` in non-comment ci.yml lines, `license-check` job exists, no other job lists `license-check` in `needs:`). Local dry-run produced a 194 KB license-report.json. Closes ADMIN-10 + ADMIN-11 + ADMIN-12 + ADMIN-13. Phase 279 progress: 1+/4 plans tracked (279-04 complete; sibling plans 279-01..03 running in parallel wave-1).

## Session Continuity

Last session: 2026-05-07T22:51:53.601Z
Stopped at: 279-04 complete: ADMIN-10 + ADMIN-12 (MinIO RELEASE.2025-09-07T16-13-09Z + mc RELEASE.2025-08-13T08-35-41Z, both digest-pinned) in 50b28b0b; ADMIN-11 (CVE-2026-4539 ignore removed, pip patched) in a146fc83; ADMIN-13 (non-blocking license-check job + 30-day artifact) in 9001c485; 5-test regression suite in 3cc9ec68. Phase 279 progress: 1+/4 plans tracked.
Resume file: None
