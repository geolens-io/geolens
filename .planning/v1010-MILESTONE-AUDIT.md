---
milestone: v1010
milestone_name: Builder Performance & Code Quality
audited: 2026-05-16T00:00:00Z
status: passed
scores:
  requirements: 17/17
  phases: 3/3
  integration: passed
  flows: passed
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 1046
    items: []
  - phase: 1047
    items:
      - "IN-01: _meta_to_kwargs hard-coded is_dem=None when meta is non-None — Info-level; defer to dedicated DEM polish phase"
      - "IN-02: LayerStyleEditor/utils.ts deepEqual no cycle detection — Info-level; current JSON-only payloads make this academic"
      - "IN-03: bulk-delete response str field vs uuid.UUID — Info-level; cosmetic OpenAPI hint"
      - "UI-REVIEW IN-01: SceneSpinnerFallback aria-label not i18n-keyed — needs locale pass in next builder polish cycle"
      - "UI-REVIEW IN-02: Double Loader2 spinner in BulkActionBar deleting state — minor visual noise"
  - phase: 1048
    items:
      - "IN-01: cursor-not-allowed on container div redundant when children disabled — Info-level cosmetic"
      - "IN-02: FOLLOWUP-01 e2e doesn't assert popup_config clear persisted before reload — Info-level"
      - "IN-03: makeLayer factory omits popup_config field (undefined vs null) — Info-level type hygiene"
nyquist:
  compliant_phases: 0
  partial_phases: 0
  missing_phases: 3
  overall: skipped
  notes: "No VALIDATION.md files for any v1010 phase. Reason: workflow.research=false project-wide; Nyquist validation depends on RESEARCH.md, which is disabled for this project. Phase 1046 audit deliverables + Phase 1047 ROADMAP success-criteria checks + Phase 1048 CLOSE-01 smoke gate fill the same role functionally."
ui_review:
  phase_1047: "21/24 (3 priority polish items absorbed into Phase 1048 Plan 01; 2 info items in tech_debt)"
  phase_1048: "n/a (no UI-SPEC generated — hygiene phase reused 1047 patterns)"
code_review:
  phase_1047: "clean (2 CR + 6 WR fixed; 3 IN deferred to tech_debt)"
  phase_1048: "clean (1 CR + 4 WR fixed; 3 IN deferred to tech_debt)"
---

# v1010 Builder Performance & Code Quality — Milestone Audit

**Audited:** 2026-05-16
**Phases:** 3 (1046 + 1047 + 1048)
**Status:** ✅ Passed — all 17 requirements satisfied

## Definition of Done (from ROADMAP)

v1010's stated goal: *"Improve Map Builder performance under load (large saved maps, bulk-ops, MapLibre repaint, bundle weight) and lock in code-quality wins via an audit-first sweep — while clearing three carried-forward builder follow-ups."*

All four pillars satisfied:
1. **Audit-first sweep:** Phase 1046 produced BUILDER-CODE-AUDIT.md (24 findings) + BUILDER-PERF-BASELINE.md (6 PERF axes + 8 bottlenecks).
2. **Performance wins (measured):** PERF-01..06 all closed with quantified deltas.
3. **Code-quality wins:** CODE-02..06 all closed; CB-07 LayerStyleEditor split 1231 → 468 LOC (-62%); CA-01 + CA-03 helpers extracted; all 14 P1 audit findings shipped or deferred-with-rationale.
4. **Carried-forward follow-ups:** FOLLOWUP-01 popup_config visible-error surface; FOLLOWUP-02 Add Data modal audit (13 findings, 0 P0, v1008 alignment ALIGNED); FOLLOWUP-03 SourcesTab it.todo backlog drained to zero (9 live tests shipped).

Plus CLOSE-01 smoke gate (7/7 PASS including Docker) and CLOSE-02 CHANGELOG `[Unreleased]` populated with measured numbers.

## Phase-Level Verification

| Phase | Goal | Status | Plans | Plans Done | Score |
|-------|------|--------|-------|------------|-------|
| 1046 | Audit deliverables exist | passed | 2 | 2/2 | — |
| 1047 | All P0 + PERF fixes shipped | passed | 6 | 6/6 | 5/5 (upgraded from 4/5 after 1048 closed Docker gates) |
| 1048 | Follow-ups closed + smoke green + CHANGELOG | passed | 4 | 4/4 | 5/5 |

## Requirement Coverage (3-source cross-reference)

| REQ | Phase | Plans claiming | SUMMARY frontmatter | VERIFICATION | Status |
|-----|-------|----------------|---------------------|--------------|--------|
| CODE-01 | 1046 | 1046-01 | listed | passed | satisfied |
| PERF-01 | 1047 | 02, 06 | listed | passed | satisfied |
| PERF-02 | 1047 | 04, 06 | listed | passed | satisfied |
| PERF-03 | 1047 | 04, 06 | listed | passed | satisfied |
| PERF-04 | 1047 | 03, 06 | listed | passed | satisfied |
| PERF-05 | 1047 | 02, 06 | listed | passed | satisfied (PARTIAL on PB-01 target — chunk 233.10 KB above 211 KB stretch target, below 281.76 KB baseline; documented with rationale) |
| PERF-06 | 1047 | 02, 03, 04, 06 | listed | passed | satisfied |
| CODE-02 | 1047 | 01, 05, 06 | listed | passed | satisfied |
| CODE-03 | 1047 | 01, 06 | listed | passed | satisfied |
| CODE-04 | 1047 | 01, 06 | listed | passed | satisfied |
| CODE-05 | 1047 | 05, 06 | listed | passed | satisfied |
| CODE-06 | 1047 | 06 | listed | passed | satisfied |
| FOLLOWUP-01 | 1048 | 01 | listed | passed | satisfied |
| FOLLOWUP-02 | 1048 | 02 | listed | passed | satisfied |
| FOLLOWUP-03 | 1048 | 03 | listed | passed | satisfied |
| CLOSE-01 | 1048 | 04 | listed | passed | satisfied (7/7 smoke gates PASS including Docker) |
| CLOSE-02 | 1048 | 04 | listed | passed | satisfied (CHANGELOG `[Unreleased]` populated) |

**Total:** 17/17 satisfied. Zero orphaned requirements. Zero unsatisfied.

## Cross-Phase Integration

Cross-phase data contracts verified:

| From | To | Contract | Status |
|------|----|----------| -------|
| 1046 BUILDER-CODE-AUDIT.md | 1047 Plan 01 (CA-01) | `hasActiveFilters` helper specified | shipped: `syncLayerFilter` extracted (rename rationale documented) |
| 1046 BUILDER-CODE-AUDIT.md | 1047 Plan 05 (CB-07) | LayerStyleEditor split into per-render-mode children | shipped: 7 sub-editors under LayerStyleEditor/, public import surface preserved |
| 1046 BUILDER-PERF-BASELINE.md | 1047 Plan 02 (PB-01) | Lazy-load top 3 scenes (-40% entry chunk forecast) | shipped: 6 scenes lazy-loaded; -18% measured (PARTIAL — gated by LayerEditorPanel hot-path constraint) |
| 1046 BUILDER-PERF-BASELINE.md | 1047 Plan 03 (PB-02, PB-04, PB-06) | Opacity 100ms + color + filter debounce + rAF coalesce | shipped: `coalesceFrame` utility + integration test |
| 1046 BUILDER-PERF-BASELINE.md | 1047 Plan 04 (PB-03) | Single batched bulk-delete endpoint | shipped: `POST /api/maps/{id}/layers/bulk-delete` (50 sequential → 1 batched, -98% HTTP count) |
| 1047 Plan 04 backend | 1048 Plan 04 CLOSE-01 | Backend pytest test_maps_bulk_layers passes against live DB | shipped: 8/8 PASS |
| 1047 Plan 04 frontend | 1048 Plan 01 (FOLLOWUP-01 UI polish) | BulkActionBar `cursor-not-allowed` + `text-xs` + partial-failure-toast suffix | shipped: 3 UI-REVIEW carry-overs all fixed |
| 1047 Plan 04 backend | 1048 Plan 01 (popup_config 422 surface) | ApiError.body[].loc detection pattern | shipped: `use-builder-save.ts` instanceof ApiError + loc inspection |

End-to-end flows verified:
- Save map with invalid `popup_config` → toast with layer name → fix expression → save succeeds (Phase 1048 e2e test in `e2e/builder.spec.ts`)
- Bulk-delete N selected layers → 1 batched HTTP call → success/partial-failure/full-rollback toast (Phase 1047 Plan 04 + Phase 1048 closeout)
- Open large saved map → 5 editor scenes lazy-load on demand (Phase 1047 Plan 02 + e2e:smoke:builder)
- Drag opacity slider → 1 MapLibre repaint per animation frame (Phase 1047 Plan 03 rAF unit test)

## CLOSE-01 Smoke Gate Evidence

From `.planning/phases/1048-followups-and-closeout/1048-04-CLOSE-EVIDENCE.md`:

| Gate | Command | Verdict |
|------|---------|---------|
| 1 | `cd frontend && npm run typecheck` | PASS (0 production errors; 4 pre-existing TS6133 in test files only) |
| 2 | `cd frontend && npm test -- --run` | PASS (1887/1887 tests, +12 from 1875 baseline) |
| 3 | `cd frontend && npm run e2e:smoke:builder` | PASS (26/26 including FOLLOWUP-01 round-trip) |
| 4 | `E2E_BACKEND_AVAILABLE=1 cd frontend && npm run e2e:smoke:perf` | PASS (PERF-02 hover p50=4.9ms vs ≤30ms target — 6× margin) |
| 5 | `cd backend && uv run pytest tests/test_maps_bulk_layers.py -x` | PASS (8/8) |
| 6 | `cd backend && uv run ruff check app/modules/catalog/maps/` | PASS (0 errors) |
| 7 | `cd frontend && npm run check:i18n` | PASS (en/de/es/fr parity at 781 keys) |

## Tech Debt

Aggregate 11 Info-level items captured in frontmatter `tech_debt` section above. None are blockers; all are deferred-with-rationale. Suggested home: a future builder polish cycle if/when these items cluster naturally with related work.

## Nyquist Compliance

`workflow.research=false` project-wide → no RESEARCH.md → no VALIDATION.md for v1010 phases. Functional equivalents:
- Phase 1046 served as the validation strategy (audit-first sequencing produced the measurable baseline targets used by Phase 1047).
- Phase 1047 ROADMAP success criteria provided per-PERF target gates with concrete numbers.
- Phase 1048 CLOSE-01 7-gate smoke matrix served as the final compliance check.

Audit verdict: equivalent coverage achieved without VALIDATION.md scaffolding. No action needed.

## Audit Verdict

**v1010 — PASSED.** Ready for `/gsd-complete-milestone`.

Deliverables landed:
- 6/6 PERF requirements with quantified before/after (PERF-02 p50=4.9ms, PERF-03 -98% HTTP, PERF-05 -18% entry chunk, etc.)
- 5/5 CODE quality requirements (CB-07 -62% LOC, CA-01 + CA-03 helpers extracted, 24-finding audit closeout matrix)
- 3/3 FOLLOWUPs closed (popup_config error surface, Add Data modal audit, SourcesTab test backlog drained)
- 2/2 CLOSE requirements (7-gate smoke green, CHANGELOG `[Unreleased]` populated)
- 11 Info-level deferrals tracked as tech debt
- Audit deliverables shipped under `.planning/phases/` for future-milestone reference

No blockers. No unsatisfied requirements. Cross-phase wiring verified end-to-end.
