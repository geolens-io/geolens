---
phase: 1047-perf-and-code-quality-fixes
plan: 06
type: execute
wave: 6
depends_on: [1047-02, 1047-03, 1047-04, 1047-05]
files_modified:
  - frontend/src/components/builder/layer-adapters/shared.ts
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/layer-adapters/circle-adapter.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/hillshade-adapter.ts
  - frontend/src/components/builder/layer-adapters/raster-adapter.ts
  - .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
  - .planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md
  - .planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md
autonomous: false
requirements: [CODE-02, CODE-03, CODE-04, CODE-05, CODE-06, PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, PERF-06]
must_haves:
  truths:
    - "All P0 audit findings (CA-01, CB-07, CC-15) have a written disposition in BUILDER-CODE-AUDIT.md — `**Status (Phase 1047):** shipped` or `resolved — claim not reproducible`"
    - "Every P1 audit finding (CA-02..CA-05, CB-08..CB-13, CC-16, CD-18..CD-20, CE-22..CE-23) has a `**Status (Phase 1047):**` annotation: `shipped` with commit ref OR `deferred — <one-line rationale>` (no silent skips per CODE-03)"
    - "CA-03 setLayerProperty helper extracted to shared.ts; try-catch wrapped setPaintProperty pattern eliminated from 6 adapters (7+ occurrences collapsed)"
    - "CA-02 + CA-04 + CA-05 duplication remediation: assess each, ship if low-risk, document deferral with rationale otherwise"
    - "CODE-04 dead-code re-verification: rg confirms CC-15, CC-16, CC-17 candidates are either removed OR annotated; no new dead code introduced this phase"
    - "CODE-05 file-size verification: LayerStyleEditor.tsx ≤ 500 (post-Plan 05); other large files (UnifiedStackPanel 1037, BuilderMap 906, LayerEditorPanel 824, use-builder-layers 1020, map-sync 718, renderAs 595) each have a disposition (shipped split OR deferred-with-rationale)"
    - "1047-06-PERF-BEFORE-AFTER.md table captures measured-after values for PERF-01..06, mirroring BUILDER-PERF-BASELINE.md Recommended Targets, with deltas"
    - "Final gate (single human checkpoint): smoke runs green — vitest builder suite, typecheck, builder Playwright smoke, i18n parity"
  artifacts:
    - path: ".planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md"
      provides: "Per-finding disposition matrix (24 findings × {shipped, deferred, n/a})"
    - path: ".planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md"
      provides: "PERF-01..06 before/after metric table with deltas"
    - path: "frontend/src/components/builder/layer-adapters/shared.ts"
      provides: "setLayerProperty helper (CA-03 extraction)"
      contains: "export function setLayerProperty"
  key_links:
    - from: ".planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md"
      to: "Per-finding `**Status (Phase 1047):**` annotations"
      via: "inline edits under each finding"
      pattern: "Status \\(Phase 1047\\)"
---

<objective>
Close out Phase 1047:
1. **CA-03 sweep** (cheap P1 duplication that pairs naturally with CA-01 from Plan 01): extract `setLayerProperty(map, layerId, property, value, kind)` helper, eliminate the 7+ try-catch wrapped setPaintProperty occurrences across 6 adapters.
2. **CA-02 / CA-04 / CA-05** assessment + ship-or-defer: review each P1 duplication finding, ship if marginal cost is low, otherwise annotate the audit doc with a `**Status (Phase 1047):** deferred — <rationale>` line.
3. **Other P1 file-size + complexity findings** (CB-08..CB-13, CC-16, CD-18..CD-20, CE-22..CE-23): per-finding decision. Most were NOT scoped to Plans 02-05 — this plan either ships the small ones or documents deferral. Default to defer (per CONTEXT.md "P1 defer-vs-fix is per-finding") unless effort is < 30 min.
4. **CODE-04 dead-code re-verification**: grep audited dirs for the three CC-XX dead-code findings + any new dead code introduced this phase.
5. **CODE-05 file-size verification**: every file flagged in Phase 1046 either drops below threshold or carries an accepted-with-rationale annotation.
6. **CODE-06 + PERF-06 final gates** (the only checkpoint in this plan): typecheck + vitest builder + builder Playwright smoke + i18n parity all green; runtimes within budget. Single human checkpoint for sign-off.
7. **Per-PERF before/after capture**: produce `1047-06-PERF-BEFORE-AFTER.md` with measured after-values mirroring BUILDER-PERF-BASELINE.md Recommended Targets.

Purpose: This is the audit-closeout. Without this plan, P1 findings sit silently un-disposed, violating CODE-03 (no silent skips). The final smoke gate proves no regression.

Output: shared setLayerProperty helper; per-finding annotations in BUILDER-CODE-AUDIT.md; audit closeout matrix; perf before/after table; final smoke green.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-01-SUMMARY.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-02-SUMMARY.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-03-SUMMARY.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-04-SUMMARY.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-05-SUMMARY.md

<interfaces>
<!-- CA-03 try-catch wrapped setPaintProperty pattern — appears 7+ times -->
<!-- Existing locations (audit CA-03 lines 168-174): -->
- fill-adapter.ts:137-150, 154-157, 180-182
- line-adapter.ts:103-112
- hillshade-adapter.ts:47-62

<!-- After Plan 01 Task 1, shared.ts already has syncLayerFilter. setLayerProperty sits beside it. -->

<!-- Files flagged by CODE-05 (file-size offenders): -->
- LayerStyleEditor.tsx (1204 → ≤ 500 by Plan 05) — shipped
- UnifiedStackPanel.tsx (1037) — not split this phase, CONTEXT.md says default-defer P1
- BuilderMap.tsx (906) — not split this phase
- LayerEditorPanel.tsx (824) — not split this phase
- use-builder-layers.ts (1020) — partially touched by Plan 04 (handleBulkDelete rewrite) but not split
- map-sync.ts (718) — not split this phase
- renderAs.ts (595) — not split this phase

<!-- Each non-shipped file-size offender gets a one-line **Status (Phase 1047):** deferred — <rationale> annotation -->
<!-- Default rationale template: "Touches X concerns and Y callers; full split is M effort; deferred to v1010 closeout (Phase 1048) or later milestone." -->

<!-- 24 findings total in BUILDER-CODE-AUDIT.md: P0=3, P1=14, P2=7 -->
<!-- P2 findings are out of scope per CONTEXT.md "Deferred Ideas" -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Extract setLayerProperty helper + refactor adapters (CA-03)</name>
  <files>
    frontend/src/components/builder/layer-adapters/shared.ts,
    frontend/src/components/builder/layer-adapters/fill-adapter.ts,
    frontend/src/components/builder/layer-adapters/line-adapter.ts,
    frontend/src/components/builder/layer-adapters/hillshade-adapter.ts,
    frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts
  </files>
  <read_first>
    frontend/src/components/builder/layer-adapters/shared.ts (post-Plan 01 — has syncLayerFilter at the bottom),
    frontend/src/components/builder/layer-adapters/fill-adapter.ts (lines 137-182 for the try-catch wrapped setPaintProperty occurrences),
    frontend/src/components/builder/layer-adapters/line-adapter.ts (lines 103-112),
    frontend/src/components/builder/layer-adapters/hillshade-adapter.ts (lines 47-62),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md (CA-03 detail at lines 165-205)
  </read_first>
  <behavior>
    - Test 1: `setLayerProperty(map, 'L', 'fill-color', '#ff0000')` calls `map.setPaintProperty('L', 'fill-color', '#ff0000')` exactly once
    - Test 2: `setLayerProperty(map, 'L', 'visibility', 'visible', 'layout')` calls `map.setLayoutProperty('L', 'visibility', 'visible')` — the optional kind param toggles paint vs layout
    - Test 3: When `map.setPaintProperty` throws, the helper catches and (in DEV mode) emits `console.debug` with the failed property/layer; does NOT re-throw
    - Test 4: Default `kind` is `'paint'` (omitting the 5th arg routes to setPaintProperty)
  </behavior>
  <action>
    Add `export function setLayerProperty(map: MaplibreMap, layerId: string, property: string, value: unknown, kind: 'paint' | 'layout' = 'paint'): void` to `frontend/src/components/builder/layer-adapters/shared.ts`. Body matches audit CA-03 recommendation:
    ```
    try {
      if (kind === 'paint') map.setPaintProperty(layerId, property, value);
      else map.setLayoutProperty(layerId, property, value);
    } catch (e) {
      if (import.meta.env.DEV) console.debug(`[map-sync] Failed to set ${kind} property ${property} on ${layerId}:`, e);
    }
    ```

    Replace every audit-identified try-catch wrapped setPaintProperty in fill-adapter.ts (lines 137-150, 154-157, 180-182), line-adapter.ts (lines 103-112), and hillshade-adapter.ts (lines 47-62) with a single `setLayerProperty(map, id, prop, value)` call. Preserve the property names and values.

    Extend `frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts` (created in Plan 01) with the 4 behavior tests above. Use the same mock-map helper.

    CA-03 mapping: per audit, this is CODE-03 duplication remediation. Ship for the same reason as CA-01.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/layer-adapters/__tests__/shared.test.ts</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/layer-adapters</automated>
    <automated>cd frontend && rg -nU "try \\{[^}]*map\\.setPaintProperty[^}]*\\} catch" src/components/builder/layer-adapters/ | grep -v shared.ts | wc -l | grep -E '^0$'</automated>
    <automated>cd frontend && grep -c "setLayerProperty(" src/components/builder/layer-adapters/fill-adapter.ts src/components/builder/layer-adapters/line-adapter.ts src/components/builder/layer-adapters/hillshade-adapter.ts | grep -v ':0'</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `setLayerProperty` exported from shared.ts with 4 contract tests
    - Zero remaining `try { map.setPaintProperty } catch` blocks outside `shared.ts` in the adapter directory
    - 6 adapter files import + use setLayerProperty
    - All existing layer-adapter tests still pass
    - Typecheck clean
  </acceptance_criteria>
  <done>CA-03 closed; duplicate try-catch pattern eliminated.</done>
</task>

<task type="auto">
  <name>Task 2: Per-P1-finding sweep — ship or annotate, then update BUILDER-CODE-AUDIT.md</name>
  <files>
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md,
    .planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md,
    frontend/src/components/builder/layer-adapters/fill-adapter.ts,
    frontend/src/components/builder/layer-adapters/heatmap-adapter.ts,
    frontend/src/components/builder/layer-adapters/circle-adapter.ts
  </files>
  <read_first>
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md (read all 24 findings),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-01-SUMMARY.md (which CA findings already shipped),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-05-SUMMARY.md (which CB findings already shipped),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md (P1 defer-vs-fix policy: default to fix; defer only if (a) effort exceeds budget OR (b) higher-risk regression surface)
  </read_first>
  <action>
    Walk each P1 finding in BUILDER-CODE-AUDIT.md. For each, decide: SHIP or DEFER. Append a one-line annotation under the finding in the audit doc. Use this template:
    - SHIPPED: `**Status (Phase 1047):** shipped — see Plan {NN} Task {N} ({brief}).`
    - DEFERRED: `**Status (Phase 1047):** deferred — {one-line rationale}. Carries to {Phase 1048 closeout | next milestone}.`

    Specifics for each P1:

    | Finding | Decision template | Notes |
    |---------|------------------|-------|
    | CA-02 (identical syncPaint structure) | DEFER unless 30 min fit | Audit recommends an "AdapterSyncTemplate" — but each adapter has slight deviations (fill has outline + extrusion, heatmap has different opacity props). Templating risks regression. RECOMMENDED: defer with rationale "Per-adapter deviations make a universal template risky; revisit after v1010 closeout when test coverage per-adapter is stronger." |
    | CA-03 (try-catch setPaintProperty) | SHIPPED (Task 1 of this plan) | Reference Plan 06 Task 1 |
    | CA-04 (filter-setting else-clause) | SHIPPED-AS-PART-OF-CA-01 | CA-01 fix (Plan 01) subsumed this; annotate "subsumed by CA-01 — syncLayerFilter handles the null branch uniformly" |
    | CA-05 (outline compound opacity) | SHIP or DEFER based on effort | Extract `syncOutlineLayer()` helper inside fill-adapter.ts (per audit recommendation) — confined to fill-adapter, < 1 hour, ship. Otherwise defer with rationale. |
    | CB-08 (UnifiedStackPanel 1037 LOC) | DEFER | DnD extraction is M effort, touches drag/drop state machine. Rationale: "DnD extraction risks regression in v1009 multi-select + drag-from-catalog; defer to v1010 follow-on or after smoke stabilization." |
    | CB-09 (BuilderMap 906 LOC) | DEFER | Similar M effort, touches tile-signing + popup. Rationale: "Tile-signing extraction is contained-but-large; defer to dedicated refactor." |
    | CB-10 (LayerEditorPanel 824 LOC) | DEFER | Rationale: "Tab/scene state machine refactor; preserve Plan 02 lazy-load wins by not touching this file during the perf milestone." |
    | CB-11 (use-builder-layers 1020 LOC) | DEFER | Rationale: "Already touched in Plan 04 for handleBulkDelete; further mega-hook split risks bulk-op regression close to milestone end." |
    | CB-12 (map-sync 718 LOC) | DEFER | Rationale: "map-sync is the linchpin; split deferred to a dedicated milestone with full per-module test coverage." |
    | CB-13 (renderAs 595 LOC) | SHIP IF 30 MIN FITS | Audit recommends data-driven RENDERER_CAPABILITIES; if a quick factory pattern is feasible, ship. Else defer with rationale. |
    | CC-16 (snake_case aliases) | INVESTIGATE then ship-or-defer | Run `rg "snake_case|fill_disabled|stroke_disabled"` across audited dirs. If zero modern usage found, remove the alias map. Else add deprecation comment + defer. |
    | CD-18 (handleBulkAction nesting) | DEFER unless cheap | The bulk-delete path was rewritten in Plan 04; the OTHER bulk paths (visibility, opacity, group, ungroup) still use the inline switch. Rationale: "Plan 04 rewrote handleBulkDelete; remaining bulk handlers stay inline because each is short and per-action handler extraction would add boilerplate without reducing complexity." |
    | CD-19 (LayerStyleEditor nested ternaries) | SHIPPED (Plan 05) | Reference Plan 05 RenderModeSwitch |
    | CD-20 (BuilderMap event nesting) | DEFER | Rationale: "Co-located with CB-09 deferral; address together in dedicated refactor." |
    | CE-22 (monolithic layer-adapters.test.ts) | DEFER unless cheap | Rationale: "Test file split is M effort; defer to test-debt sweep. Existing coverage is high." |
    | CE-23 (partial helper coverage) | INVESTIGATE + spot-fix | Run `find frontend/src/components/builder -name "suggested-datasets*"` — if a test file is missing for `suggested-datasets.ts`, write a minimal 3-test stub. < 30 min. Else annotate "already covered". |

    For any P1 finding shipped during Task 2 (CA-05, CB-13, CC-16, CE-23 — depending on outcomes), update the file(s) directly and link the commit/file in the audit annotation.

    Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md` — a flat matrix:

    | ID | Severity | Decision | Plan | Rationale (if deferred) |
    |----|----------|----------|------|--------------------------|
    | CA-01 | P0 | shipped | 1047-01 T1 | — |
    | CA-02 | P1 | deferred | — | Per-adapter deviations risk regression |
    | CA-03 | P1 | shipped | 1047-06 T1 | — |
    | ... | ... | ... | ... | ... |

    Cover all 24 findings (P0 + P1 + P2; P2 default to "deferred — out of milestone scope per CONTEXT.md"). This matrix becomes the audit-trail artifact for CODE-02 / CODE-03.

    **Important**: do NOT silently skip P1 findings. Every one of CA-02..CE-23 (14 P1s) MUST have a `Status (Phase 1047)` line in the audit doc OR an entry in the closeout matrix. CODE-03 is the gate.
  </action>
  <verify>
    <automated>grep -c "Status (Phase 1047)" .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md | awk '$1 >= 17 {print "OK: " $1 " annotations (3 P0 + 14 P1 = 17 min)"; exit 0} {print "FAIL: " $1 " annotations; need >= 17"; exit 1}'</automated>
    <automated>test -f .planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md</automated>
    <automated>grep -cE "^\\| C[A-E]-[0-9]+ " .planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md | awk '$1 >= 24 {print "OK: " $1 " findings in matrix"; exit 0} {print "FAIL: " $1 " findings; need 24"; exit 1}'</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/layer-adapters 2>&1 | tail -5</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - Every P0 (3) and P1 (14) finding has a `**Status (Phase 1047):**` annotation in BUILDER-CODE-AUDIT.md (≥ 17 grep matches)
    - `1047-06-AUDIT-CLOSEOUT.md` matrix covers all 24 findings
    - Any P1 shipped during this task has corresponding code change + unchanged tests pass
    - CODE-03 satisfied: no silent skips — every finding has a written disposition
    - Typecheck clean
  </acceptance_criteria>
  <done>Every audit finding has a written disposition; closeout matrix exists.</done>
</task>

<task type="auto">
  <name>Task 3: CODE-04 dead-code re-grep + CODE-05 file-size verification + PERF-06 runtime check</name>
  <files>
    .planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md
  </files>
  <read_first>
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md (Recommended Targets for Phase 1047 — table at the end),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md (PERF-05 measurements from Plan 02),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-02-SUMMARY.md,
    .planning/phases/1047-perf-and-code-quality-fixes/1047-03-SUMMARY.md (rAF coalescing — PERF-04),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-04-SUMMARY.md (bulk-delete throughput + input latency — PERF-02 + PERF-03)
  </read_first>
  <action>
    **CODE-04 dead-code re-verification** — run these greps and record results:
    - `rg -n "selectedLayerId" frontend/src/components/builder/map-sync.ts` (CC-15) — expect 0
    - `rg -n "BUILDER_STYLE_KEY_ALIASES|snake_case|fill_disabled|stroke_disabled" frontend/src/components/builder/layer-adapters/shared.ts` (CC-16) — expect either 0 (if removed in Task 2) or matches + deprecation comment
    - `rg -n "UNSUPPORTED_V1002_RENDERERS" frontend/src/components/builder/` (CC-17 P2) — expect 0 if removed; else accepted deferral
    - `rg -n "TODO|FIXME|XXX" frontend/src/components/builder/layer-adapters/ frontend/src/components/builder/hooks/` — count, ensure not increased vs Phase 1046 baseline

    **CODE-05 file-size verification** — `wc -l frontend/src/components/builder/{LayerStyleEditor.tsx,UnifiedStackPanel.tsx,BuilderMap.tsx,LayerEditorPanel.tsx,hooks/use-builder-layers.ts,map-sync.ts,renderAs.ts}` — capture current LOC for each. Compare to Phase 1046 baseline. LayerStyleEditor must be ≤ 500 (per Plan 05). All others either shrank or are explicitly accepted in the closeout matrix.

    **PERF-06 runtime check** — measure and record:
    - `cd frontend && time npm run test 2>&1 | tail -3` — full vitest wall-clock; budget ≤ 35s test execution + ≤ 75s total (per BUILDER-PERF-BASELINE.md)
    - `cd frontend && rm -rf dist node_modules/.vite && time npm run build 2>&1 | tail -10` — cold first build; budget ≤ 1.7s
    - `cd frontend && time npm run build 2>&1 | tail -5` — incremental build; budget ≤ 500ms (was 386ms baseline; allow ~30% buffer)

    Write `.planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md` with the canonical Phase 1047 perf table — mirrors BUILDER-PERF-BASELINE.md "Recommended Targets" structure:

    ```
    | PERF | Metric | Baseline (Phase 1046) | Target | Measured After | Delta | Status |
    |------|--------|------------------------|--------|-----------------|-------|--------|
    | PERF-01 | 50-layer FCP (p50) | 2.0-3.5s (est) | ≤ 2.6s | <fill from e2e/perf spec> | -X% | PASS/PARTIAL/DEFER |
    | PERF-02 | Input latency (p50) | 50-100ms (est) | ≤ 30ms | <fill from Plan 04 Task 3 Playwright> | -X% | ... |
    | PERF-03 | Bulk-delete N=50 wall-clock | 2-3s (50 HTTP) | ≤ 600ms | <fill from Plan 04 Task 3> | -X% | ... |
    | PERF-03 | Bulk-delete HTTP req count | 50 | 1 | 1 (Plan 04 Task 1 endpoint) | -98% | PASS |
    | PERF-04 | Paint repaints/sec during drag | 60+ | ≤ 20 | <fill from manual measurement OR Plan 03 unit test> | ... | PASS (unit-level) |
    | PERF-05 | MapBuilderPage entry chunk | 281.76 KB | ≤ 170 KB (target) / ≤ 211 KB (min) | <fill from 1047-02-CHUNK-SIZES.md> | -X% | PASS/PARTIAL |
    | PERF-06 | vitest builder wall-clock | 9.5s | ≤ 10.5s | <measured> | <delta> | PASS |
    | PERF-06 | cold first build | 1.2-1.5s | ≤ 1.7s | <measured> | <delta> | PASS |
    ```

    For PERF-01, PERF-02, PERF-03 wall-clock metrics that require Docker stack (e2e/perf spec from Plans 01+04): if Docker is unavailable in this execution context, mark "Measured by user during final smoke (handoff)" — Phase 1048 closeout will capture them. Phase 1047 is satisfied if the IMPLEMENTATION is in place + the TEST/ASSERTION is wired, even if the live measurement happens at handoff.

    Include in the doc: git SHA at measurement, machine specs (M2 Pro, 16GB, macOS 14.x), test fixtures used (50-layer map ID), exact commands run.
  </action>
  <verify>
    <automated>cd frontend && rg -n "selectedLayerId" src/components/builder/map-sync.ts | wc -l | grep -E '^0$'</automated>
    <automated>cd frontend && wc -l src/components/builder/LayerStyleEditor.tsx | awk '$1 <= 500 {print "OK"; exit 0} {print "FAIL: " $1 " > 500"; exit 1}'</automated>
    <automated>test -f .planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md</automated>
    <automated>cd frontend && time npm run test 2>&1 | tee /tmp/1047-06-vitest.log | tail -5</automated>
    <automated>cd frontend && time npm run build 2>&1 | tee /tmp/1047-06-build.log | tail -5</automated>
    <automated>grep -E "PERF-0[1-6]" .planning/phases/1047-perf-and-code-quality-fixes/1047-06-PERF-BEFORE-AFTER.md | wc -l | awk '$1 >= 6 {print "OK"; exit 0} {print "FAIL: only " $1 " PERF rows"; exit 1}'</automated>
  </verify>
  <acceptance_criteria>
    - CODE-04: 3 dead-code candidates re-greped; CC-15 confirmed 0; CC-16/CC-17 have a disposition
    - CODE-05: 7 file-size offenders each have a current LOC measurement vs Phase 1046 baseline; LayerStyleEditor ≤ 500
    - PERF-06: vitest ≤ 10.5s, cold build ≤ 1.7s (or documented deviation)
    - `1047-06-PERF-BEFORE-AFTER.md` exists with all 6 PERF rows; either measured-after values OR an explicit "handoff" marker
  </acceptance_criteria>
  <done>Audit re-verification complete; perf table captured; runtime gates green.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 4: Final smoke gate (CODE-06 + PERF-06 cross-cutting)</name>
  <what-built>
    Phase 1047 complete:
    - All 6 PERF requirements implemented (PERF-01 via Plan 02 lazy-load; PERF-02 via Plan 04 memoization; PERF-03 via Plan 04 batched endpoint; PERF-04 via Plan 03 rAF coalescing + debounce; PERF-05 via Plan 02 chunk reduction; PERF-06 via runtime budget gates this plan).
    - All 3 P0 audit findings disposed (CA-01 shipped Plan 01; CB-07 shipped Plan 05; CC-15 verified Plan 01 Task 2).
    - All 14 P1 audit findings annotated (Task 2 of this plan).
    - Single milestone exception documented: POST /api/maps/{id}/layers/bulk-delete backend endpoint.
  </what-built>
  <how-to-verify>
    Run the full smoke gate. Each command should succeed. Paste outputs into the resume signal.

    1. **Typecheck**: `cd frontend && npm run typecheck` — expect 0 errors
    2. **Vitest builder**: `cd frontend && npm run test -- --run src/components/builder src/hooks/__tests__ src/lib/builder` — expect green; total time ≤ 35s (PERF-06)
    3. **Vitest full**: `cd frontend && time npm run test` — expect green; budget ≤ 75s total per Phase 1046 baseline
    4. **i18n parity**: `cd frontend && npm run test:i18n` — expect green (770-key parity across en/de/es/fr; Plan 04 added 5 keys × 4 locales = 20 new strings)
    5. **Builder Playwright smoke** (REQUIRES Docker stack):
       - Bring up stack: `docker compose up -d --build`
       - Wait for backend ready: `curl -sf http://localhost:8080/api/health` returns 200
       - Run: `cd frontend && npm run e2e:smoke:builder` — expect green; budget ≤ 50s wall-clock
    6. **Perf smoke (NEW from Plan 01 + 04)**: `cd frontend && npm run e2e:smoke:perf` — runs the 50-layer perf assertions; if green, capture measurements and back-fill `1047-06-PERF-BEFORE-AFTER.md` rows still marked "handoff"
    7. **Backend tests**: `cd backend && uv run pytest tests/test_maps_bulk_layers.py -x` — expect green (Plan 04 new tests)
    8. **Backend lint**: `cd backend && uv run ruff check app/modules/catalog/maps/` — expect 0 violations
    9. **Final sanity check**: `cd frontend && npm run build` — expect green; cold build ≤ 1.7s
    10. **Audit closeout sanity**: `grep -c "Status (Phase 1047)" .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md` — expect ≥ 17 (all P0 + P1)

    If any step fails, fix in-line (small) OR open a followup with rationale (larger). Don't tag the milestone with a red gate.
  </how-to-verify>
  <resume-signal>
    Paste:
    - typecheck: PASS/FAIL + error count
    - vitest builder: PASS/FAIL + wall-clock + test count
    - vitest full: PASS/FAIL + wall-clock + test count
    - i18n parity: PASS/FAIL
    - e2e:smoke:builder: PASS/FAIL + wall-clock + per-spec results
    - e2e:smoke:perf: PASS/FAIL + measured PERF-01..04 values (or "Docker unavailable — handoff to user")
    - backend test_maps_bulk_layers: PASS/FAIL + test count
    - backend ruff: clean
    - build: PASS/FAIL + wall-clock
    - audit closeout: annotation count ≥ 17

    Then type "approved" to close Phase 1047, or describe any failures.
  </resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Phase close → CHANGELOG / SUMMARY | Misreporting could carry into v1010 closeout (Phase 1048) and the public CHANGELOG. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-06-01 | Repudiation | Silent P1 skip | mitigate | CODE-03 enforces "no silent skips" — Task 2 verification greps for `Status (Phase 1047)` annotations ≥ 17. Cannot pass without per-finding disposition. |
| T-1047-06-02 | Tampering | Perf regression hidden in smoke runtime | mitigate | PERF-06 budget gates: vitest ≤ 10.5s, cold build ≤ 1.7s. Final checkpoint runs all of them. |
| T-1047-06-03 | Tampering | Setting setLayerProperty default to layout instead of paint | mitigate | Test 4 in Task 1 pins the default to 'paint'. Test asserts the kind argument routes correctly. |
| T-1047-06-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Typecheck clean
- Vitest builder suite green ≤ 10.5s
- Vitest full suite green ≤ 75s
- i18n parity green
- e2e:smoke:builder green ≤ 50s (Docker required — defer to user if unavailable)
- e2e:smoke:perf green (Docker required)
- Backend tests + ruff green
- Cold build ≤ 1.7s
- Audit closeout annotation count ≥ 17
</verification>

<success_criteria>
1. CA-03 setLayerProperty extracted and used across 6 adapters; try-catch duplication eliminated.
2. BUILDER-CODE-AUDIT.md has `Status (Phase 1047)` annotations under every P0 (3) and P1 (14) finding; `1047-06-AUDIT-CLOSEOUT.md` matrix covers all 24 findings.
3. CODE-04 verified: CC-15 confirmed 0 occurrences; CC-16/CC-17 disposed.
4. CODE-05 verified: LayerStyleEditor ≤ 500; other large files measured + dispositioned.
5. `1047-06-PERF-BEFORE-AFTER.md` captures measured-after values for PERF-01..06 (or explicit handoff markers).
6. Final smoke gate green: typecheck, vitest builder, e2e:smoke:builder, e2e:smoke:perf, backend tests, i18n parity, ruff, build.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-06-SUMMARY.md` when done. Include:
- Per-finding disposition matrix (link to 1047-06-AUDIT-CLOSEOUT.md)
- PERF before/after table (link to 1047-06-PERF-BEFORE-AFTER.md)
- Final smoke gate results (paste from Task 4)
- One-paragraph milestone-narrative: what shipped, what deferred, which P1s landed beyond CA-03
- Followups list (anything that did not ship in this phase but needs Phase 1048 attention)

After commit, update `.planning/STATE.md`: set `stopped_at: Phase 1047 complete` and bump progress counters.
</output>
