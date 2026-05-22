# Phase 1089: CI Gate + Perf Baseline + Parallel Default - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

A future developer pushing a backend test or fixture change cannot land a regression that re-breaks parallel execution — CI blocks merge, perf baseline documents the chosen worker default, and `make test` runs parallel by default.

This phase wires Phase 1088's fixture-isolation work into permanent infrastructure: a CI gate that prevents regressions, a perf baseline document for the v1020 record, and a default-test-invocation switch so developers default to the parallel path.

Phase scope:
- **CI-01** — New GitHub Actions job (working name `pytest-parallel-isolation`) added to `.github/workflows/ci.yml` running `pytest -n auto` on backend changes. Sister-shape to v1017's `alembic-clean-db` job.
- **CI-02** — Switch the default test invocation in `Makefile` (line 27 `test:`) and/or `backend/pyproject.toml` `[tool.pytest.ini_options]` `addopts` to use `-n auto`. Preserve a sequential opt-in (e.g., `make test-sequential` or `PYTEST_PARALLEL=0` env var).
- **PERF-01** — Benchmark `pytest -n 4`, `pytest -n 8`, `pytest -n auto` (16 on M-series host) wall-clock + peak DB connection count via background `pg_stat_activity` sampler. Output: `.planning/audits/PYTEST-XDIST-PERF-v1020.md` reusing v1019/v1020 spike methodology.

</domain>

<decisions>
## Implementation Decisions

### Plan structure (likely 3 plans, one per requirement)

- **Plan 1089-01** — PERF-01 baseline measurement. Spike-style: run the three `-n` benchmarks, capture sampler logs, write `.planning/audits/PYTEST-XDIST-PERF-v1020.md` with reproducibility section + recommended default. **PRECEDES CI-01 + CI-02** because the perf doc's recommended default drives CI-01's `-n` value and CI-02's `addopts`.
- **Plan 1089-02** — CI-01 wiring. Add `pytest-parallel-isolation` job to `.github/workflows/ci.yml` after the `alembic-clean-db` block (around line 459-489). Reuse the `backend-test` job's database setup pattern (lines 292-410); replace the `Run tests with coverage` step with `uv run pytest -n auto -m 'not perf'`. Triggers on push-to-main + PRs touching `backend/**` or `pyproject.toml` or `db/**`. Required check status for merge.
- **Plan 1089-03** — CI-02 default switch + close-out. Update `Makefile:27` and/or `backend/pyproject.toml:82` `addopts`. Add `make test-sequential` for explicit opt-in. Final atomic TD-13 commit flips CI-01 + CI-02 + PERF-01 in REQUIREMENTS.md + ROADMAP.md + Phase 1089 SUMMARY.

### CI-01 shape (LOCKED)

The new job mirrors `alembic-clean-db` (lines 460-489) for shape and the `backend-test` job (lines 292-410) for env/setup. Concrete steps:

1. **Job name:** `pytest-parallel-isolation` ("sister to alembic-clean-db" per REQUIREMENTS.md CI-01)
2. **Trigger:** `if: needs.changes.outputs.backend == 'true' || github.event_name == 'push'` (mirrors backend-test)
3. **Path filter:** changes-job's `backend` output already covers `backend/**`. May need to broaden to also catch `db/**` if Postgres config changes can affect xdist conn ceiling (low priority — `db/postgresql.conf` is mounted by `docker compose` not CI).
4. **Postgres setup:** Reuse `backend-test`'s `Start PostgreSQL with PostGIS + pgvector` + `Set up database extensions, roles, and schemas` blocks verbatim.
5. **Python setup:** Reuse `actions/setup-python@v6`, `astral-sh/setup-uv@v8.1.0`, `uv sync --locked --dev` blocks verbatim.
6. **Test invocation:**
   ```bash
   uv run pytest -n auto -v --tb=short -m 'not perf'
   ```
   No coverage flags (CI-01 is a regression gate, not a coverage gate — `backend-test` already does coverage).
7. **Enterprise overlay:** OPTIONAL — if including the overlay path makes the gate stricter, mirror lines 372-388. Decision: simpler is better — start without overlay; revisit if Phase 1090 HYG-02 reveals overlay-specific fixture races.
8. **Required check:** add `pytest-parallel-isolation` to the `needs:` list in any deploy / release job that currently requires `backend-test` (line 641).

### CI-02 shape (planner picks)

Two implementation choices for "switch `make test` to parallel by default":

**Option A: `Makefile` only**
```makefile
test:
	docker compose exec api uv run pytest -n auto -v --tb=short

test-sequential:
	docker compose exec api uv run pytest -v --tb=short
```

**Option B: `pyproject.toml` `addopts`**
```toml
[tool.pytest.ini_options]
addopts = "-n auto -m 'not perf'"
```
This affects ALL invocations (Makefile, IDE, direct `uv run pytest`) — broader reach but couples test invocations across docker-compose and dev environments.

**Option A is recommended** — keeps `pyproject.toml` invocation-agnostic so CI-01's explicit `-n auto` doesn't double-apply, and gives developers an explicit `test-sequential` escape hatch. The `docker compose exec api uv run pytest` shape in Makefile:28 runs `pytest` inside the api container which has the test stack already set up.

### PERF-01 methodology (LOCKED)

Mirror Phase 1087's audit doc shape (`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` Section 1). Concrete steps:

1. **Pre-flight:** stack healthy, .env.test present, drop stale per-worker DBs (Section 1 Step 1b).
2. **Sequential baseline:** `cd backend && uv run pytest tests/ 2>&1 | tee /tmp/v1020-perf-seq.log` — confirm `failed == 0`.
3. **Parallel runs (3 separate invocations):**
   ```bash
   # n=4
   (background sampler) cd backend && uv run pytest -n 4 tests/ 2>&1 | tee /tmp/v1020-perf-n4.log
   # n=8
   (background sampler) cd backend && uv run pytest -n 8 tests/ 2>&1 | tee /tmp/v1020-perf-n8.log
   # n=auto (16)
   (background sampler) cd backend && uv run pytest -n auto tests/ 2>&1 | tee /tmp/v1020-perf-nauto.log
   ```
   Drop stale per-worker DBs BEFORE each run.
4. **Capture per-run:** wall-clock, exit code, `failed`/`passed`/`error` counts, peak `pg_stat_activity` connection count from background sampler.
5. **Compare:** which `-n` value gives best speedup with `failed == 0`? PERF-01 deliverable picks the optimal value with rationale.

Expected outcome: `-n auto` (16) gives ~2-3× sequential speedup (sequential 540s → parallel ~270-350s based on Phase 1087's measurement of 269s parallel vs 540s sequential), with peak connections ≤ 30 (`max_connections` ceiling). If the cascade re-emerges at `-n auto` post-1088 due to the 4.3 residual flake-class (48 failures), document it AND recommend `-n auto` anyway as the policy default (the 48 residual is flake-class per Phase 1088 decision, deferred to HYG-02).

### TD-13 rules in effect

1. **REQ citation pinning** — CI-01 cites `.github/workflows/ci.yml:<line>` for the new job. CI-02 cites `Makefile:27` and/or `backend/pyproject.toml:82`. PERF-01 cites `.planning/audits/PYTEST-XDIST-PERF-v1020.md`.
2. **Traceability flip** — final plan (1089-03) flips CI-01 + CI-02 + PERF-01 in REQUIREMENTS.md + ROADMAP.md + Phase 1089 SUMMARY in SAME commit. Verify via `git diff-tree --no-commit-id --name-only -r HEAD`.

### Sequential baseline preservation

Every plan in Phase 1089 that touches CI or test invocation must:
1. Run `cd backend && uv run pytest tests/` and assert `failed == 0` before commit.
2. NOT modify `backend/tests/conftest.py` (Phase 1088 owns that file; v1019 + v1088 patterns preserved).

### Out of scope for this phase

- Fixture-isolation fixes (Phase 1088 — done)
- Skip audit (Phase 1090 HYG-01)
- Flake hunt (Phase 1090 HYG-02)
- Paper-trail commits (Phase 1090 HYG-03)
- Cut tags (Phase 1090 close-gate)
- Frontend changes
- Schema/migration changes
- `max_connections` bump
- `-n` worker count permanently capped below `auto` (rejected in REQUIREMENTS.md Out of Scope)

</decisions>

<code_context>
## Existing Code Insights

**CI workflow (`.github/workflows/ci.yml`):**
- Line 13 — `jobs:` start
- Line 56 — `backend-lint` job
- Line 292-410 — `backend-test` job (full reference shape)
- Line 459-489 — `alembic-clean-db` job (sister-shape reference for the new job)
- Line 641 — `needs: [backend-lint, backend-test, frontend-lint, frontend-test, security-scan]` in a downstream job; may need to add `pytest-parallel-isolation` here

**Makefile (`Makefile`):**
- Line 27 — `test:` target (currently sequential via docker exec)
- Line 30 — `test-cov:` target

**pytest config (`backend/pyproject.toml`):**
- Line 74 — `[tool.pytest.ini_options]`
- Line 82 — `addopts = "-m 'not perf'"` — DO NOT prepend `-n auto` here unless going with Option B

**Phase 1088 deliverables (preserved invariants):**
- `backend/tests/conftest.py` — NullPool branch, 5s stagger, 3 retry helpers, lifecycle race fix, WR-02 PEP-343 fix
- `backend/tests/test_fixture_isolation_v1020.py` — 11 regression pins
- Sequential pytest baseline: 3047/0/38 (must stay green)
- Parallel pytest -n auto: 76 residual (mostly flake-class; 4.3 = 48 deferred to HYG-02)

**v1017 CI-01 precedent (alembic-clean-db):**
- Same shape, smaller scope (single shell script invocation vs full pytest)
- Path filter: `if: needs.changes.outputs.alembic == 'true' || github.event_name == 'push'`
- `timeout-minutes: 15` is sufficient for a single-script run; expand to 30 for full pytest -n auto

</code_context>

<specifics>
## Specific Ideas

**Plan ordering rationale:**

1. **PERF-01 FIRST** — measure-driven default selection. Without PERF-01's data, CI-01 might pick a suboptimal `-n` value. If PERF-01 shows `-n 8` is the sweet spot (e.g., due to GitHub Actions runner having only 4 cores), CI-01 should use `-n 8` not `-n auto`. The audit doc commits before CI-01 lands.

2. **CI-01 SECOND** — wire the gate. Test the gate by intentionally failing it once (e.g., create a transient fixture-isolation bug, push the branch, observe gate blocks merge, revert). Document the test result in close-gate.

3. **CI-02 THIRD** — once the gate is green on main, switch the default. Developer ergonomics: `make test` now uses parallel.

**Plan 1089-03 (CI-02 + close) extras:**
- Add a one-line documentation note in `README.md` or `docs/development.md` (if it exists) about the parallel-default + `make test-sequential` escape hatch. Low priority; planner discretion.
- The TD-13 traceability flip is the SAME-commit invariant — REQUIREMENTS.md flips for CI-01, CI-02, PERF-01 all in one commit alongside the SUMMARY.md write.

**Local time-budget estimate:**
- Plan 1089-01 (PERF-01): ~30 min (3 runs at ~5min each parallel + sequential baseline 9 min + audit doc write ~10 min)
- Plan 1089-02 (CI-01): ~20 min (compose-only edit + local validate via `act` or just YAML lint; live CI run happens on commit-push)
- Plan 1089-03 (CI-02 + close): ~15 min (Makefile edit + final pytest + TD-13 flip)

Total Phase 1089: ~65-90 min.

**CI live-verification note:** The CI-01 gate's actual effectiveness can only be confirmed on a real push to GitHub. Plan 1089-03 should reference the first post-merge CI run as the live-verification artifact. If the milestone closes before that run completes, the close-gate Plan 1090 doc must explicitly call out the deferred verification with a `gh run watch` command for the operator to confirm post-merge.

</specifics>

<deferred>
## Deferred Ideas

- **Permanent worker-count cap below auto** — REJECTED per REQUIREMENTS.md (would mask underlying issues)
- **CI matrix across multiple `-n` values** — out of scope; PERF-01 picks ONE optimal default
- **Coverage in CI-01** — out of scope; `backend-test` already does coverage
- **GitHub Actions runner type tuning (`runs-on: ubuntu-latest-16-cores`)** — out of scope unless PERF-01 shows the default runner is severely underprovisioned for `-n auto`
- **Documentation: parallel-test playbook for developers** — defer to Phase 1090 HYG-03 paper-trail or post-milestone
- **Workflow-of-workflows (reusable workflow file)** — out of scope; inline job is simpler

</deferred>
