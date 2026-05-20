---
milestone: v1013
audited: 2026-05-20
status: passed
scores:
  requirements: 10/10
  phases: 4/4
  integration: passed (via 12-gate live MCP re-verify aggregated in 1060-MCP-REVERIFY.md)
  flows: passed (G-10 builder + shared + embed parity proven live)
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1060-close-gate
    items:
      - "TECH-DEBT-GPKG-03-ORPHAN-CLEANUP: stray fan-out staging files; staging dir retention policy handles eventual cleanup; explicit sweep task would be tighter."
      - "TECH-DEBT-BSE-01-LIVE-RESET-REVERT: clicking Reset in sublayer editor doesn't revert live setPaintProperty mutations; persist+reload path correctly clears. Requires pre-override paint-value memoization."
      - "TECH-DEBT-VITE-STALE-CACHE: smoke gates can be source-correct but Vite-served-stale; /smoke-check should verify served source matches HEAD."
      - "maps/router.py decomposition queued for v1014 (1761 LOC vs 1800-LOC carve-out cap)."
      - "search/router.py decomposition queued for v1014 (1515 LOC at 1600 cap)."
inline_fixes_applied:
  - 5b965cfd  # WFS-04 layer 2 — abstract→concrete geometry-type normalization
  - 831b691f  # GPKG-03 fan-out — migration renumber + defer race + file-cleanup race
  - d24371ed  # BSE-01 load-time apply path (G-09/G-10)
  - a400eb89  # E2E fix: aria-selected drift + duplicate camelCase persistence
  - ec5c2ce5  # Plan QA revisions (3 plan files)
---

# v1013 Milestone Audit — PASSED

**Milestone:** v1013 Ingest Hardening
**Audited:** 2026-05-20
**Status:** ✅ **PASSED** — all 10 requirements satisfied, all 4 phases complete, integration verified via 12-gate live MCP re-verify

## Phase Status

| Phase | Title | Status | VERIFICATION.md | SUMMARY.md |
|---|---|---|---|---|
| 1057 | Service URL Reliability | ✅ Complete | passed (4/4) | shipped 2026-05-19 |
| 1058 | Multi-Layer GPKG Handling | ✅ Complete | passed (3/3) | shipped 2026-05-19 |
| 1059 | Basemap Sublayer Editor (Path B FIX) | ✅ Complete | passed (4/4) | shipped 2026-05-20 |
| 1060 | Close Gate | ✅ Complete | (acceptance in SUMMARY — close-gate has no separate VERIFICATION.md) | shipped 2026-05-20 |

## Requirements Coverage (10/10 satisfied)

| REQ-ID | Severity | Phase | Status | Evidence |
|---|---|---|---|---|
| WFS-04 | P0 | 1057 | ✅ Satisfied | `c6f13906` (layer 1) + `5b965cfd` (layer 2 close-gate). G-01 live MCP PASS — 241 features ingested. |
| PROBE-05 | P1 | 1057 | ✅ Satisfied | Lazy-enrich at preview time; G-02 measured 1.32s direct API. |
| CRS-06 | P2 | 1057 | ✅ Satisfied | `86b47544`. G-03 catalog state proof via Large Lakes 667a6c65 EPSG:4326. |
| CLASS-07 | P2 | 1057 | ✅ Satisfied | `41e2c617` + Phase 1057 backend kind classification. G-04 VEC:16 RAS:1 post-Vite refresh. |
| GPKG-01 | P0 | 1058 | ✅ Satisfied | Reupload File layer-select step + source_layer pre-selection. G-05 live MCP PASS. |
| GPKG-02 | P1 | 1058 | ✅ Satisfied | Layer name + column-level schema diff in preview pane. G-06 live MCP PASS with data-testid="schema-change-advisory". |
| GPKG-03 | P2 | 1058 (UX) + 1060 (3-bug close) | ✅ Satisfied | POST /ingest/commit-fan-out + 3 inline fixes (`831b691f`). G-07 live MCP PASS — both buildings + addresses datasets created. |
| BSE-01 | Feature | 1059 + 1060 (load-time apply) | ✅ Satisfied | sublayer_overrides jsonb + applySublayerOverrides helper + load-time apply fix (`d24371ed`). G-08..G-12 live MCP PASS across builder/shared/embed. |
| CLEAN-01 | Hygiene | 1060 | ✅ Satisfied | 7 deletes (3 named + 4 gate-created) + 1 map, all verified 204 + 404. See 1060-CLEAN-LOG.md. |
| CTRL-01 | Hygiene | 1060 | ✅ Satisfied | All smoke gates green; 12/12 MCP gates PASS; CHANGELOG promoted to [1.3.0]; tags v1013 + v1.3.0 cut locally. |

## Cross-Phase Integration

| Integration Surface | Verdict | Evidence |
|---|---|---|
| WFS-04 + clip_to_mercator_bounds + dataset.geometry_type | ✅ Working | Two-layer fix (1057 column relax + 1060 type normalize) verified end-to-end. |
| GPKG-03 fan-out → ingest_file × N | ✅ Working | Both per-layer datasets land cleanly post-fix. |
| BSE-01 builder + viewer + shared + embed | ✅ Working | Same applyViewerBasemapConfig helper shared across 3 viewer contexts; tested all 3. |
| frontend normalize-style-config ↔ backend canonicalize_builder_style_config | ✅ Working | Round-trip stays snake_case in DB; React state stays camelCase. Duplicate test pins this. |

## E2E Flows

| Flow | Verdict | Notes |
|---|---|---|
| Headless `e2e:smoke:builder` | ✅ 25/0/1 | Was 10/2/13 before close-gate `a400eb89` fixes. |
| Live MCP re-verify 12 gates | ✅ 12/0/0 | Full breakdown in 1060-MCP-REVERIFY.md. |
| Service URL → Import end-to-end | ✅ Verified | G-01 (WFS) + G-02 (probe) + G-03 (CRS) + G-04 (VEC label) |
| Reupload File multi-layer GPKG | ✅ Verified | G-05 + G-06 |
| Bulk Review Ingest all layers | ✅ Verified | G-07 |
| Basemap sublayer styling round-trip | ✅ Verified | G-08..G-12 |

## Tech Debt

Five items queued for v1014 (see frontmatter). All non-blocking; documented in 1060-SUMMARY.md "Tech-Debt Followups" section.

## Inline Close-Gate Fixes (5 commits — 0 deferrals to v1013.1)

Per A-02 inline-fix posture, all critical issues surfaced during live MCP re-verify were fixed in-milestone:

1. `5b965cfd` — WFS-04 layer 2 (abstract OGC geometry-type normalization in metadata.py)
2. `831b691f` — GPKG-03 fan-out (migration renumber + defer-before-commit race + file-cleanup race)
3. `d24371ed` — BSE-01 load-time apply (BuilderMap + ViewerMap useEffect ordering)
4. `a400eb89` — E2E + duplicate persistence (test contract drift + backend canonicalize helper)
5. `ec5c2ce5` — Plan QA revisions (3 plan files; pre-execute hygiene)

## Definition of Done

All 5 ROADMAP success criteria for Phase 1060 (CTRL-01) satisfied with v1.3.0 substitution per A-01:

1. ✅ 3 named fixtures + 4 gate-created datasets deleted (CLEAN-01)
2. ✅ Smoke gates green: typecheck 0, vitest 2091/2091, e2e:smoke:builder 25/0/1, i18n 2/2
3. ✅ Live MCP re-verify 12/12 PASS (WFS-04, PROBE-05, GPKG-01, GPKG-02, BSE-01 + 7 bonus sub-gates)
4. ✅ Code-review pass: 5 inline fixes; zero v1013.1 deferrals
5. ✅ CHANGELOG `[Unreleased]` → `[1.3.0]` promoted (per A-01 NOT v1.4.0); local tags `v1013` + `v1.3.0` cut

## Recommendation

**PROCEED TO COMPLETE** — run `/gsd:complete-milestone v1013` to archive `.planning/ROADMAP.md` → `.planning/milestones/v1013-ROADMAP.md` and reset planning state for the next milestone.

Tags are local only per A-04. Push via `git push origin v1013 v1.3.0` when ready.
