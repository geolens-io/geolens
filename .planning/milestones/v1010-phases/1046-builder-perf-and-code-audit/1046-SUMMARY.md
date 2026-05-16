---
phase: 1046
phase_name: builder-perf-and-code-audit
status: complete
shipped: 2026-05-16
plans_total: 2
plans_complete: 2
requirements_satisfied: [CODE-01]
commits: [63eddbb5, b8d2abe5, 482c4258, 7f8551bf]
deliverables:
  - 1046-BUILDER-CODE-AUDIT.md
  - 1046-BUILDER-PERF-BASELINE.md
---

# Phase 1046 — Summary

**builder-perf-and-code-audit** — shipped 2026-05-16 (single session, autonomous --only mode).

## Deliverables

### `1046-BUILDER-CODE-AUDIT.md` (35.9 KB, 556 lines)
- **24 findings** classified P0 (3) / P1 (14) / P2 (7)
- **5 audit dimensions** covered: Duplication (6), File-size (8), Dead Code (3), Complexity (5), Test Coverage (2)
- **Scope:** 71 files (41,758 LOC) across `components/builder/`, builder/hooks/, and adjacent lib helpers (`basemap-utils.ts`, `normalize-saved-map.ts`, `normalize-style-config.ts`, `popup-template.ts`, `layer-capabilities.ts`, `MapBuilderPage.tsx`)
- Every finding has: ID, dimension, severity, file:line, why, recommended fix, est. effort, Phase 1047 requirement mapping
- Top P0 findings forward-fed to Phase 1047 CODE-02:
  - **CA-01** — filter-checking duplication across 5 layer adapters (10+ sites; extract `hasActiveFilters(layer)` utility, ~30min)
  - **CB-01** — LayerStyleEditor.tsx oversized (1204 LOC + high complexity; split per-render-mode, M effort)
  - **CC-15** — unused `selectedLayerId` parameter in map-sync (trivial removal, <1h)

### `1046-BUILDER-PERF-BASELINE.md` (26.7 KB, 466 lines)
- **All 6 PERF axes** (PERF-01..06) documented
- **Measured statically:**
  - PERF-05 — builder route entry chunk: **281.76 KB / 64.35 KB gzip** (8% larger than other routes)
  - PERF-06 — vitest full suite **35.28s**, builder subset **9.5s**; cold vite build 1.2–1.5s estimated; e2e:smoke:builder env-blocked
- **Runtime-blocked (with documented reproduction):** PERF-01 (large-map first paint), PERF-02 (input latency at 50 layers), PERF-03 (bulk-op throughput), PERF-04 (MapLibre repaint cost). Each carries exact Playwright + Chrome DevTools steps for Phase 1047 to drive against a seeded test map.
- **8 bottlenecks** identified (PB-01..PB-08) with file/line evidence + Phase 1047 mapping:
  - **PB-01 (P0, Bundle, PERF-05):** 5 editor scenes synchronously imported in MapBuilderPage (DEMEditorScene + SettingsEditorScene + 2 basemap editors + StyleJsonDialog). Lazy-loading the top 3 (SettingsEditorScene 28 KB + DEMEditorScene 22 KB + basemap editors 33 KB) is forecast to save 83 KB (~30% of entry chunk); all 5 lazy-loaded forecasts ~40% reduction.
  - **PB-02 (P1, Repaint, PERF-04):** Opacity slider has no debounce; fires onChange per pixel of drag → 50+ repaints/sec instead of ~10/sec. Adding 100ms debounce forecast 70% frame rate improvement.
  - **PB-03 (P1, Bulk-ops, PERF-03):** Bulk-delete uses `Promise.allSettled()` over 50 sequential HTTP requests; should be 1 batched endpoint OR a tighter client-side request budget. Forecast 70% throughput gain.

## What Shipped

- **Plans:** 2 (PLAN-01 + PLAN-02 written before execution, committed at `b8d2abe5`)
- **Deliverable docs:** 2 (CODE-AUDIT + PERF-BASELINE, committed atomically at `482c4258` + `7f8551bf`)
- **Source code touched:** None — this is an audit phase by design
- **Commits in scope:** 4
  - `63eddbb5` — auto-generated CONTEXT.md
  - `b8d2abe5` — Plan 01 + Plan 02
  - `482c4258` — BUILDER-CODE-AUDIT.md
  - `7f8551bf` — BUILDER-PERF-BASELINE.md

## What Didn't Ship (and Why)

- **No code changes** — Phase 1046 is audit-only by definition. Phase 1047 implements fixes.
- **No runtime perf measurements for PERF-01..04** — would require a live Docker stack + a seeded 50+ layer test map. Plan 02 explicitly accepts `runtime_blocked: true` for this; Phase 1047 will seed the map and capture timings during fix work (more efficient than measuring twice).
- **No backend audit** — out of scope (frontend builder only).
- **No mobile audit** — deferred to a future milestone (per REQUIREMENTS.md "Future Requirements" section).
- **No `--research` exploration** — research disabled per project config (`workflow.research=false`); the codebase-as-source audit substitutes for external stack research.

## Forward Hand-off to Phase 1047

Phase 1047 plan authors should:
1. **Read both audit docs first** — they are the fix backlog.
2. **Group fixes by file overlap** for wave-based execution (audit findings cluster: layer adapters, LayerEditorPanel area, use-builder-layers hook).
3. **Seed the 50+ layer test map early** — both for runtime perf measurement AND for the bulk-op throughput PERF-03 / repaint cost PERF-04 verification.
4. **Lock per-PERF win targets** from the baseline's "Recommended Targets for Phase 1047" section before writing plans.
5. **Order P0s first:** PB-01 (lazy-load — likely 1 day) → CA-01 (filter utility — 30min) → CC-15 (param cleanup — <1h) → CB-01 (LayerStyleEditor split — biggest single CODE refactor).

## Operational Notes

- **Audit reproducibility:** Both docs are diffable against future audits. Git SHA `b8d2abe5` frozen in PERF-BASELINE frontmatter.
- **Memory check:** No findings overlap with the recent stable fixes documented in MEMORY (e.g., 260516-9g9 Path R applyMasterOpacity is intentionally not flagged as code-quality issue).
- **Test debt forwarding:** Audit dimension E (test coverage) flagged `it.todo` items across builder tests — these feed FOLLOWUP-03 in Phase 1048 (SourcesTab + others).

## Status

**Phase 1046:** ✅ Complete. Per `--only 1046` autonomous mode: workflow exits cleanly; lifecycle (audit-milestone, complete, cleanup) skipped. Phase 1047 + 1048 deferred to fresh `/clear`-ed sessions.
