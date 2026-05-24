---
gsd_state_version: 1.0
milestone: v1024
milestone_name: ADK High Peaks Marketing-Ready
status: planning
last_updated: "2026-05-24T23:31:43.894Z"
last_activity: 2026-05-24
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-24 — Milestone v1024 started

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1024 ADK High Peaks Marketing-Ready — upgraded ADK marketing data/maps, builder layer ordering, terrain controls, and Playwright MCP verification

## Last Shipped Milestone

**Version:** v1023 CI Live-Verify + OOS Hygiene Tail
**Shipped:** 2026-05-24 (degraded — CI-01 deferred to v1024+)
**Phases:** 1098-1100 (3 phases, 3 plans, 7/8 reqs satisfied; CI-01 carry-forward to v1024+)
**Tag:** `v1023` (local) + `v1.5.8` (public) at commit `892fca01`
**Milestone audit:** PENDING — orchestrator runs /gsd:audit-milestone v1023 next
**Archived phases:** (pending /gsd:cleanup-milestone — will move to `.planning/milestones/v1023-phases/`)

## Phase Plan (v1024)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1101 ADK Source Data Upgrade | TNM/NAIP aerial path or documented no-data fallback; NHD hydrography; expanded 46er peak source data | ADK-DATA-01..05 | — |
| 1102 ADK Saved Map Composition | Primary map refresh + bonus 3D relief variant Map 2 | ADK-MAP-01..03 | Phase 1101 |
| 1103 Builder Mixed Layer Reorder | Mixed raster/vector reorder updates live MapLibre canvas and persists | BUILDER-01, BUILDER-02 | Phase 1102 |
| 1104 Terrain Rendering and Config | DEM zoom metadata, explicit terrain disabled state, terrain/exaggeration controls | TERRAIN-01..04 | Phase 1102 |
| 1105 Builder Error Hygiene | Specific map error routing, non-overlapping toast, Positron sprite warning cleanup | TOAST-01, TOAST-02, BASEMAP-01, SPRITE-01 | Phase 1104 |
| 1106 Playwright Marketing Close Gate | Live Playwright MCP smoke + close evidence | VERIFY-01..03 | Phases 1103-1105 |

**Coverage:** 21/21 v1024 requirements mapped, 0 orphans, 0 duplicates.

**Public tag target:** `v1.5.9` (SemVer patch — data/script + UI/rendering bug fixes; avoid API/schema/migration changes unless a verified fix requires them).

**HARD INVARIANT:** A freshly composed ADK map at `localhost:8080/maps/{new_id}` opens in the builder with zero browser console errors/warnings, vectors above rasters after reorder, and working terrain settings/exaggeration controls verified through Playwright MCP.

## Quick Tasks Completed

| Date | Quick ID | Slug | Status | Notes |
|------|----------|------|--------|-------|
| 2026-05-24 | 260524-o57 | adk-high-peaks-data | Delivered + 6 findings | Marketing-data ingest for ADK High Peaks AOI (1m DEM + NY 2023 orthos + 4 vector layers + curated 46er peaks). Map `c39be324-6815-40e5-8143-00a2723827b2` shippable; 6 GeoLens dogfooding findings filed in [260524-o57-API-ISSUES.md](quick/260524-o57-adk-high-peaks-data/260524-o57-API-ISSUES.md) — CRITICAL builder-reorder bug, HIGH DEM-maxzoom + basemap-toast root cause, MEDIUM terrain-config + toast-position, LOW sprite-refs cosmetic. |

## Accumulated Context

### Decisions

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

None — v1023 closed.

### Blockers/Concerns

- **CI-01-v1024 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before CI-01 can close GREEN in v1024+. Once resolved: `gh run rerun 26359374410` (preserves v1022 SHA-of-record `5344cd50`) OR new dispatch on a post-v1023 commit → `gh run watch <run_id>` → embed `gh run view <run_id> --log --job=<job_id>` block in v1024+ CI-01 closure phase doc.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate live-verify on real GitHub Actions (billing block) | Carried forward to v1024+ as CI-01-v1024 | v1023 Phase 1100 degraded close (mirrors v1022 deferral) |

## Session Continuity

Last session: 2026-05-24T23:31:43.894Z
Stopped at: v1024 initialized from ADK High Peaks marketing-ready scope; autonomous execution requested
Resume file: .planning/ROADMAP.md

## Operator Next Steps

- Run autonomous v1024 execution from Phase 1101
