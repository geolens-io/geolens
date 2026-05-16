# Phase 1046 — Plan 02: Builder Perf Baseline

**Phase:** 1046 builder-perf-and-code-audit
**Plan:** 02 of 02
**Requirement:** CODE-01 (the baseline doc is the second half of the audit deliverable)
**Forward-feeds:** PERF-01..06 in Phase 1047
**Status:** Pending
**Owner:** Claude (executor: spawned analyst agent)
**Deliverable:** `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md`

## Goal

Produce a measurable perf baseline document for the Map Builder along the 4 user-confirmed pain axes (large-map render, bulk-op throughput, MapLibre repaint, bundle size). Each baseline metric MUST reference its test map + tooling so Phase 1047 can reproduce the measurement and quantify the win.

## Scope

### In scope (the 4 user-confirmed perf axes)

1. **PERF-01 (Large-map first paint):** First paint for `/maps/:id` with a 50+ layer saved map.
2. **PERF-02 (Input latency at scale):** Hover/click latency on rows in the unified stack on a 50+ layer map.
3. **PERF-03 (Bulk-op throughput):** Wall-clock + request count for bulk-{visibility, opacity, group, ungroup, delete} of N selected layers.
4. **PERF-04 (MapLibre repaint cost):** Frame rate / repaint count during sustained paint-property changes (color picker drag, opacity slider drag, expression editor keystrokes).
5. **PERF-05 (Bundle size / lazy split):** Builder route entry chunk weight + dependency tree; identify code that should be lazy-loaded.
6. **PERF-06 (Smoke runtime baseline):** vitest builder suite runtime, e2e:smoke:builder runtime, cold first build wall-clock (so 1047 can verify no regression).

### Out of scope
- Backend perf (only frontend builder)
- Mobile perf (deferred future milestone)
- Non-builder routes (Search, Dataset detail — separate audits if needed)

## Methodology

### Tooling
- **Static analysis:** `ripgrep` for code patterns, `vite build` output + `vite-bundle-visualizer` (or `rollup-plugin-visualizer` if already wired) for chunk analysis.
- **Runtime measurement:** Chrome DevTools Performance panel (manual capture) + Playwright `page.evaluate` for repeatable timing measurements. Headed mode acceptable; document machine + Chromium version.
- **Bulk-op profiling:** Network panel (XHR/Fetch waterfall) for request count + timing; `performance.mark`/`measure` for client-side wall-clock.
- **Smoke baselines:** `time npm run e2e:smoke:builder`, `time npm run test -- builder`, `time pnpm vite build`.

### Test map (the "50+ layer" reference)

If a representative 50+ layer saved map does not already exist in the dev seed, Plan 02 must:
- Document the seed approach (e.g., script that loops 50 vector layers over a sample dataset, OR a hand-curated saved map JSON).
- Persist the script under `frontend/scripts/seed-large-map.ts` OR `.planning/phases/1046-builder-perf-and-code-audit/scripts/seed-large-map.md` (manual recipe).
- Record the resulting `map.id` so Phase 1047 reproduces against the same fixture.

**Acceptable substitute:** If seeding a real 50+ layer map is too expensive within this phase, document a synthetic in-memory measurement approach (e.g., Playwright that programmatically calls `addLayer` 50 times via the builder's hook API) + note that the runtime numbers are bounded by this synthetic context.

### Repeatability protocol
- Each runtime measurement records: machine (CPU/RAM/OS), browser (Chromium version), test map id, methodology snippet, raw timing (median of N runs, N >= 3), tooling version.
- Static measurements (bundle size, LOC, complexity) reference the git SHA they were captured at.
- Whenever a runtime measurement is impractical in this phase, the doc records that fact and tags the item with `runtime_blocked: true` so Phase 1047 picks up the measurement during fix work.

## Deliverable Structure (`1046-BUILDER-PERF-BASELINE.md`)

```markdown
---
phase: 1046
audit: builder-perf-baseline
status: draft
generated: 2026-05-16
git_sha: <captured>
test_map_id: <id or "synthetic">
machine: { cpu, ram, os }
browser: { chromium_version }
---

# BUILDER-PERF-BASELINE — Map Builder Performance (Phase 1046)

## Methodology

(tooling, repeatability protocol, test map)

## Test Map / Fixture

(description of the 50+ layer fixture; seed script reference; reproduction steps)

## Baseline Metrics

### PERF-01 — Large-map first paint
- **Measurement:** <numbers, e.g., "median first-contentful-paint = X ms over 5 runs">
- **Methodology:** <how it was captured>
- **Status:** measured / runtime_blocked
- **Notes:** <observed bottlenecks or anomalies>

### PERF-02 — Input latency at scale
- (same structure)

### PERF-03 — Bulk-op throughput
- (same structure; document N-layer scenarios e.g. N=10, N=25, N=50)

### PERF-04 — MapLibre repaint cost
- (same structure; document the user gesture that triggers repaints, e.g., color picker drag)

### PERF-05 — Bundle size / lazy split
- **Builder route entry chunk:** <KB before gzip, gzip>
- **Top contributors:** <table of imports by weight>
- **Lazy-load candidates:** <list with rationale: LayerEditorPanel? AddDataModal? Settings scene?>
- **Methodology:** vite build + bundle-visualizer

### PERF-06 — Smoke runtime baseline
- **vitest builder suite:** <wall-clock>
- **e2e:smoke:builder:** <wall-clock>
- **cold first build (pnpm vite build):** <wall-clock>

## Identified Bottlenecks

| ID | Severity | Area | File(s) | Why | Recommended fix | Phase 1047 mapping |
|----|----------|------|---------|-----|-----------------|---------------------|
| PB-01 | P0 | Bundle | path | description | proposal | PERF-05 |
| ... | ... | ... | ... | ... | ... | ... |

## Recommended Targets for Phase 1047

For each PERF-* requirement, propose a measurable target (e.g., "reduce large-map first paint by 30%", "shrink builder route entry chunk by 25%") informed by the baseline. Phase 1047 PLANs lock these targets.

## Closing Notes

(observations, surprises, methodology caveats)
```

## Tasks

1. Spawn `Explore` agent (read-only + bash for build/measurement, very thorough) to:
   - Build the frontend (already-built artifacts OK) and read chunk sizes from `frontend/dist/`
   - If a bundle visualizer isn't already wired, document what command produces chunk sizes (e.g., `pnpm vite build --profile`)
   - Capture vitest builder suite runtime, e2e:smoke:builder runtime, vite build runtime (if smoke can be run; otherwise document "blocked" + reason)
   - Static-analyze top-N largest imports in builder route
   - Identify lazy-load candidates from import graph (panels that aren't on the initial render path)
   - For runtime measurements (PERF-01..04) that require a live stack, EITHER capture them via Playwright/Chrome MCP if available OR mark `runtime_blocked: true` with clear reproduction steps for Phase 1047
   - Write `1046-BUILDER-PERF-BASELINE.md` per the structure above
2. Verify the file:
   - All 6 PERF-* sections present
   - Methodology section names the tools + machine + git SHA
   - Each metric is either measured (with numbers) OR explicitly `runtime_blocked: true` with reason
   - At least one bottleneck identified per PERF axis OR explicit "no bottleneck identified" note
   - Recommended Phase 1047 targets section present
3. Atomic commit: `docs(1046): produce BUILDER-PERF-BASELINE.md`

## Success Criteria (verifiable post-execution)

- [ ] `1046-BUILDER-PERF-BASELINE.md` exists at the deliverable path
- [ ] All 6 PERF-* sections present (PERF-01..06)
- [ ] Methodology + test map + machine + git SHA recorded in frontmatter
- [ ] Bundle size analysis is present (this is the most static-measurable PERF axis — no excuse to skip)
- [ ] Bottlenecks table has at least 5 entries with file/line evidence + recommended fix + Phase 1047 mapping
- [ ] Recommended targets section gives Phase 1047 concrete win criteria

## Non-goals

- No code changes (baseline only)
- No actual perf fixes (deferred to Phase 1047)
- No backend perf measurements
- No mobile perf
