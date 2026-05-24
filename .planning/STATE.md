---
gsd_state_version: 1.0
milestone: v1023
milestone_name: CI Live-Verify + OOS Hygiene Tail
status: executing
stopped_at: Phase 1099 Plan 01 shipped — ready for Phase 1100
last_updated: "2026-05-24T15:55:21.335Z"
last_activity: 2026-05-24 -- Phase 1099 OAUTH-01/02/03 shipped
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 4
  completed_plans: 2
  percent: 50
---

# State

## Current Position

Phase: 1100 (CI Live-Verify + Close Gate) — next
Plan: 1100-01 — pending
Status: Awaiting CI-01 operator action (billing resolution)
Last activity: 2026-05-24 -- Phase 1099 OAUTH-01/02/03 shipped

Progress: [█████░░░░░] 50%

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1100 — CI Live-Verify + Close Gate

## Last Shipped Milestone

**Version:** v1022 Parallel-Test Cascade Closure + Hygiene Tail
**Shipped:** 2026-05-24 (degraded — CI-01 deferred)
**Phases:** 1094-1097 (4 phases, 6 plans, 5/6 reqs; CI-01 carry-forward to v1023)
**Tag:** `v1022` (local) + `v1.5.7` (public) at commit `48707fb1`
**Milestone audit:** `.planning/milestones/v1022-MILESTONE-AUDIT.md`
**Archived phases:** `.planning/milestones/v1022-phases/`

## Phase Plan (v1023)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1098 OOS Triad Closure | Sequential `failed == 0` literal: fix test_layering + test_phase_275_readme_accuracy + test_ssrf_redirect | OOS-01, OOS-02, OOS-03 | — |
| 1099 OAuth Parallel-Mode Stabilization | `-n 4` `failed == 0` literal: eliminate test_callback_missing_state_returns_error + test_callback_invalid_code_returns_error flakes | OAUTH-01, OAUTH-02 | Phase 1098 |
| 1100 CI Live-Verify + Close Gate | `gh run watch` confirms `pytest-parallel-isolation` success on live GH Actions + CHANGELOG `[1.5.8]` + tags `v1023`/`v1.5.8` | CI-01, CLOSE-01 | Phase 1099 |

**Coverage:** 7/7 v1023 requirements mapped, 0 orphans, 0 duplicates.

**Public tag target:** `v1.5.8` (SemVer patch — test-infra hygiene only; no API/schema changes, no migrations).

**HARD INVARIANT (v1019 TD-13):** Sequential pytest `failed == 0` non-negotiable. v1022 close-gate baselines (v1023 starting state): sequential **3060/3 OOS/38** + `-n 4` **3059/4 OOS+oauth/38**. Post-v1023 target: sequential **3063+/0/38** + `-n 4` **3063+/0/38** (literal zero — OOS rows retired, not bypassed).

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

### Pending Todos

None at v1023 roadmap-create.

### Blockers/Concerns

- **CI-01 billing prerequisite:** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before Phase 1100 can execute. `gh run rerun 26359374410` preserves SHA `5344cd50` as SHA-of-record. If billing unresolvable, new dispatch on an equivalent post-v1023 commit is the fallback.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate first post-merge run (run 26359374410) | In scope as v1023 CI-01 — Phase 1100 | v1022 Phase 1097 degraded close |

## Session Continuity

Last session: 2026-05-24T15:55:06.260Z
Stopped at: Phase 1099 Plan 01 shipped — ready for Phase 1100
Resume file: .planning/phases/1099-oauth-parallel-mode-stabilization/1099-01-SUMMARY.md
