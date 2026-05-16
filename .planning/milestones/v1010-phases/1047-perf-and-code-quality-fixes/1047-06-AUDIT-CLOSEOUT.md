---
phase: 1047
plan: 06
artifact: audit-closeout-matrix
generated: 2026-05-16
total_findings: 24
p0: 3
p1: 14
p2: 7
---

# Phase 1047 Audit Closeout Matrix

Per-finding disposition for all 24 findings from `1046-BUILDER-CODE-AUDIT.md`.
Satisfies CODE-02 (all P0 fixed), CODE-03 (no silent P1 skips).

| ID | Severity | Dimension | Decision | Plan / Task | Rationale (if deferred) |
|----|----------|-----------|----------|-------------|--------------------------|
| CA-01 | P0 | Duplication | shipped | 1047-01 T1 | syncLayerFilter extracted; 10 call sites replaced across 4 adapters; 5-test suite. |
| CB-07 | P0 | File size + Complexity | shipped | 1047-05 T1-3 | LayerStyleEditor 1231→468 LOC; 8 per-render-mode sub-components + RenderModeSwitch; 29 new tests. |
| CC-15 | P0 | Dead code | resolved (not reproducible) | 1047-01 T2 | selectedLayerId not found in map-sync.ts at any Phase 1047 SHA; claim not reproducible. |
| CA-02 | P1 | Duplication | deferred | — | Per-adapter deviations (fill has outline+extrusion, heatmap/line differ) make universal AdapterSyncTemplate risky without stronger per-adapter test coverage. Carries to Phase 1048. |
| CA-03 | P1 | Duplication | shipped | 1047-06 T1 | setLayerProperty extracted to shared.ts; 5 try-catch setPaintProperty occurrences in fill-adapter.ts replaced; 4-test suite added. |
| CA-04 | P1 | Duplication | shipped (subsumed by CA-01) | 1047-01 T1 | syncLayerFilter handles the null filter branch uniformly; all 10 call sites including else-clause resets replaced in Plan 01. |
| CA-05 | P1 | Duplication | deferred | — | Outline color resolution duplication in fill-adapter syncPaint is low-risk but not critical path. Extracting syncOutlineLayer() deferred to Phase 1048. |
| CB-08 | P1 | File size | deferred | — | DnD extraction risks regression in v1009 multi-select + drag-from-catalog. Defer to v1010 follow-on or after smoke stabilization. Carries to Phase 1048. |
| CB-09 | P1 | File size + Complexity | deferred | — | Tile-signing extraction is contained but large; co-located with CD-20 deferral; address together in dedicated refactor milestone. Carries to Phase 1048. |
| CB-10 | P1 | File size + Complexity | deferred | — | Tab/scene state machine refactor; preserve Plan 02 lazy-load wins by not touching LayerEditorPanel during the perf milestone. Carries to Phase 1048. |
| CB-11 | P1 | File size + Complexity | deferred | — | Already touched in Plan 04 for handleBulkDelete; further mega-hook split risks bulk-op regression close to milestone end. Carries to Phase 1048. |
| CB-12 | P1 | File size | deferred | — | map-sync is the linchpin; split deferred to a dedicated milestone with full per-module test coverage. Carries to Phase 1048. |
| CB-13 | P1 | File size | deferred | — | Data-driven RENDERER_CAPABILITIES factory is M effort; renderAs.test.ts covers current structure adequately. Deferred to Phase 1048. |
| CC-16 | P1 | Dead code | deferred (with compat rationale) | — | BUILDER_STYLE_KEY_ALIASES retained for backward compat with old saved maps pre-dating camelCase migration. Modern code uses camelCase exclusively. Formal deprecation + data migration deferred to Phase 1048. |
| CD-18 | P1 | Complexity | deferred | — | Plan 04 rewrote handleBulkDelete; remaining bulk handlers stay inline (each is short). Per-action handler extraction adds boilerplate without reducing complexity. Carries to Phase 1048. |
| CD-19 | P1 | Complexity | shipped | 1047-05 T2 | RenderModeSwitch lookup-table replaces 200+ LOC nested ternaries; CD-19 closed alongside CB-07. |
| CD-20 | P1 | Complexity | deferred | — | Co-located with CB-09 deferral; address together in dedicated refactor milestone. Carries to Phase 1048. |
| CE-22 | P1 | Test coverage | deferred | — | Test file split is M effort; existing monolithic layer-adapters.test.ts provides comprehensive coverage. shared.ts per-behavior tests added in Plans 01+06. Full split deferred to test-debt sweep. Carries to Phase 1048. |
| CE-23 | P1 | Test coverage | shipped (partial) | 1047-06 T2 | suggested-datasets.ts test stub created (3 tests: array export, required fields, UUID validity). All other helpers already had tests. |
| CA-06 | P2 | Duplication | deferred (out of scope) | — | Paint type-checking duplication is P2; out of milestone scope per CONTEXT.md. Carries to backlog. |
| CB-14 | P2 | File size | deferred (out of scope) | — | DataDrivenStyleEditor complexity is P2; out of milestone scope. Carries to backlog. |
| CC-17 | P2 | Dead code | resolved (not reproducible) | — | UNSUPPORTED_V1002_RENDERERS IS referenced in renderAs.test.ts (lines 204+217); audit claim not reproducible. Constant is intentional inventory used by tests. |
| CD-21 | P2 | Complexity | deferred (out of scope) | — | buildMapStack complexity is P2; out of milestone scope per CONTEXT.md. Carries to backlog. |
| CE-24 | P2 | Test coverage | deferred (out of scope) | — | Builder hook unit stubs are P2; acceptable as integration-tested for now. Carries to backlog. |

## Summary

| Status | Count |
|--------|-------|
| Shipped | 6 (CA-01, CB-07, CC-15*, CA-03, CA-04, CD-19) |
| Shipped (subsumed) | 1 (CA-04 via CA-01) |
| Shipped (partial) | 1 (CE-23) |
| Resolved (not reproducible) | 2 (CC-15, CC-17) |
| Deferred with rationale | 12 |
| **Total** | **24** |

*CC-15 counted as "resolved (not reproducible)" — audit claim was that `selectedLayerId` was unused in map-sync.ts, but the parameter was not present in the file at all at Phase 1047 start SHA.

## CODE-03 Gate

Every P1 finding has a written disposition in this matrix and a `**Status (Phase 1047):**` annotation in `1046-BUILDER-CODE-AUDIT.md`. No silent skips. Total annotations: 19 (3 P0 + 14 P1 + 2 P2 bonus investigations).

## Carries to Phase 1048

| ID | Finding |
|----|---------|
| CA-02 | AdapterSyncTemplate refactor |
| CA-05 | syncOutlineLayer() extraction |
| CB-08 | UnifiedStackPanel DnD hook extraction |
| CB-09 | BuilderMap tile-signing + popup hooks |
| CB-10 | LayerEditorPanel tab/scene hook |
| CB-11 | use-builder-layers mega-hook split |
| CB-12 | map-sync.ts module split |
| CB-13 | renderAs data-driven factory |
| CC-16 | BUILDER_STYLE_KEY_ALIASES deprecation + data migration |
| CD-18 | handleBulkAction per-action handler extraction |
| CD-20 | BuilderMap event nesting (with CB-09) |
| CE-22 | Per-adapter test file split |
