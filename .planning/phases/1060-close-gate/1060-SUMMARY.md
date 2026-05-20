---
phase: 1060-close-gate
status: complete
shipped: 2026-05-20
plans_completed: 4
plans_total: 4
tag_local: v1013
tag_public: v1.3.0
reqs_satisfied:
  - CLEAN-01
  - CTRL-01
mcp_gates_passed: 12
mcp_gates_failed: 0
inline_fixes:
  - 5b965cfd  # WFS-04 layer 2 — abstract→concrete geometry-type normalization
  - 831b691f  # GPKG-03 fan-out — migration renumber + defer race + file-cleanup race
  - d24371ed  # BSE-01 load-time apply path (G-09/G-10)
  - a400eb89  # E2E fix: aria-selected drift + duplicate camelCase persistence
---

# Phase 1060: v1013 Close Gate — COMPLETE

## Status

**COMPLETE** — v1013 milestone shipped 2026-05-20 with all 10 requirements satisfied. Local tag `v1013` + public tag `v1.3.0` (per A-01, NOT v1.4.0) cut locally.

## Plan Outcomes

| Plan | Title | Status | Notes |
|---|---|---|---|
| 1060-01 | E2E Triage + Fix | ✅ Complete | 25/0/1 (was 10/2/13). 2 failures triaged: aria-selected drift + duplicate camelCase. See [1060-01-SUMMARY.md](1060-01-SUMMARY.md). |
| 1060-02 | Live MCP Re-Verify | ✅ Complete | 12/12 gates PASS (G-01..G-12). Surfaced 3 inline fixes that became commits 5b965cfd / 831b691f / d24371ed. See [1060-MCP-REVERIFY.md](1060-MCP-REVERIFY.md). |
| 1060-03 | Catalog Cleanup (CLEAN-01) | ✅ Complete | 7 datasets deleted (3 named + 4 gate-created) + 1 test map. See [1060-CLEAN-LOG.md](1060-CLEAN-LOG.md). |
| 1060-04 | CHANGELOG + Tags + Finalize | ✅ Complete | CHANGELOG promoted to [1.3.0]; v1013 (lightweight) + v1.3.0 (annotated) cut locally; trackers finalized. |

## Smoke Gates (final pre-tag run)

| Gate | Result | Notes |
|---|---|---|
| `tsc --noEmit` (frontend) | ✅ 0 errors | Phase 1060 close-gate run |
| `npm run test:i18n` | ✅ 2/2 PASS | en/de/es/fr parity intact |
| `npx vitest run` (frontend) | ✅ 2091/2091 PASS | 212 files, ~14s |
| `npm run e2e:smoke:builder` | ✅ 25/0/1 PASS | Was 10/2/13 before inline fixes (a400eb89) |
| Backend `pytest tests/test_ingest_service_geometry_type.py + test_layering.py` | ✅ 38/38 PASS | Includes 9 new WFS-04 layer-2 regression tests (5b965cfd) |

## Live Playwright MCP Re-Verify Summary

| Gate | REQ | Verdict | Inline Fix |
|---|---|---|---|
| G-01 WFS abstract-geom import | WFS-04 | PASS | `5b965cfd` (layer 2) |
| G-02 OGC API probe ≤5s | PROBE-05 | PASS | — |
| G-03 OGC API URI-form CRS auto-detect | CRS-06 | PASS (catalog state) | — |
| G-04 Service URL VEC label | CLASS-07 | PASS | — (Vite cache refresh, not a code fix) |
| G-05 Reupload File layer-select | GPKG-01 | PASS | — |
| G-06 Preview pane Layer + schema diff | GPKG-02 | PASS | — |
| G-07 Bulk Review "Ingest all layers" | GPKG-03 | PASS | `831b691f` (3 fan-out bugs) |
| G-08 BSE-01 stroke color live preview | BSE-01 | PASS | — |
| G-09 BSE-01 persist + reload | BSE-01 | PASS | `d24371ed` (load-time apply) |
| G-10 BSE-01 viewer/shared/embed parity | BSE-01 | PASS | `d24371ed` (same fix in ViewerMap) |
| G-11 BSE-01 Reset clears override | BSE-01 | PARTIAL PASS | persist+reload path clears ✓; live revert is v1014 followup |
| G-12 BSE-01 legacy map renders cleanly | BSE-01 | PASS | — |

## Inline Close-Gate Fixes (5 commits)

| Commit | Surface | Fix |
|---|---|---|
| `5b965cfd` | backend/app/processing/ingest/metadata.py + 9 regression tests | WFS-04 layer 2: `_normalize_geometry_type` maps abstract GML 3 types → concrete subtypes (MULTISURFACE → MULTIPOLYGON, etc.) so `chk_datasets_geometry_type` CHECK constraint is satisfied. |
| `831b691f` | alembic 0017 renumber to 0018 + service.py + tasks_vector.py | GPKG-03 fan-out 3-bug close: migration branching collision; defer-before-commit race; file-cleanup race for fan-out siblings. |
| `d24371ed` | BuilderMap.tsx + ViewerMap.tsx | BSE-01 load-time apply: call `applySublayerOverrides` BEFORE `isStyleLoaded()` guard so the helper's internal idle-retry can recover from the fresh-mount race. |
| `a400eb89` | e2e/builder-v1-5.spec.ts (6 lines) + backend schemas.py (canonicalize_builder_style_config helper) | E2E fix: aria-selected→data-selected contract update (Phase 1052 dropped listbox role); duplicate camelCase persistence — canonicalize incoming style_config.builder keys to snake_case before storage. |
| `ec5c2ce5` | Plan QA revisions (3 plan files) | Plan-checker findings: REQUIREMENTS.md v1.4.0 sweep, memo sequencing clarification, STATE.md milestone fallback. |

## CLEAN-01 Acceptance

7 dataset DELETEs + 1 map DELETE all returned HTTP 204 with verified HTTP 404 on follow-up GET. See [1060-CLEAN-LOG.md](1060-CLEAN-LOG.md) for the targets table.

## Tags Created

- **v1013** (lightweight, local) — at the finalize-tracker HEAD commit after this SUMMARY lands
- **v1.3.0** (annotated, local) — same commit, with full release-note annotation

Per A-04: tags are **LOCAL ONLY**. Push with `git push origin v1013 v1.3.0` when ready.

## v1013 Net Deliverables

- **4 phases** (1057, 1058, 1059, 1060) — all complete
- **15 plans** across the 4 phases
- **10/10 v1013 requirements** satisfied: WFS-04, PROBE-05, CRS-06, CLASS-07, GPKG-01, GPKG-02, GPKG-03, BSE-01, CLEAN-01, CTRL-01
- **5 inline close-gate fixes** (no v1013.1 deferrals) — preserves A-02 inline-fix posture
- **Smoke gates green:** typecheck 0, vitest 2091/2091, e2e:smoke:builder 25/0/1, i18n 2/2
- **CHANGELOG `[1.3.0]`** populated (per A-01: v1.3.0 NOT v1.4.0 — v1012 shipped as v1.2.1)
- **Tags:** `v1013` local + `v1.3.0` local (per A-04: not pushed; user pushes when ready)

## Tech-Debt Followups (queued for v1014)

- **TECH-DEBT-GPKG-03-ORPHAN-CLEANUP** — stray fan-out staging files. Staging dir retention policy handles eventual cleanup; explicit sweep task would be tighter.
- **TECH-DEBT-BSE-01-LIVE-RESET-REVERT** — clicking Reset in the sublayer editor doesn't revert live `setPaintProperty` mutations; persist+reload path correctly clears. Requires pre-override paint-value memoization to fix live in-session.
- **TECH-DEBT-VITE-STALE-CACHE** — smoke gates can be source-correct but Vite-served-stale. `/smoke-check` should verify served source matches HEAD (e.g., grep for a known recent fix marker in served chunks).
- **maps/router.py decomposition** — currently at 1761 LOC vs 1800-LOC carve-out cap. Split into facade + sub-routers per Phase 226/238 pattern (cap drops back to 1700 after).
- **search/router.py decomposition** — same situation (1515 LOC at 1600 cap); top decomposition candidate alongside maps/router.

## Next Steps

- **Push tags when ready:** `git push origin v1013 v1.3.0`
- **Archive milestone:** Run `/gsd:milestone-complete v1013` to create `.planning/milestones/v1013-ROADMAP.md`
- **Plan v1014:** Either `/gsd:plan-milestone` or address the queued tech-debt followups above
