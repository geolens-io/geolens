# Phase 1087: Fixture-Isolation Spike (Taxonomy) - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Developer can read `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` and see every one of the 192 failures classified by root cause, with sufficient evidence to drive Phase 1088 sequencing.

This is a **spike-first** phase per v1019 Phase 1085 precedent. Phase 1087 produces an audit doc only — **no production-code changes, no test-code changes, no `backend/tests/conftest.py` edits**. The deliverable is the classification document committed to the repo before any Phase 1088 fix code can land.

Phase scope:
- Reproduce the 192-failure baseline under `pytest -n auto` against the post-v1019 HEAD (commit `02cb25db` baseline, sequential `3036/0/38`).
- For each failure, capture: exact `path::TestClass::test_name` node-ID, primary error class (e.g., `KeyError`, `AssertionError`, `IntegrityError`, asyncpg `DuplicateColumnError`, missing key in `app.dependency_overrides`, etc.), and root-cause category.
- Define a taxonomy that at minimum names the four v1019-hypothesis categories: **Redis singleton state**, **storage provider override**, **`app.dependency_overrides` leak**, **autouse-fixture coupling**. Add additional categories if measurement reveals them.
- Recommend Phase 1088 fix sequencing (highest-impact category first by failure count).

Sequential pytest baseline that MUST stay green throughout v1020: **3036/0/38** (v1019 close-gate, 532s).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`.

Strong guidance from REQUIREMENTS.md (FI-01) + the v1019 spike-doc precedent (`.planning/audits/PYTEST-XDIST-SPIKE-v1019.md`):

1. **Measurement methodology** — Use a background `pg_stat_activity` sampler in a separate subshell + capture `/tmp/v1020-xdist-fixture-spike.log` from a `pytest -n auto tests/` run. Mirror v1019 Section 1's exact shape so the reproducibility section is one-to-one.

2. **Failure extraction** — Use pytest's JUnit XML output (`--junitxml=/tmp/v1020-junit.xml`) or `-rE -rf` summary + parse, since `grep` against the human-readable log misses test parametrizations. Each failure must be cited with full `path::TestClass::test_name` (including `[parametrize-id]` if applicable).

3. **Category assignment** — The four named categories are the v1019 audit's hypothesis set:
   - **Redis singleton state**: tests that fail when another worker mutates the global Redis cache key (e.g., `cache.clear()` in a session-scoped fixture)
   - **storage provider override**: tests that fail when `app.dependency_overrides[get_storage_provider]` is cleared/replaced by another worker
   - **`app.dependency_overrides` leak**: tests that fail when any `app.dependency_overrides[get_db_X]` or `get_current_user_X` is mutated by another worker mid-test
   - **autouse-fixture coupling**: tests that fail when an autouse session/module-scoped fixture's side effects depend on per-worker isolation that isn't preserved
   
   If measurement reveals additional patterns (e.g., file-system race in `worker_data_dir`, structlog contextvar leak, env-var mutation), add new categories — do not force-fit into the four.

4. **Audit doc structure** — One Markdown file at `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` with sections:
   - **Section 1 — Methodology** (mirrors v1019 spike Section 1; reproducibility steps)
   - **Section 2 — Measured numbers** (total failures, per-category breakdown, worker count, max_connections, sequential baseline confirmation)
   - **Section 3 — Failure inventory** (one table row per failing node-ID, with `category | error_class | snippet`)
   - **Section 4 — Per-category root-cause analysis** (one subsection per category; minimal Python diff sketch of the offending fixture or override pattern; impact count)
   - **Section 5 — Phase 1088 fix sequencing recommendation** (ordered category list with rationale)

5. **Repro determinism** — Pick a known-good seed (e.g., `pytest --randomly-seed=0` if `pytest-randomly` is installed; otherwise call out the limitation). The spike SHOULD be reproducible exit-code-equal across two consecutive runs to ensure the 192 number is stable.

6. **Container-state hygiene** — Stack must be in a known state before measurement: `docker compose ps db` healthy on `127.0.0.1:5434`, `.env.test` present, no stale per-worker test DBs from a previous run. Use the v1019 spike's cleanup commands as the starting point.

7. **Out of scope for this phase** — No fix attempts. No regression tests. No conftest edits. No fixture refactoring. The Phase 1088 plan will consume this audit's Section 5 sequencing.

### REQ Citation Pinning (TD-13 rule from v1019)
This phase MUST follow `<req_citation_pinning>` in `gsd-planner.md`:
- The audit doc cites failing tests by exact `path::TestClass::test_name` node-IDs.
- The Phase 1087 PLAN.md will validate citations via `git grep` only if the audit cites currently-existing tests (which it should — these are the 192 already-existing failures).
- The audit itself is a measurement artifact, not a plan — but its node-ID format is consumed by Phase 1088's planner, so the plan-phase commit MUST grep-validate each cited test exists before committing PLAN.md.

### Traceability Flip (TD-13 rule from v1019)
The Phase 1087 executor MUST flip REQUIREMENTS.md FI-01 from `[ ]` → `[x]` and traceability row `Pending` → `Complete` in the SAME commit as the SUMMARY.md write per `<requirements_traceability_flip>` in `gsd-executor.md`.

</decisions>

<code_context>
## Existing Code Insights

**v1019 spike artifact (reference shape for v1020 spike):**
- `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` — same milestone, same methodology, different question (asyncpg cascade vs fixture isolation). Reuse the measurement scaffolding 1:1 where applicable.

**Test infrastructure entry points:**
- `backend/tests/conftest.py` — top-level pytest config. Defines `client` fixture, per-worker test-DB lifecycle (post-v1019: NullPool + 5s startup stagger). Worker ID via `PYTEST_XDIST_WORKER` env.
- `backend/tests/` — full backend test suite (~3000 tests total; 3036 passing sequential, 0 failing, 38 skipped at v1019 close).
- `backend/pyproject.toml` — `[tool.pytest.ini_options]` + dev-deps including `pytest-xdist>=3.6.0`.
- `db/postgresql.conf` — `max_connections=30` (PERF-05 envelope; do not bump per OUT OF SCOPE).
- `.env.test` — test environment variables consumed during `pytest -n auto` invocation.

**Known suspicious fixture sources (from v1019 audit hypothesis set):**
- Redis cache singletons in `backend/app/core/cache.py` (if present) — surfaced any time `cache.clear()` is called from an autouse fixture.
- `app.dependency_overrides` mutation patterns — `backend/app/main.py` boots a FastAPI app; tests using `TestClient` typically override `get_db`, `get_current_user`, `get_storage_provider`, etc. Concurrent overrides in different sessions on the same `app` instance leak.
- Storage provider in `backend/app/processing/storage/` — `StorageProvider` Protocol implementation; session-scoped fixtures may keep a worker-local provider while another worker mutates the global default.
- `worker_data_dir` or similar per-worker dirs — file-system races if not properly per-worker-isolated.

**v1019 pattern reinforcement (do not regress these):**
- NullPool branch in `backend/tests/conftest.py` (`_make_test_async_engine` helper, commit `ea24168c`) for xdist async engines.
- 5s startup stagger in `backend/tests/conftest.py` (`_SETUP_STAGGER_SECONDS=5.0`, commit `1aaf81c5`).
- Sequential pytest 3036/0/38 baseline (532s).

**TD-13 retro reference:**
- `.planning/retros/v1019-process.md` — three incident narratives that motivated the REQ-citation-pinning + executor-traceability-flip rules.

</code_context>

<specifics>
## Specific Ideas

**Deliverables (commit-equivalent units of work):**

1. **Spike pre-flight check** — confirm `docker compose ps db` healthy; `.env.test` present; no stale per-worker DBs from previous runs; HEAD is at v1019 close (`git rev-parse HEAD` = `02cb25db` or descendant).

2. **Sequential baseline re-verify** — `cd backend && uv run pytest tests/` returns 3036/0/38 (or current — whatever's at HEAD). If different, capture the new sequential baseline in Section 2 of the audit.

3. **Parallel measurement** — `cd backend && uv run pytest -n auto --junitxml=/tmp/v1020-junit.xml tests/ 2>&1 | tee /tmp/v1020-xdist-fixture-spike.log`. Capture wall-clock, total failures, sequential baseline preservation under parallel mode for any non-fixture-isolation reasons (sanity check).

4. **Failure extraction** — parse `/tmp/v1020-junit.xml` for `<testcase>` elements with child `<failure>` or `<error>` to extract every failing node-ID + error class. Write a small Python helper or `xmllint` one-liner; commit the helper script if reusable.

5. **Categorization** — for each failure, read the test source + the offending fixture (via `pytest --setup-show` or stack-trace inspection) and assign one root-cause category. Categories list is open — at minimum the four hypothesized; add as discovered.

6. **Audit doc write** — `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` with the 5 sections from Implementation Decisions #4. Include reproducibility commands. Include per-category Python-diff sketches (1-3 lines each — illustrative, not prescriptive).

7. **Phase 1087 SUMMARY.md** — concise summary referencing the audit doc + the per-category counts; flips FI-01 in REQUIREMENTS.md in the SAME commit per TD-13 traceability rule.

**Plans this phase should produce (planner's discretion — likely 1-2 plans):**
- Plan 1087-01 — Spike measurement + categorization + audit doc commit (single atomic plan; one commit per deliverable section, final commit lands the audit doc and SUMMARY.md together).
- Optional Plan 1087-02 — only if measurement reveals an obvious quick-win (e.g., a single fixture causing 60+ of the 192 failures that could be fixed in <30 min). Otherwise, do NOT introduce code changes in this phase — keep the spike pure.

</specifics>

<deferred>
## Deferred Ideas

- **Quick-win fixes** — even if Section 5 identifies a single fixture causing 60+ failures, the fix lands in Phase 1088 unless it's a literal one-line obvious bug. Spike-first discipline.
- **Test deletion** — if any of the 192 are flakes that should be removed entirely (not isolated), defer that disposition to Phase 1090 HYG-01 (skip audit) where each skip/flake gets a `KEEP/FIX/REMOVE` decision with rationale.
- **Worker-count tuning** — defer to Phase 1089 PERF-01.
- **`max_connections` bump** — OUT OF SCOPE for v1020 entirely (rejected in v1019 spike Section 4 / REQUIREMENTS.md Out of Scope).

</deferred>
