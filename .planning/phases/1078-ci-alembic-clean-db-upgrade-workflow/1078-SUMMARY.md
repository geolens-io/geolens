---
phase: 1078-ci-alembic-clean-db-upgrade-workflow
completed_at: 2026-05-21
requirements: [CI-01]
plans_completed: 2
verdict: PASS
tests_run: 1
tests_passed: 1
tests_failed: 0
tests_skipped: 0
duration_minutes: ~10 (cumulative across 2 plans)
---

# Phase 1078 — CI Alembic Clean-DB Upgrade Workflow

**Wired `backend/scripts/test_alembic_upgrade_clean_db.sh` (built in v1016 Phase 1071 KNOWN-02) into `.github/workflows/ci.yml` as a peer of the existing backend gates so migration regressions against a fresh PostGIS+pgvector DB fail the CI build immediately; closes SEC-OBSV-03 from v1016 Phase 1072 triage.**

## Summary

Phase 1078 closes the v1017 CI-hardening tail with a single, additive change to `.github/workflows/ci.yml`:

- **CI-01** — Added an `alembic-clean-db` job (40 lines) between `backend-test` and the frontend section. The job uses the same `actions/checkout@v6` + `astral-sh/setup-uv@v8.1.0` (v0.10.2 pin) + `actions/setup-python@v6` (3.13 pin) shape as the other backend gates, then invokes `./backend/scripts/test_alembic_upgrade_clean_db.sh` directly. The script (shipped in v1016 Phase 1071) owns the docker lifecycle internally: build the project's custom PostGIS+pgvector image from `db/Dockerfile`, spin up a throwaway container on `127.0.0.1:54399` with `scripts/init-db.sh` mounted, poll for `vector` extension readiness, then run `uv run --no-dev alembic upgrade head` from `backend/`. The trap-based cleanup drops the container on every exit path.

- The trigger condition mirrors the other backend gates: `needs.changes.outputs.alembic == 'true' || github.event_name == 'push'`. A new `alembic:` slot in the `changes` job's `outputs` block + `filters` block fires the workflow only when migration-relevant paths change (`backend/alembic/**`, `backend/scripts/test_alembic_upgrade_clean_db.sh`, `backend/app/models/**`, `db/**`) or on any push to `main`. Random PRs touching only frontend / docs / CLI surface skip the job, saving ~5 min cold-CI per such PR.

- Structural correctness is verified now via `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` + the four acceptance greps (alembic output line, alembic filter line, alembic-clean-db job line, script reference line). End-to-end validation (the job actually firing against a real PR) is **deferred to Phase 1079's close-gate**, which exercises the script against a live `docker compose up -d --build` stack as VG-01.

- The CI job is purely additive — zero existing job was modified, zero workflow file added (the alembic-clean-db job sits inside the same `ci.yml` to group its signal with the other backend gates on the PR summary). No `docker-compose*.yml` change. No env-var change. No secret added.

## Plan References

- [Plan 01 — Add alembic-clean-db job + path filter](1078-01-SUMMARY.md) (~5 min, 1 commit `40fb9112`)
- Plan 02 — Phase verification + close-gate (this file; commit to follow)

## Production-Code Files Touched

- `.github/workflows/ci.yml` — 3 edit blocks:
  - `changes` job `outputs:` (`ci.yml:22-26`) — added `alembic: ${{ steps.filter.outputs.alembic }}` (+1 line)
  - `changes` job `filters:` (`ci.yml:48-52`) — added new `alembic:` block with 4 path globs (+5 lines)
  - New `alembic-clean-db` job (`ci.yml:455-495`) — checkout + setup-uv + setup-python + uv sync + invoke script (+40 lines, including a 7-line comment header explaining the CI-01 / SEC-OBSV-03 closure context)

No other production file touched. No backend code change. No frontend code change. No env-var added. No new secret required.

## Tests Added

Zero new tests. CI-01 is a CI-wiring requirement, not a behavior-adding requirement; the test that the new job runs is the script itself (`backend/scripts/test_alembic_upgrade_clean_db.sh`), which was already shipped in v1016 Phase 1071 KNOWN-02 with its own internal pre-flight checks (docker availability, uv availability, db/Dockerfile presence, alembic.ini presence, port-in-use guard, pg_isready + `vector` extension readiness polling). The Plan 1078-02 close-gate "test" is the YAML lint (exit code 0).

## Cross-Plan Interactions

Phase 1078 has only one production-code plan (Plan 01 — `.github/workflows/ci.yml`); Plan 02 is the close-gate and touches only `.planning/` markdown + the three milestone-tracking files (`STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`). No cross-plan file overlap.

## Verification

See [1078-VERIFICATION.md](1078-VERIFICATION.md) for the full evidence trail.

**Headline:** YAML lint exits 0; all 4 acceptance greps green:

- CI-01: `alembic` output declared (`ci.yml:26`), `alembic` filter declared (`ci.yml:48`), `alembic-clean-db` job declared (`ci.yml:462`), `test_alembic_upgrade_clean_db.sh` invoked (`ci.yml:486`).
- Structural pins: `actions/checkout@v6`, `astral-sh/setup-uv@v8.1.0` (v0.10.2), `actions/setup-python@v6` (3.13), `timeout-minutes: 15`, trigger condition exactly as specified in `1078-CONTEXT.md`.

## SEC-OBSV-03 Closure

`SEC-OBSV-03` was the observational finding from v1016 Phase 1072 triage that flagged the `test_alembic_upgrade_clean_db.sh` script as built (in Phase 1071) but not wired to CI. The closure chain:

1. **v1016 Phase 1071 KNOWN-02** — Built the script (219 lines, custom PostGIS+pgvector image build + throwaway container + alembic upgrade head).
2. **v1016 Phase 1072 triage** — Observed the wiring gap, logged as SEC-OBSV-03 ("alembic-clean-DB CI wiring") and carried into v1017's `Deferred Items` in STATE.md.
3. **v1017 Phase 1078 Plan 01** — Wired the script into `ci.yml` (commit `40fb9112`).
4. **v1017 Phase 1078 Plan 02** — Closed via this VERIFICATION (and the close-gate commit that follows).

SEC-OBSV-03 is now structurally closed. The first live execution of the new job is deferred to Phase 1079's close-gate (VG-01: docker-smoke re-verify against a freshly-built `docker compose up -d --build` stack).

## Deferred / Out of Scope

Per Plan 1078-02 VERIFICATION:

- **End-to-end live CI run** — deferred to Phase 1079 close-gate. Phase 1079's VG-01 task re-verifies the script against a freshly-built `docker compose up -d --build` stack (db + api + worker), which doubles as proof that the CI job's container-build sequence is functionally equivalent. The new job's debut PR-run also lands on the `v1.5.2` close commit.
- **`actionlint`** — not installed on this host; non-blocking per Plan 02 Task 1 acceptance criteria. The YAML-syntax + structural-grep gates are sufficient.
- **Docker image build caching** — deferred per `1078-CONTEXT.md` "Deferred Ideas". First-run image build is ~2-3 min (pgvector install on top of the PostGIS base); cache-friendly on subsequent runs via uv's `cache-dependency-glob` + Docker's layer cache. Revisit if Phase 1079 flags the alembic-clean-db job as a CI bottleneck.
- **Matrix testing across multiple Postgres versions (17, 16)** — deferred per `1078-CONTEXT.md`; not needed until multi-version production support.
- **Wiring into `release.yml` for tag-push verification** — deferred per `1078-CONTEXT.md`; separate scope.

## Patterns Established

Documented at the per-plan level (`1078-01-SUMMARY.md`); summarized:

1. **Path-filtered job with push-fallback** — `needs.changes.outputs.<filter> == 'true' || github.event_name == 'push'` is the canonical shape across all backend gates in `ci.yml`. PR runs are filtered by relevance; push-to-main runs are catch-all. The alembic-clean-db job adopted this pattern verbatim.
2. **Script-owned docker lifecycle, CI-owned env** — The job's role is checkout → install uv → invoke script. The script (shipped in v1016 Phase 1071) owns docker build/run/cleanup via a trap on EXIT/INT/TERM. Env-var overrides (`ALEMBIC_TEST_DB_PORT=54399`, `ALEMBIC_TEST_TIMEOUT=90`) are passed at the job level rather than hardcoded into the script, keeping the script reusable from any cwd (per its README).
3. **Single-workflow grouping over separate workflow files** — Rejected adding a separate `.github/workflows/alembic-clean-db.yml`; the new job lives inside `ci.yml` to (a) reuse the `changes` job's path-filter machinery and (b) group all CI signals on one PR summary. Phase 1078's planner forecast this design decision.
4. **Structural closure now, e2e closure on next phase** — When a new CI job can't be exercised on its own PR (no migration-relevant paths changed; only `ci.yml` itself), structural correctness via YAML lint + acceptance greps is sufficient as the phase's `passed` verdict, with end-to-end deferred to the next phase's close-gate. `1078-CONTEXT.md` explicitly named this split.

## Next Phases

Phase 1078 → ✅ Complete. One downstream condition advances:

- **Phase 1079 — Close Gate + Hygiene** (TI-03, VG-01, HYG-01): Was gated on Phases 1075 + 1076 + 1077 + 1078. With Phase 1078 now complete, **all four predecessors are closed** and Phase 1079 is eligible. Phase 1079's TI-03 baseline planner must first disposition the 7 verification-gap failures documented in `.planning/phases/1075-conftest-test-db-lifecycle-refactor-baseline-fixes/1075-05-VERIFICATION.md` (or open Plan 1075-06 to do so) before TI-03 captures the post-v1017 pytest baseline. Phase 1079's VG-01 task exercises this same alembic-clean-db script against a live `docker compose up -d --build` stack as the e2e gate that closes the structural-only verdict from this phase.

## Self-Check: PASSED

Verified post-write:

- `.planning/phases/1078-ci-alembic-clean-db-upgrade-workflow/1078-VERIFICATION.md` — FOUND
- `.planning/phases/1078-ci-alembic-clean-db-upgrade-workflow/1078-SUMMARY.md` — FOUND (this file)
- `.planning/phases/1078-ci-alembic-clean-db-upgrade-workflow/1078-01-SUMMARY.md` — FOUND
- `.planning/STATE.md` — updated (Phase 1078 complete; completed_phases 4; percent 80)
- `.planning/ROADMAP.md` — updated (`- [x] **Phase 1078`; progress table `1/1 Complete 2026-05-21`)
- `.planning/REQUIREMENTS.md` — updated (CI-01 → Complete in traceability table; checkbox flipped to `[x]`)
- YAML lint exits 0
- All CI-01 acceptance greps green
- Plan 01 commit `40fb9112` reachable in git history

---

*Phase: 1078-ci-alembic-clean-db-upgrade-workflow*
*Completed: 2026-05-21*
