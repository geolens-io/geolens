---
gsd_state_version: 1.0
milestone: v1023
milestone_name: CI Live-Verify + OOS Hygiene Tail
status: planning
last_updated: "2026-05-24"
last_activity: 2026-05-24
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: 1098 of 3 (OOS Triad Closure) — ready to plan
Plan: —
Status: Ready to plan
Last activity: 2026-05-24 — v1023 roadmap created; Phase 1098 next

Progress: [░░░░░░░░░░] 0%

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1023 CI Live-Verify + OOS Hygiene Tail — retire 3 OOS sequential failures + 2 OAuth parallel flakes so `failed == 0` is literal, then close with live CI evidence.

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

- **2026-05-24 (v1023 roadmap):** Phase 1098 bundles OOS-01 + OOS-02 + OOS-03. Three coupling reasons: (a) all 3 share the measurement gate (sequential `failed == 0`); (b) all 3 are tightly scoped per-test fixes with low investigation cost (no spike required per REQUIREMENTS.md); (c) one re-measurement covers all 3 retirements atomically — splitting would double gate cost with no coverage gain.
- **2026-05-24 (v1023 roadmap):** Phase 1099 bundles OAUTH-01 + OAUTH-02. Likely share root cause (parallel-worker shared-state leakage in OAuth mock/session fixtures); one fix may close both. Per REQUIREMENTS.md OAUTH-02 framing: "if one fix closes both, OAUTH-02 SUMMARY references the OAUTH-01 closure SHA + shared regression pin."
- **2026-05-24 (v1023 roadmap):** Phase 1100 bundles CI-01 + CLOSE-01 per v1022 Phase 1097 precedent. CI live-verify IS the primary piece of close-gate evidence; CLOSE-01 acceptance criterion (f) explicitly requires the `gh run view --log` block embedded in the close-gate doc.
- **2026-05-24 (v1023 roadmap):** Phase 1099 sequenced AFTER Phase 1098 so the OAuth measurement gate runs against the already-zero OOS baseline. Avoids ambiguity about which failures are OOS vs OAuth when measuring `-n 4`.
- **2026-05-24 (v1023 roadmap):** No spike phase required. CI-01 is operator-driven verification. OOS triad + OAuth flakes are tightly scoped per-test fixes (REQUIREMENTS.md explicit: "spike scope: None required"). Follows v1022 PARA-02/HYG-01/CI-01 framing — spike only for architectural items.
- **2026-05-24 (v1023 roadmap):** v1019 TD-13 rules LIVE for v1023 from Day 1: REQ citation pinning (planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit) + traceability flip (executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in SAME commit as SUMMARY.md).

### Pending Todos

None at v1023 roadmap-create.

### Blockers/Concerns

- **CI-01 billing prerequisite:** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before Phase 1100 can execute. `gh run rerun 26359374410` preserves SHA `5344cd50` as SHA-of-record. If billing unresolvable, new dispatch on an equivalent post-v1023 commit is the fallback.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate first post-merge run (run 26359374410) | In scope as v1023 CI-01 — Phase 1100 | v1022 Phase 1097 degraded close |

## Session Continuity

Last session: 2026-05-24
Stopped at: v1023 roadmap created (ROADMAP.md + STATE.md + REQUIREMENTS.md traceability updated). Phase 1098 ready to plan.
Resume file: None
