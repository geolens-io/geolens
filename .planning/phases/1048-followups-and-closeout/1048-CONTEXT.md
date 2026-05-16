# Phase 1048: followups-and-closeout - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Three carried-forward builder follow-ups are resolved, the smoke gate is green, and the CHANGELOG records all v1010 user-visible changes — closing the milestone cleanly.

**Requirements covered (from REQUIREMENTS.md):**
- FOLLOWUP-01 — Invalid `popup_config` no longer silently blocks PUT round-trip. User sees actionable error toast/banner; backend rejection path surfaces a structured error; vitest covers failure surface + e2e covers success-path round-trip on the once-blocked test map.
- FOLLOWUP-02 — Add Data modal audit completes. Findings surfaced in audit doc; P0 fixes shipped inline or as targeted plans; deferred items documented with rationale. Alignment with v1008 unified-stack model verified (no leftover six-section assumptions).
- FOLLOWUP-03 — SourcesTab `it.todo` backlog at `.planning/backlog/SourcesTab-test-todos.md` (8 items) reaches zero: items either ship as live tests OR migrate to the documented backlog with rationale. Net `it.todo` count for SourcesTab drops to zero at closeout.
- CLOSE-01 — Smoke gate green at milestone close: typecheck clean, vitest builder suite regression-free vs pre-milestone count, builder Playwright smoke green, i18n parity green, frontend coverage thresholds met. Also absorbs the deferred Phase 1047 Docker-stack gates (e2e:smoke:builder, e2e:smoke:perf, backend pytest test_maps_bulk_layers, backend ruff).
- CLOSE-02 — `CHANGELOG.md` `[Unreleased]` section documents all v1010 user-visible changes with quantified perf wins + follow-up bug fixes (and a one-line note that the audit deliverables — `1046-BUILDER-CODE-AUDIT.md` + `1046-BUILDER-PERF-BASELINE.md` — landed under `.planning/`).

**Inputs (frozen by Phase 1047):**
- All Plan 01-06 SUMMARY.md files (perf wins, fix counts, file deltas).
- `1047-06-PERF-BEFORE-AFTER.md` — measured before/after for PERF-01..06 (source for CHANGELOG perf-win quantification).
- `1047-06-AUDIT-CLOSEOUT.md` — 24-finding disposition matrix.
- `1047-REVIEW.md` (status: clean after fixes — CR+WR all fixed; IN deferred).
- `1047-UI-REVIEW.md` (21/24 — 3 priority polish items: partial-failure-toast suffix, cursor-not-allowed scope, text-[13px] in BulkActionBar — may bundle into FOLLOWUP work or defer with rationale).
- `1047-VERIFICATION.md` (status: human_needed — Docker gates batched into CLOSE-01).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting (`workflow.skip_discuss=true`). Use ROADMAP phase goal, REQUIREMENTS.md, codebase conventions to guide.

### Hygiene-shape close (per `feedback_hygiene_milestone_pattern.md` memory)
- This is a closeout phase. Keep plan count low — 3-4 plans grouped by concern (FOLLOWUP, AUDIT, BACKLOG/CHANGELOG, FINAL GATE) — single batch close at the end.
- Do not split into multiple phases.

### FOLLOWUP-01 — popup_config validation surface
- **Backend path:** find where `popup_config` is validated on map PUT (likely `backend/app/modules/catalog/maps/router.py` or `service_layers.py` — adjacent to bulk-delete added in Plan 04). Surface structured rejection.
- **Frontend path:** find the map PUT call (likely `frontend/src/api/maps.ts` or `frontend/src/components/builder/hooks/use-builder-save.ts`). Surface the structured rejection as a sonner toast or banner. Reuse existing v1009 rollback-toast pattern.
- **Tests:** vitest covers failure surface (frontend translation of error → toast); e2e covers success-path round-trip on the previously-blocked test map. The "previously-blocked test map" should be a fixture the plan author identifies (likely in `e2e/fixtures/` or a known seeded map).

### FOLLOWUP-02 — Add Data modal audit
- Produce a single audit document: `.planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md`.
- Scope: `frontend/src/components/builder/BuilderDialogs.tsx`, `frontend/src/components/builder/AddDataModal*.tsx` (or equivalent), `frontend/src/components/builder/DatasetSearchPanel*.tsx`.
- Severity classification mirroring Phase 1046's pattern (P0 / P1 / P2 with file:line + recommended fix + Phase 1048-or-defer disposition).
- **Specifically check** for leftover six-section assumptions from pre-v1008 unified-stack model.
- Ship P0 fixes inline if any are found and effort is ≤1 hour each; otherwise defer-with-rationale.

### FOLLOWUP-03 — SourcesTab it.todo backlog
- Source list: `.planning/backlog/SourcesTab-test-todos.md` (8 items, verbatim from `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx`).
- Default: ship as live vitest tests against current SourcesTab implementation.
- Migrate-with-rationale only when (a) the underlying behavior has shifted since the test was deferred and the test author would need to re-design the assertion, OR (b) the test would require a new fixture/util that exceeds the closeout budget.
- Net `it.todo` count for SourcesTab MUST be zero at closeout. The backlog file gets a final disposition line per item.

### CLOSE-01 — smoke gate (includes Phase 1047 deferred Docker gates)
- Run all of:
  - `cd frontend && npm run typecheck` (must be 0 errors in production)
  - `cd frontend && npm test -- --run` (vitest full suite; no regression in builder subset)
  - `cd frontend && npm run e2e:smoke:builder` (Docker stack required)
  - `E2E_BACKEND_AVAILABLE=1 cd frontend && npm run e2e:smoke:perf` (Phase 1047 PERF-01..04 live)
  - `cd backend && uv run pytest tests/test_maps_bulk_layers.py -x` (Phase 1047 backend)
  - `cd backend && uv run ruff check app/modules/catalog/maps/`
  - `cd frontend && npm run check:i18n` (en/de/es/fr parity)
- Capture results in the final plan's SUMMARY + a small CLOSE-01 evidence sidecar.
- If a gate fails, halt and route as a blocker per autonomous workflow.

### CLOSE-02 — CHANGELOG entry
- Edit `CHANGELOG.md` `[Unreleased]` section.
- Use the existing 1.1.1 entry as the structural template (Added / Changed / Fixed / sections, quantified deltas).
- Pull perf-win numbers from `1047-06-PERF-BEFORE-AFTER.md` and code-quality counts from `1047-06-AUDIT-CLOSEOUT.md`.
- Reference Phase 1046 audit deliverables as a one-liner under "Internal".
- Note: actual version-tag bump is deferred to `/gsd-complete-milestone`; this phase just fills `[Unreleased]`.

### UI-REVIEW carry-over from Phase 1047
- 3 priority UI-REVIEW recommendations (partial-failure toast suffix, cursor-not-allowed container scope, text-[13px] arbitrary size in BulkActionBar) are minor polish.
- Default: bundle the 3 fixes into the FOLLOWUP plan that also fixes popup_config (since both touch builder UI). Keep the locale updates atomic with the suffix fix.

</decisions>

<code_context>
## Existing Code Insights

Starting points (plan-phase research will deepen):

**FOLLOWUP-01 — popup_config:**
- Backend: `backend/app/modules/catalog/maps/router.py` PUT handler + `service_layers.py` (where Phase 1047 Plan 04 also landed code; co-located change surface).
- Frontend save path: `frontend/src/components/builder/hooks/use-builder-save.ts` (or equivalent) + `frontend/src/api/maps.ts` PUT call.
- Toast pattern: `sonner` toast.error + retry action (see Phase 1047 Plan 04 + UI-SPEC for the established pattern + `bulkActions.*` i18n namespace; new key namespace likely `popupConfig.*`).
- Test map fixture: search e2e fixtures for "popup_config" or known-broken seed.

**FOLLOWUP-02 — Add Data modal:**
- Likely files: `frontend/src/components/builder/BuilderDialogs.tsx` (already touched in Plan 02 lazy-load), `frontend/src/components/builder/AddDataModal*`, `DatasetSearchPanel*`.
- Six-section assumption check: grep for `section`, `sections`, or any iteration over a hard-coded six-element list inside Add Data modal scope.

**FOLLOWUP-03 — SourcesTab:**
- Test file: `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx`.
- Component under test: `frontend/src/components/dataset/SourcesTab.tsx`.
- 8 items listed in `.planning/backlog/SourcesTab-test-todos.md`.

**CLOSE-01 evidence sources:**
- Phase 1047 SUMMARY files for baseline numbers.
- `frontend/package.json` smoke scripts.
- `backend/pyproject.toml` for pytest/ruff invocation.

**CLOSE-02 CHANGELOG template:**
- `CHANGELOG.md` `[1.1.1]` section is the structural model.

</code_context>

<specifics>
## Specific Ideas

- **Wave shape:** group plans by concern (the hygiene-milestone shape):
  - **Plan 01 — FOLLOWUP-01 popup_config + 3 carry-over UI-REVIEW fixes** (builder UI touch surface, single commit run).
  - **Plan 02 — FOLLOWUP-02 Add Data modal audit + any inline P0 fixes**.
  - **Plan 03 — FOLLOWUP-03 SourcesTab test backlog drain**.
  - **Plan 04 — CLOSE-01 final smoke gate + CLOSE-02 CHANGELOG entry** (single human-verify checkpoint at the end for Docker gates + CHANGELOG review).

  Adjust if a plan would balloon past ~5 tasks or if file overlap suggests merging.

- **CHANGELOG entry skeleton (Plan 04):**
  ```markdown
  ## [Unreleased]

  > v1010 Builder Performance & Code Quality milestone — large-map performance
  > wins (perceived latency, MapLibre paint coalescing, bulk-op batching), code-quality
  > refactor of the unified-stack Map Builder (LayerStyleEditor split, file-size compliance),
  > and three carried-forward builder follow-ups closed.

  ### Added
  - Backend bulk-delete endpoint `POST /api/maps/{id}/layers/bulk-delete` …
  - `coalesceFrame` rAF-coalescing utility …
  - `SceneSpinnerFallback` Suspense fallback for lazy-loaded editor scenes …
  - Bulk-op progress affordance: BulkActionBar `Loader2` + aria-live …

  ### Changed
  - Map Builder entry chunk reduced 281.76 KB → 230.98 KB (-18%) via lazy-loaded editor scenes.
  - LayerStyleEditor split 1231 LOC → 468 LOC orchestrator + per-render-mode children (-62%).
  - Bulk-delete on N layers now sends 1 batched HTTP request instead of N sequential …

  ### Fixed
  - Invalid `popup_config` no longer silently fails on map save — actionable error toast.
  - 8 code-quality findings from BUILDER-CODE-AUDIT.md (P0+P1) — see audit closeout matrix.

  ### Internal
  - `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md` — 24 findings (P0=3, P1=14, P2=7) classified.
  - `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md` — 6 PERF axes baselined.
  ```
  (Plan author refines with the actual measured numbers.)

</specifics>

<deferred>
## Deferred Ideas

- **Mobile builder polish, AI authoring, new render modes, new widgets, history panel UX** — all out of scope per REQUIREMENTS.md "Future Requirements".
- **Phase 1047 Info-level review findings (IN-01..IN-03)** — already deferred during Phase 1047 fix pass; no scope here unless trivially absorbed.
- **Backend schema changes beyond the Phase 1047 bulk-delete exception** — out of scope.
- **Render-mode work** — out of scope.

</deferred>
