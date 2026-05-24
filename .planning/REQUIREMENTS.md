# Requirements: GeoLens — v1023 CI Live-Verify + OOS Hygiene Tail

**Defined:** 2026-05-24
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Close v1022's CI-01 carry-forward (`pytest-parallel-isolation` live-verify on real GH Actions) and retire the 5 pre-existing test failures surfaced during v1022's close gate (3 OOS triad + 2 oauth flake). Smallest-milestone, hygiene-shape — no new features, no production-code surface beyond targeted test fixes.

**Public tag target:** `v1.5.8` (SemVer patch — test-infra hygiene only; no API contract changes, no migrations, no production-code behavior change beyond the targeted test stabilizations).

**HARD INVARIANT (v1019 TD-13):** `failed == 0` in sequential mode is non-negotiable. v1022 close-gate baselines (the OOS-laden starting state for v1023): sequential **3060 passed / 3 OOS failed / 38 skipped** + `-n 4` **3059 passed / 2 OOS + 2 oauth flake failed / 38 skipped**. Post-v1023 target: sequential **3063+ passed / 0 NEW failed / 38 skipped** and `-n 4` **3063+ passed / 0 NEW failed / 38 skipped** (the 5 retired tests stay live but pass).

**Spike scope:** None required. CI-01 is operator-driven verification, the OOS triad + oauth flake are tightly scoped per-test fixes whose investigation cost is low. Skipped per v1022 PARA-02 / HYG-01 / CI-01 precedent (spike only for architectural items).

---

## v1023 Requirements

Requirements for this milestone. All `CI-*` / `OOS-*` / `OAUTH-*` / `CLOSE-*` IDs map to roadmap phases in ROADMAP.md.

### CI Verification

- [ ] **CI-01**: Live-verify the `pytest-parallel-isolation` CI gate on real GitHub Actions infrastructure (closes v1022 Phase 1097-02's deferred operator action). Origin: v1022 hit GH Actions billing block on first dispatch (run `26359374410`: 0/13 jobs executed, all failed/skipped at runner-allocation; billing annotation persisted at `/tmp/v1022-1097-billing-annotation.json`). Acceptance criteria: (a) operator resolves billing at https://github.com/organizations/geolens-io/settings/billing; (b) `gh run rerun 26359374410` (preserves SHA `5344cd50` as SHA-of-record) OR new dispatch on an equivalent post-v1022 commit; (c) `gh run watch <run_id>` shows `pytest-parallel-isolation` job conclusion `success`; (d) the full `gh run view <run_id> --log --job=<job_id>` block is embedded in the v1023 close-gate doc as evidence; (e) v1023 SUMMARY.md cross-references the v1022 carry-forward closure; (f) if the gate fails on first live run, the failure is fed back into a follow-up phase (not silently ignored). **Note:** gate-shape is already verified locally via v1022 Plan 1097-01 baselines (3-run `-n auto` 2/3/2 distinct deterministic + 0 ICN frames + sequential 3060/3 OOS/38 + `-n 4` 3059/4 OOS/38). This requirement closes the external-evidence gap, not the gate-shape itself.

### Out-of-Scope Failure Closure

The 3 pre-existing sequential-mode failures carried by v1019/v1020/v1021/v1022's "0 NEW failures" invariant. v1023 retires them so the post-v1023 invariant becomes `sequential 0 failed` literal (not "0 NEW failed").

- [ ] **OOS-01**: Close `test_layering` LOC-cap failure. Pin location to be confirmed by planner via `git grep -n "def test_layering" backend/tests/` (carried from v1019/v1020/v1021/v1022 OOS list). Acceptance criteria: (a) root-cause documented inline at the failing assertion site (e.g., comment block citing the offending module + line count + threshold); (b) fix EITHER decomposes the offending module to fit the cap OR raises the cap with documented rationale at the test source-of-record + corresponding `MAX_LOC` constant; (c) test passes in sequential, `-n 4`, and `-n auto` modes; (d) no regression on other layering invariants — if cap is raised, the rationale must explain why the new value is the load-bearing threshold (not arbitrary slack).

- [ ] **OOS-02**: Close `test_phase_275_readme_accuracy` failure. Pin location to be confirmed by planner via `git grep -n "def test_phase_275_readme_accuracy" backend/tests/`. Acceptance criteria: (a) root-cause documented (likely README drift from a post-Phase 275 surface change — `frontend/README.md` or `backend/README.md` or `README.md`); (b) fix EITHER updates README to match current state OR updates the test assertion if the README intent changed (rationale required); (c) test passes in sequential, `-n 4`, and `-n auto` modes; (d) if README content was updated, the change is human-reviewable (no auto-generation artifact).

- [ ] **OOS-03**: Close `test_ssrf_redirect` failure. Pin location to be confirmed by planner via `git grep -n "def test_ssrf_redirect" backend/tests/`. Acceptance criteria: (a) root-cause documented (likely SSRF redirect-following gate drift since the test was last validated — could be an `httpx` follow_redirects= default flip, a validator change, or a redirect-target allow-list change); (b) fix is at the production-code site (NOT the test assertion) unless the SSRF posture genuinely changed (in which case rationale + security review note required); (c) test passes in sequential, `-n 4`, and `-n auto` modes; (d) zero regression on the broader SSRF test family (`grep -rn "ssrf\|validate_url_for_ssrf" backend/tests/` — full pin family stays green).

### OAuth Parallel-Mode Stabilization

The 2 oauth callback test flakes that surface specifically under `pytest -n 4` parallel mode (sequential mode passes; classified as flake-class per `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 2). v1023 stabilizes them at the test-isolation layer.

- [ ] **OAUTH-01**: Close `test_callback_missing_state_returns_error` `-n 4` flake. Pin location to be confirmed by planner via `git grep -n "def test_callback_missing_state_returns_error" backend/tests/`. Acceptance criteria: (a) root-cause documented (likely shared-state leakage between parallel workers — session cookies, callback URLs, or oauth provider mocks bleeding across workers); (b) fix is at the test-isolation layer (fixture-scope adjustment, per-worker oauth mock, monkeypatch reset) NOT at the production callback handler unless a real concurrency bug is found (rationale + security review note required if production-code change); (c) test passes deterministically in sequential, `-n 4`, and `-n auto` modes across 3 consecutive runs; (d) zero regression on `test_callback_*` oauth test family.

- [ ] **OAUTH-02**: Close `test_callback_invalid_code_returns_error` `-n 4` flake. Pin location to be confirmed by planner via `git grep -n "def test_callback_invalid_code_returns_error" backend/tests/`. Acceptance criteria: (a)–(d) same shape as OAUTH-01 (paired flake — likely shares root cause; one fix may close both, in which case OAUTH-02 SUMMARY references the OAUTH-01 closure SHA + the shared regression pin).

### Close Gate

- [ ] **CLOSE-01**: Close gate for milestone v1023 — sequential pytest baseline now `failed == 0` (literal, not "0 NEW"), `-n 4` baseline `failed == 0` (literal), `-n auto` ≤30 distinct deterministic across 3 runs (PARA-01 invariant preserved), CHANGELOG `[1.5.8]` entry written with per-requirement evidence, tags `v1023` (local) + `v1.5.8` (public) cut at the close-gate commit SHA. Acceptance criteria: (a) sequential pytest result quoted verbatim in CLOSE-GATE.md showing `3063+ passed / 0 failed / 38 skipped` (NO OOS rows — the literal-zero state); (b) `-n 4` result quoted showing `3063+ passed / 0 failed / 38 skipped` (NO OOS rows — the literal-zero state); (c) `-n auto` 3-run measurement table showing ≤30 distinct (failed+errors) per run with stale-DB cleanup between runs (PARA-01 acceptance preservation); (d) live docker stack health spot-check (`docker compose ps` 5 services healthy + `curl http://localhost:8080/api/health` returns 200 — note no-trailing-slash per v1022 Phase 1097-01 [Rule 3]); (e) CHANGELOG `[1.5.8]` block lists CI-01, OOS-01, OOS-02, OOS-03, OAUTH-01, OAUTH-02 closures with the test pin names + line numbers; (f) CI-01's live-verify run-watch log embedded (the carried-over evidence requirement); (g) tags cut and recorded in `.planning/MILESTONES.md`.

---

## Future Requirements

Deferred to a later milestone. Catch-net for items that surface during v1023 execution.

_None at roadmap time. If any of the OOS/OAUTH fixes surfaces a deeper architectural issue (e.g., SSRF posture change requires a broader security review, oauth parallel-isolation needs a multi-test fixture refactor), promote that to a v1024+ item rather than blooming v1023 scope. Same precedent as v1021/v1022's escalation language._

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Postgres `max_connections` bump | Restated from v1020 + v1021 + v1022. Production envelope at 30 is correct; the fix surface for test-infra is per-fixture retry, not headroom. |
| Artificial `-n` cap below `auto` | Restated from v1020 + v1021 + v1022. Masks contention. CI default stays at `-n 4` per PERF-01, but `-n auto` determinism is the v1022 PARA-01 invariant that v1023 must preserve. |
| New test-infra hardening beyond CI/OOS/OAUTH | v1022 PARA-* / HYG-* closed the engine-retry envelope. v1023 does not add new envelope shapes — only closes the 5 named failures + the CI carry-forward. |
| Production-code refactor beyond the targeted OOS/OAUTH fixes | Smallest-milestone charter. If an OOS fix touches production code (OOS-03 SSRF likely will), keep the diff minimal and rationale-pinned. |
| Documentation site changes (`~/Code/getgeolens.com`) | Sibling repo. v1023 may produce internal `.planning/` audit docs but no docs-site copy. |
| New CI jobs beyond live-verifying the existing `pytest-parallel-isolation` gate | CI-01 is verification-only. Adding new CI jobs is out of scope until the 5 OOS/OAUTH failures retire and the new invariant (`sequential 0 failed` literal) is stable across 3+ post-v1023 milestones. |
| Stale backlog file consumption (`v13.12-low-findings.md`, `v13.12-medium-findings.md`, `ingest-audit-20260519-findings.md`) | Surveyed during v1023 backlog sweep (2026-05-24). All 3 files target shipped milestones (v13.13+, v1014, v1015, v1016) and would balloon v1023 well beyond smallest-milestone charter. Promote to a dedicated future hygiene milestone if appetite exists. |
| New retry envelopes / engine wrappers / fixture-isolation surfaces | v1022 closed PARA-01/02 + HYG-01. v1023 inherits the stabilized engine state — new infrastructure work is post-v1023. |
| Migrations | None required. All v1023 changes live in `backend/tests/` + targeted production-code sites (likely `backend/app/` for OOS-03 only) + `CHANGELOG.md` + `.planning/`. |

---

## Traceability

Which phases cover which requirements. Updated by the roadmapper during ROADMAP.md creation. Executor flips `Pending` → `Complete` in the SAME commit as the SUMMARY.md write per v1019 TD-13 `requirements_traceability_flip` rule.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CI-01 | TBD | Pending |
| OOS-01 | TBD | Pending |
| OOS-02 | TBD | Pending |
| OOS-03 | TBD | Pending |
| OAUTH-01 | TBD | Pending |
| OAUTH-02 | TBD | Pending |
| CLOSE-01 | TBD | Pending |

**Coverage:**
- v1023 requirements: 7 total
- Mapped to phases: 0 (pending roadmap creation)
- Unmapped: 7 ⚠️ (will be 0 ✓ after roadmapper runs)

---
*Requirements defined: 2026-05-24*
*Last updated: 2026-05-24 after initial definition*
