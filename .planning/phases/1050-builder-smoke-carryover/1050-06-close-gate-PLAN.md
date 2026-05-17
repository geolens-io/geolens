---
phase: 1050-builder-smoke-carryover
plan: 06
type: execute
wave: 3
depends_on: [1050-01, 1050-02, 1050-03, 1050-04, 1050-05]
files_modified:
  - CHANGELOG.md
autonomous: false
requirements: []

must_haves:
  truths:
    - "Smoke gate is green across typecheck, vitest, and e2e:smoke:builder"
    - "Playwright MCP re-verify confirms all 5 observed surfaces from v1010.1 SMOKE-FINDINGS.md are now clean"
    - "CHANGELOG records the close with measurable evidence (tile-URL counts for SF-04, console-error count deltas for SF-05/06, PUT count for SF-07, toast inventory for SF-08)"
    - "No regression in the 5 v1010 win surfaces previously re-verified by v1010.1 (lazy-load, debounce/rAF, bulk-delete, render-mode swap, popup_config error toast)"
  artifacts:
    - path: "CHANGELOG.md"
      provides: "[Unreleased] section populated with v1010.2 close note + 5 measured before/after numbers"
      contains: "v1010.2"
  key_links:
    - from: "CHANGELOG.md [Unreleased]"
      to: "Plans 01-05 commit SHAs + measured metrics"
      via: "5 bullets, one per SF-XX"
      pattern: "SF-04|SF-05|SF-06|SF-07|SF-08"
---

<objective>
Single CTRL-01 batch gate confirms all 5 SF closures shipped clean; CHANGELOG `[Unreleased]` populated; v1010.1 SMOKE-FINDINGS.md "Observed" evidence re-verified against the fresh stack via Playwright MCP for SF-04..08.

Purpose: This is the close gate — verifies SMOKE-08..12 collectively (no direct requirement mapping). Mirrors v1010 CLOSE-01..02 and v1010.1 CTRL-01 patterns. The plan has ONE checkpoint task (Playwright MCP re-verify is a human-driven verification) plus automated gates around it.

Output:
- Smoke gate evidence: typecheck 0, vitest green, e2e:smoke:builder green, Playwright MCP re-verify clean for SF-04..08
- `CHANGELOG.md` `[Unreleased]` populated with 5 measured before/after entries
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md
@.planning/phases/1050-builder-smoke-carryover/1050-01-SUMMARY.md
@.planning/phases/1050-builder-smoke-carryover/1050-02-SUMMARY.md
@.planning/phases/1050-builder-smoke-carryover/1050-03-SUMMARY.md
@.planning/phases/1050-builder-smoke-carryover/1050-04-SUMMARY.md
@.planning/phases/1050-builder-smoke-carryover/1050-05-SUMMARY.md

@CHANGELOG.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run the full automated smoke gate</name>
  <files>(no source code modifications — runs typecheck + vitest + e2e:smoke:builder gates only)</files>
  <read_first>
    - .planning/phases/1050-builder-smoke-carryover/1050-01-SUMMARY.md through 1050-05-SUMMARY.md (confirm all 5 plans landed)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md (the "Observed" sections for SF-04..08 — these are the surfaces the MCP re-verify will exercise)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 06 section — smoke commands list)
  </read_first>
  <action>
    Run the full automated gate in this order. If any step fails, STOP and fix inline before proceeding.

    1. **Frontend typecheck:**
       ```
       cd /Users/ishiland/Code/geolens/frontend && npm run typecheck
       ```
       Expected: 0 errors.

    2. **Targeted vitest sweep (all 5 touched test surfaces):**
       ```
       cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run \
         src/components/builder/__tests__/map-sync.dedupe.test.ts \
         src/components/builder/__tests__/map-sync.raster.test.ts \
         src/components/builder/__tests__/map-sync.cluster.test.ts \
         src/components/builder/hooks/__tests__/use-builder-layers.test.ts \
         src/components/builder/hooks/__tests__/use-builder-save.test.ts \
         src/components/builder/__tests__/BuilderMap.a11y.test.tsx \
         src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts \
         src/components/maps/hooks/__tests__/use-quicklook.test.ts \
         src/components/search/hooks/__tests__/use-saved-searches.test.ts
       ```
       Expected: all green; no skipped/disabled tests.

    3. **Full frontend vitest run** (regression sweep):
       ```
       cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run
       ```
       Expected: same-or-greater test count vs. v1010.1 baseline (v1010.1 ended at vitest 799/799 + 54/54 pages; v1010.2 should be ≥ that, with the new tests from plans 01..05 added).

    4. **e2e:smoke:builder:**
       ```
       cd /Users/ishiland/Code/geolens/frontend && npm run e2e:smoke:builder
       ```
       Expected: same scenario count as v1010.1 baseline (26/26 passing); no new failures.

    Capture the metric snapshots (test counts, timing) for the CHANGELOG entry in Task 3.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run typecheck && npm run test -- --run && npm run e2e:smoke:builder</automated>
  </verify>
  <acceptance_criteria>
    - typecheck exits 0.
    - Full vitest run: 0 failed; total count ≥ v1010.1 baseline + ≥ 6 net-new tests (3 from plan 04, 3 from plan 05, plus the dedupe + revoke + saved-searches additions from plans 01, 02, 03).
    - e2e:smoke:builder: all scenarios pass; count ≥ 26.
    - No MapLibre `there is no source with this ID` errors in any test stdout.
    - No new console.error patterns in test output.
  </acceptance_criteria>
  <done>
    All 3 automated gates green; metrics captured for CHANGELOG.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Playwright MCP re-verify against fresh stack</name>
  <files>(no source code modifications — live Playwright MCP re-verify against fresh stack; SF-XX surfaces only)</files>
  <read_first>
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md (the "Observed" sections for SF-04..08 — these are the EXACT surfaces to re-verify)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 06 — re-verify checklist)
  </read_first>
  <what-built>
    All 5 SF closures (plans 01..05) shipped + automated smoke gate green. This task is the live re-verify against a freshly-rebuilt Docker stack via Playwright MCP — orchestrator-scoped (MCP is not exposed to executor subagents per memory note in v1010.1).
  </what-built>
  <how-to-verify>
    **Setup:**
    1. Fresh stack rebuild:
       ```
       cd /Users/ishiland/Code/geolens && docker compose down -v && docker compose up -d --build
       ```
       Wait for 5/5 services healthy.
    2. Use the same admin login flow from v1010.1 (form-encoded POST to backend `/auth/login`).
    3. Open Playwright MCP browser at `http://localhost:8080`.

    **Re-verify each SF surface against the v1010.1 "Observed" evidence:**

    **SF-04 (SMOKE-08) — Vector source dedupe:**
    1. Login → navigate to a saved test map with N layers / M datasets where M < N (target: 8 layers / 2 datasets — same as v1010.1 test map `c868cc3a-a3a0-4714-b559-67b3f2b478e2` or equivalent).
    2. Capture network log filter on `data\\.` after initial paint.
    3. Expected: ~M × tiles-per-viewport unique tile URLs (target ≤ ~24, was ~80 in v1010.1).
    4. Count distinct `sig=...` tokens — should be ~M, not ~N.
    5. Toggle a layer's visibility off then on — no `there is no source with this ID` MapLibre console errors.

    **SF-05 (SMOKE-09) — Blob revoke timing:**
    1. Logout (clear `geolens-auth` localStorage).
    2. Open `/login`, submit form-encoded credentials.
    3. On redirect to `/`, evaluate `browser_console_messages` filter on `blob:|ERR_FILE_NOT_FOUND`.
    4. Expected: 0 `blob:` `net::ERR_FILE_NOT_FOUND` console errors (was 4 in v1010.1).
    5. Thumbnails visible pre-login render cleanly post-redirect (no broken-image placeholders).

    **SF-06 (SMOKE-10) — Anonymous pre-auth probes:**
    1. Logout + clear cookies + clear `geolens-auth` localStorage.
    2. Open `/login` fresh.
    3. Capture network log immediately.
    4. Expected: 0 requests to each of `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/`.
    5. Login → confirm those same hooks DO fire on authed pages (gating is on `isAuthenticated`, not blanket-disabled).
    6. Visit a non-admin page while authed → `/api/admin/ai-status/` should still NOT fire (gated additionally on `isAdmin`).
    7. Visit an admin page (e.g. AIStatusCard) while admin-authed → `/api/admin/ai-status/` DOES fire.

    **SF-07 (SMOKE-11) — Single thumbnail PUT on mount:**
    1. Hard-reload `/maps/{id}` for an existing saved map (one that has `hasThumbnail: false` OR a freshly-created map without thumbnail).
    2. Capture network log filter on `thumbnail`.
    3. Expected: exactly 1 `PUT /api/maps/{id}/thumbnail/` request (was 2 in v1010.1).
    4. Drag the zoom slider → no PUTs during drag, exactly 0 or 1 PUT after release (debounce still collapses).
    5. `⌘S` manual save → expected PUT after the debounce window settles.

    **SF-08 (SMOKE-12) — No false-positive basemap toast:**
    1. Open a saved map with a healthy basemap (e.g. openfreemap-positron) — let it fully load (visible tiles).
    2. Edit a layer's paint (e.g. opacity slider).
    3. Trigger save (`⌘S` or save button).
    4. Capture `evaluate(toasts)`.
    5. Expected: only `'Map saved'` toast, NO `'Basemap connection issue'` toast (was both in v1010.1).
    6. Round-trip: reload the map, edit again, save again — confirm no spurious toast on subsequent save.

    **Regression check — v1010 win surfaces (verified clean by v1010.1):**
    1. Bulk-delete: select 3 layers → confirm dropdown delete → 1 `POST /layers/bulk-delete` + `"3 layers deleted"` toast (v1010.1 SF-01 fix preserved).
    2. Render-mode swap: Layer 1 Line → Arrow → zero console errors (v1010.1 SF-02 fix preserved).
    3. StyleJsonDialog lazy: hard-reload → `StyleJsonDialog.tsx` NOT fetched until first open (v1010.1 SF-03 fix preserved).

    **Pass criteria:** All 5 SF surfaces re-verify clean against their v1010.1 "Observed" evidence; the 3 v1010.1 fixes show no regression. Capture screenshots for each pass.
  </how-to-verify>
  <resume-signal>
    Type "approved" if all 5 re-verifies pass clean and v1010.1 fixes show no regression. Otherwise describe the specific failing surface — the orchestrator will spawn an inline fix.
  </resume-signal>
  <action>
    See <how-to-verify> above — execute the 5 SF re-verify scenarios (SF-04..08) plus 3 regression checks against the v1010.1 inline fixes (SF-01 bulk-delete, SF-02 render-mode swap, SF-03 StyleJsonDialog lazy). Capture screenshots for each pass. This is a checkpoint task — Claude (orchestrator) drives the Playwright MCP browser; the user reviews and approves via <resume-signal>.
  </action>
  <verify>
    <human-check>5/5 SF surfaces re-verify clean against v1010.1 Observed evidence; 3/3 v1010.1 fixes show no regression; screenshots captured.</human-check>
  </verify>
  <done>
    All 5 SF re-verifies pass; all 3 v1010.1 fix regression checks pass; user types approved via <resume-signal>.
  </done>
</task>

<task type="auto">
  <name>Task 3: Populate CHANGELOG [Unreleased] with v1010.2 close note</name>
  <files>CHANGELOG.md</files>
  <read_first>
    - CHANGELOG.md (full file — locate the existing `[Unreleased]` section; review the v1010 + v1010.1 entry shapes as the template to mirror)
    - .planning/phases/1050-builder-smoke-carryover/1050-01-SUMMARY.md through 1050-05-SUMMARY.md (pull the measured before/after numbers from each)
    - Output of Task 1 (vitest count, e2e:smoke:builder pass count) and Task 2 (Playwright MCP re-verify metrics)
  </read_first>
  <action>
    Open `CHANGELOG.md` and find the `[Unreleased]` section. If empty or sparse, populate it with the v1010.2 close entry. Use the v1010 + v1010.1 entries as the format template (see memory `Last Shipped Milestone` for v1010.1 shape).

    Write the entry with this structure:

    ```markdown
    ## [Unreleased]

    ### Builder smoke carryover (v1010.2 — closes Phase 1050)

    Closed all 5 carried-forward smoke findings from v1010.1's 2026-05-17 Playwright MCP smoke (1 P1 + 4 P2). Map Builder now ships clean of all 2026-05-17 smoke noise.

    - **SF-04 / SMOKE-08 — Dedupe MapLibre vector tile sources** (commit `<sha-from-plan-01>`): Non-cluster vector layers now share a MapLibre source per unique `dataset_table_name`. Initial paint of the 8-layer / 2-dataset test map: ~80 → ~<measured> vector tile requests (network log filter on `data\\.`). Cluster sources remain per-layer (cluster radius/minPoints are per-layer settings). `swapLayerOnMap` + `handleAiRemoveLayer` route through new `getSourceIdForLayer(layer)` helper; per-layer `removeSource` calls replaced by desired-set prune in `removeStaleSourcesAndLayers` (reference-count-safe by construction). New test `map-sync.dedupe.test.ts` asserts `addSource` called 2× for 4 layers / 2 datasets.

    - **SF-05 / SMOKE-09 — Defer thumbnail blob revoke** (commit `<sha-from-plan-02>`): Post-login redirect to `/`: 4 → 0 `blob:` `net::ERR_FILE_NOT_FOUND` console errors. `use-map-thumbnail.ts` mirrors the `use-quicklook.ts:67-74` cleanup pattern — `URL.revokeObjectURL(data)` fires on `data` change AND component unmount (via `useEffect` cleanup), not on cache eviction without `<img>` teardown.

    - **SF-06 / SMOKE-10 — Gate anonymous pre-auth probes** (commit `<sha-from-plan-03>`): `/login` fresh-mount (anonymous): 5 → 0 401-error console entries for `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/`. `useSavedSearches` gated on `!!token`. `useAIStatus` consumers (`AIStatusCard`, `SettingsAITab`) pass `{ enabled: !!token && isAdmin }` — admin probe never fires from anonymous OR non-admin authed pages.

    - **SF-07 / SMOKE-11 — Single thumbnail PUT on mount** (commit `<sha-from-plan-04>`): Hard-reload of `/maps/{id}`: 2 → 1 `PUT /api/maps/{id}/thumbnail/` requests. Fix: <Fix Option A/B/C from plan-04 SUMMARY> — the upstream double-fire was <root cause from plan-04 SUMMARY>. The v1009.1 SP-16 module-level debounce (`captureThumbnail`) was already correct; the fix was at the caller level. New vitest asserts synchronous double-call collapse via fake timers.

    - **SF-08 / SMOKE-12 — Suppress false-positive basemap toast** (commit `<sha-from-plan-05>`): Saving a clean-basemap map: 2 toasts → 1 toast (`'Basemap connection issue'` suppressed; `'Map saved'` preserved). `basemapLoadedAtRef` latch set on first successful style load; `errorHandlerRef` body early-returns on transient 5xx when latch is set. Real first-load failures still surface (`setBasemapNotice('style')` path unchanged). Latch resets on basemap change so new basemap's first-load failure surfaces correctly.

    ### Smoke gate evidence

    - frontend typecheck: 0 errors
    - frontend vitest: <pass/total from Task 1> (≥ v1010.1 799/799 baseline + new tests)
    - e2e:smoke:builder: <pass/total from Task 1> (≥ v1010.1 26/26 baseline)
    - Playwright MCP re-verify (fresh `docker compose down -v && up -d --build` stack): 5/5 SF surfaces clean; 3/3 v1010.1 fixes show no regression
    ```

    Replace `<sha-from-plan-XX>` placeholders with the actual 8-char SHAs from each plan's landing commits. If a plan landed in multiple commits, list the primary one. Replace `<measured>` and `<root cause>` with the actual numbers / diagnosis from each plan's SUMMARY.md.

    DO NOT create a new version section (e.g. `## [v1010.2]`) — that happens at milestone close / tag time via `/gsd-complete-milestone`. The `[Unreleased]` section is the close note while the milestone is in progress.
  </action>
  <verify>
    <automated>grep -n "v1010.2\|SF-04\|SF-05\|SF-06\|SF-07\|SF-08" /Users/ishiland/Code/geolens/CHANGELOG.md | head -20</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "v1010.2" CHANGELOG.md` returns ≥ 1.
    - `grep -c "SF-04\|SF-05\|SF-06\|SF-07\|SF-08" CHANGELOG.md` returns ≥ 5 (one per SF entry).
    - Each SF entry contains a commit SHA placeholder OR a real 8-char SHA.
    - Each SF entry contains a measured before/after number (tile counts for SF-04, error counts for SF-05/06, PUT count for SF-07, toast inventory for SF-08).
    - Smoke gate evidence section lists typecheck / vitest / e2e:smoke:builder / Playwright MCP outcomes with metrics.
    - No new `## [vX.Y.Z]` section was added (only `[Unreleased]` updated).
  </acceptance_criteria>
  <done>
    CHANGELOG `[Unreleased]` populated with 5 SF entries + smoke gate evidence; commit SHAs filled in; measurable metrics recorded.
  </done>
</task>

</tasks>

<verification>
- Task 1 (automated gate): typecheck 0, vitest green, e2e:smoke:builder green.
- Task 2 (Playwright MCP re-verify): 5/5 SF surfaces clean; 3/3 v1010.1 fixes show no regression.
- Task 3 (CHANGELOG): `[Unreleased]` populated with 5 SF entries + smoke gate evidence + commit SHAs + measurable metrics.
</verification>

<success_criteria>
1. typecheck exits 0.
2. Full frontend vitest run: 0 failed; net-new test count ≥ 6 vs. v1010.1 baseline.
3. e2e:smoke:builder: same-or-greater scenario count as v1010.1 (≥ 26 scenarios passing).
4. Playwright MCP re-verify confirms all 5 v1010.1 SMOKE-FINDINGS "Observed" surfaces are now clean.
5. CHANGELOG `[Unreleased]` records the close with commit SHAs + measurable metrics per SF.
6. No regression in the 3 v1010.1 fixes (bulk-delete, render-mode swap, StyleJsonDialog lazy).
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-06-SUMMARY.md` when done — record:
- All 3 task outcomes (typecheck/vitest/e2e counts; MCP re-verify pass/fail per SF; CHANGELOG diff hash).
- Any deferred follow-ups discovered during MCP re-verify (with rationale).
- Confirmation that Phase 1050 is ready for `/gsd-complete-milestone v1010.2`.
</output>
