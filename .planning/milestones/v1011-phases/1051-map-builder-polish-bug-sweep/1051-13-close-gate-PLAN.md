---
phase: 1051
plan: 13
type: execute
wave: 13
depends_on: ["1051-01", "1051-02", "1051-03", "1051-04", "1051-05", "1051-06", "1051-07", "1051-08", "1051-09", "1051-10", "1051-11", "1051-12"]
files_modified:
  - CHANGELOG.md
autonomous: false
requirements: [CTRL-01]
tags: [builder, close-gate, smoke, changelog, mcp-reverify]

must_haves:
  truths:
    - "All four batched gates pass: frontend typecheck (npx tsc --noEmit returns 0 errors), full vitest run green (no new failures vs v1010.2 baseline), npm run e2e:smoke:builder green (no regression vs v1010.2 26/26 baseline), Playwright MCP re-verify of all 11 user-reported items on FRESH docker compose stack"
    - "CHANGELOG.md [Unreleased] section populated with one bullet per BUG/UX/RESP/INV requirement plus EMRG-01 outcome bullet plus CTRL-01 gate evidence summary"
    - "v1010.2 SF-04..08 win surfaces (source dedupe, blob revoke, anonymous gating, single-PUT, basemap latch) spot-checked during MCP re-verify and confirmed not regressed"
    - "Any code-review findings surfaced during the gate are fixed INLINE (per feedback_review_findings_inline.md) before the close, NOT deferred to v1011.1"
    - "Phase 1051 ready for milestone-close (orchestrator can proceed to /gsd-complete-milestone v1011)"
  artifacts:
    - path: "CHANGELOG.md"
      provides: "[Unreleased] section populated with v1011 bullets (one per fixed requirement + INV-01 disposition + EMRG-01 outcome + gate evidence)"
      contains: "BUG-01"
  key_links:
    - from: "All 12 prior plan commits (1051-01..12)"
      to: "CHANGELOG.md [Unreleased] entries"
      via: "One bullet per closed requirement; subject line summarizes; commit hash optional"
      pattern: "BUG-|UX-|RESP-|INV-|EMRG-"
---

<objective>
Fix CTRL-01: Single batched close gate confirms all 11 user-reported items shipped clean, INV-01 disposition + EMRG-01 outcome are reflected in CHANGELOG, and a fresh `docker compose down -v && up -d --build` stack passes Playwright MCP re-verify across all 11 fixed items.

Per critical_planning_directive #7 + `feedback_review_findings_inline.md`: any code-review findings that surface during the gate get fixed INLINE in this milestone — do NOT defer to v1011.1.

Per critical_planning_directive #11 + v1010.2 SF-04..08 reinforcement: spot-check the v1010.2 win surfaces (SF-04 vector tile source dedupe via `getSourceIdForLayer`; SF-05 quicklook blob revoke; SF-06 `enabled: !!token && isAdmin()` gating on `useAIStatus`/`useEmbeddingStats`/`useSavedSearches`; SF-07 module-level `autoCapturedMapIds` Set survives StrictMode; SF-08 `basemapLoadedAtRef` 3000ms save-flow window) for regression during the MCP re-verify.

This plan is the LAST plan in Phase 1051 and depends on EVERY prior plan being green-committed. If any prior plan is incomplete or its commit reverted, this plan must NOT proceed.

Purpose: Ship a clean v1011 release. No quiet skips, no quiet defers; the CHANGELOG is the durable contract with the user.
Output: Full smoke gate run; CHANGELOG.md `[Unreleased]` populated; MCP re-verify evidence captured.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md

<interfaces>
<!-- CHANGELOG bullet shape (per v1010.2 [Unreleased] section as reference). Keep-a-Changelog grouping. -->

Target [Unreleased] structure:

```
## [Unreleased]

### Fixed
- BUG-01: Regular layer visibility eye toggle now dispatches to MapLibre (was a no-op at /maps/<id> repro URL). Commit <hash>.
- BUG-02: Delete-layer now removes the layer from the sidebar AND the map render, with optimistic state update + rollback on error. Commit <hash>.
- BUG-03: Rename-group input now autofocuses on open (DropdownMenu restoreFocus race fixed via rAF-deferred focus). Commit <hash>.
- RESP-01: Collapsed right sidebar no longer overlaps the MapLibre NavigationControl at 800-1099px viewports. Commit <hash>.
- RESP-02: Coordinate readout pill no longer overlaps the top-right widget zone at narrow viewports. Commit <hash>.
- RESP-03: Right-sidebar Sheet overlays render exactly one close button at <800px viewport. Commit <hash>.

### Changed
- UX-01: Layer-group expand caret meets 24x24 px touch target using Lucide ChevronRight icon. Commit <hash>.
- UX-02: Basemap sublayer rows now show config-state indicator badges instead of per-row opacity slider; opacity editing remains in LayerEditorPanel flyout. Commit <hash>.
- UX-03: Basemap row is now draggable in the layer order with saved-map persistence (basemap_position field on MapBasemapConfig jsonb; no backend migration). Commit <hash>.
- UX-04: Map Settings -> Widgets section now uses clear Enable/Disable [name] labels for availability toggles. Commit <hash>.

### Removed
- INV-01: DETAIL LEVEL toggle removed — it was dead wiring (Phase 1038 TODO never implemented). FIX path (sublayer style persistence) documented as future backlog. Commit <hash>.

### Internal
- EMRG-01: <X> emergent finding(s) triaged: <X> fix-now, <Y> deferred. See .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md. Commit <hash>.
- CTRL-01: Close gate — typecheck 0 errors; vitest <N>/<N>; e2e:smoke:builder <M>/<M>; Playwright MCP re-verify of all 11 items + v1010.2 SF-04..08 spot-checks on fresh docker compose up stack.
```

Smoke gate commands (per PATTERNS.md Plan 13):

```
cd frontend && npx tsc --noEmit
cd frontend && npm test -- --run
cd frontend && npm run e2e:smoke:builder
```

Stack-up sequence for MCP re-verify:

```
docker compose down -v && docker compose up -d --build
docker compose ps   # confirm 5/5 services healthy
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Batched smoke gate (typecheck + vitest + e2e:smoke:builder)</name>
  <files>(no files modified)</files>
  <read_first>
    - frontend/package.json (verify the e2e:smoke:builder script name)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 13 smoke gate commands)
  </read_first>
  <action>
    Run, in order, against the working tree at HEAD (commits from Plans 01-12 already in place):

    1. `cd frontend && npx tsc --noEmit` — must return 0 errors. If errors surface, STOP and surface to orchestrator (gate failure). Per feedback_review_findings_inline.md, fix inline if the error is from a Plan 01-12 commit; do NOT defer.
    2. `cd frontend && npm test -- --run` — full vitest run. Must complete with 0 failures. Capture the total test count for the CHANGELOG entry (e.g. vitest 1928/1928). Compare against v1010.2 baseline (1913/1913 per MEMORY.md) — the delta should reflect regression tests added across Plans 02/03/04/05/06/07/10. Acceptable: counts >= v1010.2 baseline + new tests; unacceptable: any net failure.
    3. `cd frontend && npm run e2e:smoke:builder` — Playwright e2e smoke. Must be >=26/26 (v1010.2 baseline). New regression = STOP.
    4. (Optional cross-check) `cd frontend && npm run i18n:check 2>/dev/null` if such a script exists, OR manually grep each locale file for parity of the new keys added in Plans 05/06/07.

    Record each command's pass/fail + counts in a scratch note for use in Task 3 CHANGELOG bullet.

    NOTE: per feedback_ci_local_first.md, run these locally BEFORE any push.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit ; cd frontend && npm test -- --run 2>&1 | tail -20 ; cd frontend && npm run e2e:smoke:builder 2>&1 | tail -20</automated>
  </verify>
  <acceptance_criteria>
    - npx tsc --noEmit returns 0 errors
    - vitest run completes with 0 failures; total count >= v1010.2 baseline (1913) + tests added by Plans 02-10
    - e2e:smoke:builder >=26/26 (no regression vs v1010.2)
    - All three gate command outputs captured for the CHANGELOG entry
  </acceptance_criteria>
  <done>Batched smoke gate green; gate evidence captured.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 2: Playwright MCP re-verify on fresh stack — all 11 items + v1010.2 SF-04..08 spot-check</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 13 MCP re-verify list + cross-cutting v1010.2 spot-check section)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md (v1010.2 SF-04..08 spot-check guidance)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps:

    (a) Bring the stack up fresh: `docker compose down -v && docker compose up -d --build`. Wait for all 5 services healthy (`docker compose ps`). Confirm `http://localhost:8080` reachable.

    (b) Re-verify EACH of the 11 fixed items (use the Plan 01-11 success criteria as the test list):
    - BUG-01: navigate to http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2; toggle Layer 1 eye; confirm MapLibre visibility flips visible<->none on each click; tiles disappear/reappear.
    - BUG-02: open a map with >=2 layers; delete a non-basemap layer; confirm row disappears immediately (optimistic); confirm map tiles disappear; reload page; confirm deletion persists.
    - BUG-03: click kebab -> Rename group; confirm document.activeElement is the rename input; type a character -> confirm it enters the input.
    - UX-01: measure caret button getBoundingClientRect() on BasemapGroupRow + FolderGroupRow; confirm >=24x24.
    - UX-02: expand a basemap group; confirm no per-sublayer opacity slider; confirm any present config-state indicator badges render correctly; click a sublayer -> confirm LayerEditorPanel still exposes opacity edit.
    - UX-03: drag basemap row to top of stack; confirm group-drag (sublayers move with parent); save; reload; confirm position persists; confirm MapLibre layer order reflects (basemap fill/raster above data).
    - UX-04: open Map Settings -> Widgets; confirm each toggle has Enable/Disable [name] aria-label; toggle a widget off -> confirm it disappears from map render; on -> reappears.
    - RESP-01: resize viewport to 800/900/1024; confirm NavigationControl is visible + clickable + no overlap with sidebar.
    - RESP-02: same viewport set; confirm MapCoordReadout no overlap with top-right widget zone.
    - RESP-03: resize to 780px; open layer editor (Sheet overlay); confirm exactly 1 close button visible.
    - INV-01: open basemap sublayer editor; confirm DETAIL LEVEL section is absent.

    (c) Spot-check v1010.2 SF-04..08 surfaces:
    - SF-04 (source dedupe): open a map with shared-source vector layers; via DevTools Network or `map.getStyle().sources`, confirm sources are deduped by dataset_table_name (no per-layer source duplication).
    - SF-05 (blob revoke): open a map with raster quicklook layers; navigate away + return; confirm no blob URL leak (Memory profile if accessible).
    - SF-06 (anonymous gating): log out; visit a builder page; confirm useAIStatus, useEmbeddingStats, useSavedSearches do not fire requests (no 401s in network panel from anonymous probe).
    - SF-07 (StrictMode-survival): open a builder map; refresh; confirm thumbnail PUT does not fire twice (single PUT in network panel).
    - SF-08 (basemap latch): save a map; confirm no false-positive Basemap toast appears during the 3000ms save-flow window.

    (d) If ANY MCP re-verify step fails OR any v1010.2 spot-check shows regression: STOP. Per feedback_review_findings_inline.md, fix inline in this milestone (re-open the relevant Plan 01-11 OR add a hot-fix commit). Re-run gate. Do NOT defer to v1011.1.
  </action>
  <verify>
    <automated>Playwright MCP captures 11 + 5 verification screenshots/evidence; orchestrator confirms zero regressions; docker compose ps shows 5/5 healthy.</automated>
  </verify>
  <acceptance_criteria>
    - Fresh stack: 5/5 services healthy
    - All 11 user-reported items pass MCP re-verify
    - All 5 v1010.2 SF spot-checks pass (no regression)
    - Any inline fixes (if needed) committed with subject prefix `fix(1051): inline gate-fix — <description>`
    - Re-run gate after any inline fix returns green
  </acceptance_criteria>
  <done>Fresh-stack MCP re-verify confirms phase ships clean.</done>
</task>

<task type="auto">
  <name>Task 3: Populate CHANGELOG.md [Unreleased] + atomic close-gate commit</name>
  <files>CHANGELOG.md</files>
  <read_first>
    - CHANGELOG.md (top of file — confirm an [Unreleased] section exists OR needs to be created above the prior version entry)
    - Each of .planning/phases/1051-map-builder-polish-bug-sweep/1051-{01..12}-SUMMARY.md (read the disposition + commit hash references)
    - .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md (EMRG-01 outcome summary)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 13 CHANGELOG shape)
  </read_first>
  <action>
    Edit `CHANGELOG.md` `[Unreleased]` section per the shape in <interfaces> above. Group entries by Keep-a-Changelog convention:

    - `### Fixed`: BUG-01, BUG-02, BUG-03, RESP-01, RESP-02, RESP-03 (one bullet each, repro URL where applicable + commit hash)
    - `### Changed`: UX-01, UX-02, UX-03, UX-04 (one bullet each)
    - `### Removed`: INV-01 (REMOVE disposition with rationale)
    - `### Internal`: EMRG-01 outcome (X fix-now, Y defer with FINDINGS.md link) + CTRL-01 gate evidence (typecheck/vitest/e2e counts + MCP re-verify pass)

    Get commit hashes via `git log --oneline -15` (the 12 plan commits + any inline gate-fix commits from Task 2). For each requirement bullet, append the short commit hash. For Plan 12's commit, the EMRG bullet references its hash; the per-finding fix-now commits (if any) are referenced inside FINDINGS.md, not duplicated here.

    Then stage CHANGELOG.md and commit: `chore(1051): CTRL-01 close gate + CHANGELOG (v1011 Map Builder Polish & Bug Sweep)` with body summarizing the gate evidence (gate counts, MCP coverage, SF spot-checks pass).
  </action>
  <verify>
    <automated>grep -E '^(### Fixed|### Changed|### Removed|### Internal|- \*\*BUG-|- \*\*UX-|- \*\*RESP-|- \*\*INV-|- \*\*EMRG-|- \*\*CTRL-|- BUG-|- UX-|- RESP-|- INV-|- EMRG-|- CTRL-)' CHANGELOG.md | head -20 ; git log --oneline -1 ; git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - CHANGELOG.md [Unreleased] contains one bullet for each of BUG-01..03, UX-01..04, RESP-01..03, INV-01 (11 user-reported items)
    - CHANGELOG.md [Unreleased] contains EMRG-01 outcome bullet + CTRL-01 gate evidence bullet
    - Commit hashes from Plans 01-12 (and any inline gate-fix commits) referenced in the bullets
    - Atomic commit exists with subject `chore(1051): CTRL-01 close gate + CHANGELOG (v1011 Map Builder Polish & Bug Sweep)`
    - `git diff HEAD~1 HEAD --stat` shows only CHANGELOG.md modified
  </acceptance_criteria>
  <done>CHANGELOG populated; close-gate commit pushed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| docs-only | CHANGELOG update is documentation; gate runs read-only against codebase |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-13 | (n/a) | close gate | accept | No new security surface; gate is verification-only |
</threat_model>

<verification>
- Batched smoke gate green: typecheck 0 errors; vitest 0 failures; e2e:smoke:builder >=26/26
- Fresh stack Playwright MCP re-verifies all 11 user-reported items
- v1010.2 SF-04..08 spot-checks pass (no regression)
- Any inline gate-fix findings fixed inline (per feedback_review_findings_inline.md) — none deferred
- CHANGELOG.md [Unreleased] populated with 13 bullets (11 fix + EMRG + CTRL)
</verification>

<success_criteria>
- Smoke gate is green across typecheck, vitest, and e2e:smoke:builder
- Playwright MCP re-verify confirms all 11 user-reported items are now fixed on a fresh stack
- CHANGELOG records the close with one bullet per fixed item + INV-01 disposition + EMRG-01 outcome + gate evidence
- No regression in the v1010.2 win surfaces (SF-04..08)
- Any code-review findings from the gate are fixed inline (zero deferrals to v1011.1)
- Atomic close-gate commit on main with subject `chore(1051): CTRL-01 close gate + CHANGELOG (v1011 Map Builder Polish & Bug Sweep)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-13-SUMMARY.md` with: gate counts (typecheck/vitest/e2e), MCP re-verify evidence (per-item pass/fail), v1010.2 SF spot-check results, list of any inline gate-fix commits, final CHANGELOG diff snippet.
</output>
