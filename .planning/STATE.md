---
gsd_state_version: 1.0
milestone: v1027
milestone_name: Map Builder Architecture Simplification
status: complete
stopped_at: v1027 complete
last_updated: "2026-05-25T16:31:30Z"
last_activity: 2026-05-25 -- v1027 complete
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 6
  completed_plans: 6
  percent: 100
---

# State

## Current Position

Phase: v1027 complete
Plan: All planned phases complete
Status: Milestone complete
Last activity: 2026-05-25 -- v1027 complete

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1027 Map Builder Architecture Simplification — reduce map-builder orchestration complexity while preserving style reconciliation, AI action behavior, basemap/background settings, save/reload, viewer/embed parity, and target-map UAT behavior.

## Last Shipped Milestone

**Version:** v1027 Map Builder Architecture Simplification
**Shipped:** 2026-05-25
**Phases:** 1118-1123 (6 phases, 6 plans, 29/29 reqs satisfied)
**Commit:** local `v1027` tag target
**Tag:** `v1027`
**Milestone audit:** Completed by focused frontend/backend tests, frontend gates, Playwright MCP target-map smoke, destructive throwaway-copy UAT, and GSD open-item scan
**Archived phases:** v1027 local archive copies exist under ignored `.planning/milestones/`; backlog `999.*` phase directories remain.

## Phase Plan (v1027)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1118 Architecture Baseline and Complexity Budget | Audit ownership, define target boundaries, document regression surfaces, and pin no-regression constraints | ARCH-01..04 | — |
| 1119 Basemap State Controller | Consolidate basemap/background/terrain/sublayer state and close remove-basemap drift paths | BASEMAP-01..04 | Phase 1118 |
| 1120 Builder/Viewer Sync Orchestrator | Share source/layer/style/background/terrain sequencing between builder and viewer | SYNC-01..04 | Phase 1119 |
| 1121 Editor Scene Controller Extraction | Extract scene routing, settings/dialog/selection state, persistence, dirty-state, and save-semantics wiring | SCENE-01..04 | Phase 1120 |
| 1122 Layer Action Contract and AI Bridge Cleanup | Route manual actions, duplicate/remove flows, undo/history, persistence, and AI chat through typed command semantics | ACTION-01..04 | Phase 1121 |
| 1123 Test Fixture DRY-Up and Close Gate | DRY builder fixtures, run focused gates, complete Playwright MCP UAT, and update audit guidance | TEST-01..04, VERIFY-01..05 | Phases 1118-1122 |

**Coverage:** 29/29 v1027 requirements mapped, 0 orphans, 0 duplicates.

**Target map:** `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd`

**HARD INVARIANT:** Refactoring must reduce duplication and clarify ownership without changing existing builder behavior. Manual UI actions, AI chat actions, basemap/background settings, layer options, style reconciliation, undo/history, save/reload, public viewer, embed viewer, and target-map UAT flows must remain functionally equivalent or explicitly improved by a documented bug fix.

## Phase Progress

| Phase | Status | Evidence |
|-------|--------|----------|
| 1118 Architecture Baseline and Complexity Budget | Complete | `.planning/phases/1118-architecture-baseline-and-complexity-budget/1118-01-SUMMARY.md`; `.planning/phases/1118-architecture-baseline-and-complexity-budget/1118-ARCHITECTURE-BASELINE.md`; `.planning/phases/1118-architecture-baseline-and-complexity-budget/1118-COMPLEXITY-BUDGET.md`; `.planning/phases/1118-architecture-baseline-and-complexity-budget/1118-REGRESSION-SURFACES.md`; `.planning/phases/1118-architecture-baseline-and-complexity-budget/1118-STYLE-CONTRACT-PRESERVATION.md` |
| 1119 Basemap State Controller | Complete | `.planning/phases/1119-basemap-state-controller/1119-01-SUMMARY.md`; `.planning/phases/1119-basemap-state-controller/1119-VERIFICATION.md` |
| 1120 Builder/Viewer Sync Orchestrator | Complete | `.planning/phases/1120-builder-viewer-sync-orchestrator/1120-01-SUMMARY.md`; `.planning/phases/1120-builder-viewer-sync-orchestrator/1120-VERIFICATION.md` |
| 1121 Editor Scene Controller Extraction | Complete | `.planning/phases/1121-editor-scene-controller-extraction/1121-01-SUMMARY.md`; `.planning/phases/1121-editor-scene-controller-extraction/1121-VERIFICATION.md` |
| 1122 Layer Action Contract and AI Bridge Cleanup | Complete | `.planning/phases/1122-layer-action-contract-and-ai-bridge-cleanup/1122-01-SUMMARY.md`; `.planning/phases/1122-layer-action-contract-and-ai-bridge-cleanup/1122-VERIFICATION.md` |
| 1123 Test Fixture DRY-Up and Close Gate | Complete | `.planning/phases/1123-test-fixture-dry-up-and-close-gate/1123-01-SUMMARY.md`; `.planning/phases/1123-test-fixture-dry-up-and-close-gate/1123-VERIFICATION.md`; `.planning/milestones/v1027-MILESTONE-AUDIT.md` |

## Quick Tasks Completed

| Date | Quick ID | Slug | Status | Notes |
|------|----------|------|--------|-------|
| 2026-05-24 | 260524-o57 | adk-high-peaks-data | Delivered + 6 findings | Marketing-data ingest for ADK High Peaks AOI (1m DEM + NY 2023 orthos + 4 vector layers + curated 46er peaks). Map `c39be324-6815-40e5-8143-00a2723827b2` shippable; 6 GeoLens dogfooding findings filed in [260524-o57-API-ISSUES.md](quick/260524-o57-adk-high-peaks-data/260524-o57-API-ISSUES.md) — CRITICAL builder-reorder bug, HIGH DEM-maxzoom + basemap-toast root cause, MEDIUM terrain-config + toast-position, LOW sprite-refs cosmetic. |

## Accumulated Context

### Decisions

- **2026-05-25 (v1027 start):** Scope Map Builder Architecture Simplification as a GSD milestone, not a quick cleanup. The files involved are central to builder state, live MapLibre sync, persistence, viewer/embed parity, and AI action paths.
- **2026-05-25 (v1027 start):** Keep the milestone behavior-preserving by default. Any user-visible change must be a documented bug fix, with remove basemap, duplicate layer, layer editor save semantics, background color, terrain exaggeration, and gradient-to-solid treated as explicit regression surfaces.
- **2026-05-25 (v1027 start):** AI chat is in scope only where it shares the same map/layer/style command boundary as manual UI actions; broad chat UX redesign is out of scope.
- **2026-05-25 (v1027 start):** External research is skipped. This is internal architecture hardening driven by GeoLens codebase evidence and target-map UAT.
- **2026-05-25 (Phase 1119 close):** Basemap state now routes through a pure frontend controller. The non-persisted Land-Water basemap sublayer row was removed as a false affordance; editable sublayers are Roads, Labels, Buildings, and Boundaries.
- **2026-05-25 (Phase 1119 close):** Playwright MCP found and Phase 1119 fixed a MapLibre terrain/style transition error when restoring Positron after a blank-basemap save. Builder now clears terrain before style swaps and reapplies terrain on `idle` after the new style loads.
- **2026-05-25 (Phase 1120 close):** Builder and viewer full composition sync now share `map-composition-sync.ts`, a small sequencing helper around existing `map-sync` and basemap mutation primitives. Adapter behavior remains explicit in `map-sync.ts` and the layer adapters.
- **2026-05-25 (Phase 1120 close):** Viewer sync now passes saved `basemap_position` and aligns terrain/style swap recovery with builder by clearing terrain before style replacement and reseeding terrain on `idle`.
- **2026-05-25 (Phase 1121 close):** Editor scene routing, selected-layer lookup, saved-baseline lookup, synthetic basemap/settings layer descriptors, and editor-open state now live in `useBuilderEditorScene`. Desktop and mobile editor surfaces consume the same `editorLayer`.
- **2026-05-25 (Phase 1121 close):** `use-builder-layers` mutation helpers were split into `builder-layer-mutations.ts`; the existing duplicate-rendering helper remains re-exported for compatibility. Layer editor save semantics stay immediate preview plus map-level Save, with pending-preview state derived from `savedLayerBaseline`.
- **2026-05-25 (Phase 1122 close):** Layer mutations now have a typed frontend `BuilderLayerAction` boundary and `dispatchLayerAction` bridge. Manual editor/stack actions and AI chat wrappers share the same command semantics where practical.
- **2026-05-25 (Phase 1122 close):** Manual remove remains persisted through the server mutation, while AI/chat remove remains draft-only local state until map Save. Backend `ChatAction`, OpenAPI, and SDK artifacts were not touched.
- **2026-05-25 (Phase 1123 close):** Shared builder test fixtures now cover the highest-duplication `use-builder-layers` hook suites. Full mechanical fixture migration of every builder component test is deferred as optional future cleanup.
- **2026-05-25 (Phase 1123 close):** `/builder-audit` guidance was updated locally with v1027 architecture contracts: basemap controller, composition sync helper, editor scene controller, duplicate-rendering helper, and typed layer action boundary.
- **2026-05-25 (v1027 close):** Frontend focused tests, typecheck, lint, build, and Playwright MCP target-map smoke passed. Backend/OpenAPI/SDK gates were skipped for Phase 1123 because no backend/API/generated artifacts were touched by the close phase.
- **2026-05-25 (v1027 loose-end close):** Builder-audit guidance remains local/ignored. Follow-up cleanup migrated `map-stack.test.ts` to shared builder fixtures, converted the expected MapLibre vendor chunk warning into an explicit Vite build budget, and created ignored local archive copies for v1027 ROADMAP/REQUIREMENTS/phases.
- **2026-05-25 (v1027 loose-end close):** Destructive Playwright MCP UAT ran against a throwaway duplicate map and then deleted it. Duplicate layer, remove basemap, background color setting, save/reload persistence, tile readiness, and 0 warning/error browser-console status passed. The original ADK target map was rechecked unchanged afterward.
- **2026-05-25 (v1027 loose-end close):** `gsd-sdk query audit-open --json` reports 0 open items after adding complete frontmatter to two completed quick-task summaries and marking the quick-task archive container complete.
- **2026-05-25 (v1027 loose-end close):** Focused backend map/schema tests passed with `.env.test.example` exported (198 passed). A prior attempt without test env failed at setup because it looked for a generated test DB on the wrong Postgres port.
- **2026-05-25 (v1027 ship):** Local `v1027` tag created for the milestone. Builder-audit and v1027 local archive copies remain ignored.
- **2026-05-25 (v1026 start):** Scope Mapbuilder Style Reconciler as a GSD milestone rather than a quick patch. The immediate `line-gradient` stale-property bug is fixed, but the durable solution needs a shared style mutation/reconciliation contract across manual UI, adapters, AI chat, save/reload, and viewer/embed paths.
- **2026-05-25 (v1026 start):** AI chat style actions are in scope because `ChatPanel` applies `set_style` and `set_data_driven_style` through the same builder style handlers as manual UI edits. `set_style` should be classified explicitly as patch/replace/clear to avoid live-vs-saved drift.
- **2026-05-25 (v1026 start):** External research is skipped. This milestone is internal architecture hardening driven by observed GeoLens code paths, not discovery of a new domain feature.
- **2026-05-24 (Phase 1098 close):** OOS-01 took TRIM path (not CAP-RAISE fallback) — `maps/router.py` 1807 → 1793 LOC via private-helper docstring compression on 2 helpers (`_build_frame_ancestors` + `_meta_to_kwargs`). Zero behavior change. Allowlist at `test_layering.py:865` unchanged; no Phase 999.x backlog entry promoted.
- **2026-05-24 (Phase 1098 close):** OOS-03 required Rule 1 inline iteration. First defensive rewrite still called `make_safe_client()`, which constructs `httpx.AsyncClient(...)`. `tests/test_seed_natural_earth_reconciliation.py:328` patches the global `httpx.AsyncClient` to `_FakeAsyncClient` without teardown — contaminating subsequent tests. Second iteration: drop `make_safe_client()` call entirely, test `_revalidate_redirect` directly (mirroring the 6 sibling tests at lines 22-97 that already pass durably in full sequential). Leaker hunt deferred indefinitely per D-10.
- **2026-05-24 (Phase 1098 close):** Phase 1099 OAuth carry-forward expanded to 3 tests (not 2): T5 verify gate's `-n auto` Run B surfaced `test_oauth_login_redirect` in addition to OAUTH-01/OAUTH-02. Likely a third member of the same OAuth-mock-state leakage family. Phase 1099 should address holistically rather than narrowly-pinned 2-test scope.
- **2026-05-24 (v1023 roadmap):** Phase 1098 bundles OOS-01 + OOS-02 + OOS-03. Three coupling reasons: (a) all 3 share the measurement gate (sequential `failed == 0`); (b) all 3 are tightly scoped per-test fixes with low investigation cost (no spike required per REQUIREMENTS.md); (c) one re-measurement covers all 3 retirements atomically — splitting would double gate cost with no coverage gain.
- **2026-05-24 (v1023 roadmap):** Phase 1099 bundles OAUTH-01 + OAUTH-02. Likely share root cause (parallel-worker shared-state leakage in OAuth mock/session fixtures); one fix may close both. Per REQUIREMENTS.md OAUTH-02 framing: "if one fix closes both, OAUTH-02 SUMMARY references the OAUTH-01 closure SHA + shared regression pin."
- **2026-05-24 (v1023 roadmap):** Phase 1100 bundles CI-01 + CLOSE-01 per v1022 Phase 1097 precedent. CI live-verify IS the primary piece of close-gate evidence; CLOSE-01 acceptance criterion (f) explicitly requires the `gh run view --log` block embedded in the close-gate doc.
- **2026-05-24 (v1023 roadmap):** Phase 1099 sequenced AFTER Phase 1098 so the OAuth measurement gate runs against the already-zero OOS baseline. Avoids ambiguity about which failures are OOS vs OAuth when measuring `-n 4`.
- **2026-05-24 (v1023 roadmap):** No spike phase required. CI-01 is operator-driven verification. OOS triad + OAuth flakes are tightly scoped per-test fixes (REQUIREMENTS.md explicit: "spike scope: None required"). Follows v1022 PARA-02/HYG-01/CI-01 framing — spike only for architectural items.
- **2026-05-24 (v1023 roadmap):** v1019 TD-13 rules LIVE for v1023 from Day 1: REQ citation pinning (planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit) + traceability flip (executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in SAME commit as SUMMARY.md).
- **2026-05-24 (Phase 1099 close):** OAUTH-01/02/03 closed via D-04a fixture override (`client_session` shares `client`'s `dependency_overrides[get_db]` factory). Iter-2 Rule 1 inline iteration added `_ensure_public_app_url` monkeypatch fixture after T4 verify gate surfaced that the actual root cause was order-dependent `_PUBLIC_URL_CACHE` priming + `for_external_use=True` strict-config requirement (Phase 268 H-27 / SEC-13), NOT just the snapshot gap hypothesized in T2. Sequential 3062/0/38 preserved; -n 4 ×3 = 3062/0/38 literal-zero; -n auto ×3 within PARA-01 envelope (2 distinct unrelated failures in Run C). Two commits (`f57f1a76` iter-1 + `9922cce5` iter-2) mirror Phase 1098 OOS-03 two-iteration pattern.
- **2026-05-24 (Phase 1099 close):** Leaker hunt deferred per D-07a — the actual originator of `_PUBLIC_URL_CACHE` priming was traced via bisect to `test_dataset_metadata_idor.py` family but the fix surface stays at `test_oauth.py` per D-10. Future v1024+ test-isolation audit could promote priming pattern to a fixture if appetite arises.
- **2026-05-24 (Phase 1100 close):** CI-01 ships degraded — user-authorized 2026-05-24 via smart-discuss AskUserQuestion mirroring v1022 precedent (same GH Actions billing block at https://github.com/organizations/geolens-io/settings/billing since v1022 run 26359374410). Per D-01d, no fresh dispatch attempted — would just re-confirm the block. Substitute evidence captured: 5/5 docker healthy + /api/health 200 + sequential 3062/0/38 LITERAL + -n 4 3062/0/38 LITERAL + -n auto 3-run 1/0/0 distinct within v1022 PARA-01 envelope. v1024+ carry-forward chain v1022→v1023→v1024+. T4 atomic 5-file flip at SHA `892fca01`; tags `v1023` + `v1.5.8` cut at same SHA; pushed to origin successfully.

### Pending Todos

None — v1027 starts from a clean pending-todo slate.

### Blockers/Concerns

- **CI-01-v1027 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before CI-01 can close GREEN in v1027+. This remains outside the map-builder architecture invariant.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate live-verify on real GitHub Actions (billing block) | Carried forward to v1027+ as CI-01-v1027 | v1023 Phase 1100 degraded close (mirrors v1022 deferral) |

## Session Continuity

Last session: 2026-05-25T16:31:30Z
Stopped at: v1027 complete
Resume file: .planning/ROADMAP.md

## Operator Next Steps

- v1027 is complete and tagged locally as `v1027`.
- Start the next milestone with `$gsd-new-milestone` when ready.
