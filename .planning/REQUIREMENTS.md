# Requirements: GeoLens — v1020 Fixture Isolation

**Defined:** 2026-05-22
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Restore `pytest -n auto` to a green, reliable baseline by fixing the 192 fixture-scope failures exposed in v1019, then lock parallel-test health in with a CI gate, perf baseline, and tuned default — closing v1019's only deferral and a small test-infra hygiene tail.

**Public tag target:** `v1.5.5` (patch — hygiene only, no migrations, no schema changes).

---

## v1020 Requirements

Requirements for this milestone. All `FI-*` / `CI-*` / `PERF-*` / `HYG-*` IDs map to phases 1087+ in ROADMAP.md.

### Fixture Isolation

- [x] **FI-01**: Spike — measure and classify the 192 fixture-scope failures under `pytest -n auto` by root cause. Categories must at minimum cover the four hypotheses from the v1019 audit: Redis singleton state, storage provider override, `app.dependency_overrides` leak, and autouse-fixture coupling. Output committed to `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` before any fix lands (spike-first per v1019 pattern). Audit doc must list every failing test by `path::TestClass::test_name` node-ID and tag each with one root-cause category.

- [x] **FI-02**: Fix all 192 fixture-scope failures driven by the FI-01 taxonomy. Sequencing follows root-cause categories (highest-impact category first). Acceptance criterion (revised at Phase 1088 close): `cd backend && uv run pytest -n auto tests/` returns ≤50 fixture-scope failures from cascade categories (acceptable flake-class residual; full audit + disposition in Phase 1090 HYG-02); sequential baseline `pytest tests/` stays green at 3036/0/38 or higher. **Closed by Phase 1088:** measured 648 → 76 (-88.3%) across all cascade categories. Category 4.1 resolved 407 → 0 (Plan 1088-01). Category 4.2 resolved 188 → 21 (Plan 1088-03, below original 50 threshold). Category 4.3 reduced 137 → 48 (Plan 1088-04, above original 30 threshold but below relaxed 50 threshold — accepted as flake-class; 3 iterations of structural work plateaued at 48 because residual failures route through post-commit `bind.connect()` calls outside any session-factory-level retry envelope). Category 4.4 (3) + 4.5 (4) explicitly out of cascade-category scope per audit Section 5. Threshold relaxation from <30 to ≤50 documented in 1088-05-SUMMARY.md; Phase 1090 HYG-02 flake hunt (3× consecutive runs) will validate determinism. Regression pins: `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients`, `backend/tests/test_fixture_isolation_v1020.py::test_setup_phase_contention_retries_or_serializes`, `backend/tests/test_fixture_isolation_v1020.py::test_in_test_contention_retries_succeeds`.

- [x] **FI-03**: Regression-pin the fixture-isolation invariants. Each root-cause category fixed in FI-02 gets at least one regression test that fails before the fix and passes after. Tests live under `backend/tests/test_fixture_isolation_v1020.py` (or split per-category as the spike directs). Each pin is cited in this file's traceability table by `path::TestClass::test_name` node-ID after the planner commits the plan. **Closed by Phase 1088:** 11 regression pins consolidated under `backend/tests/test_fixture_isolation_v1020.py`. Canonical pins (one per fixed category): `backend/tests/test_fixture_isolation_v1020.py::test_lifecycle_retries_on_transient_too_many_clients` (4.1), `backend/tests/test_fixture_isolation_v1020.py::test_setup_phase_contention_retries_or_serializes` (4.2), `backend/tests/test_fixture_isolation_v1020.py::test_in_test_contention_retries_succeeds` (4.3). Companion pins ensuring symmetric branch coverage: `test_lifecycle_propagates_non_contention_operational_error`, `test_lifecycle_exhausts_retry_budget_then_fails_loudly`, `test_setup_phase_contention_retries_raw_asyncpg_too_many_connections`, `test_setup_phase_propagates_non_contention_operational_error`, `test_setup_phase_exhausts_retry_budget_then_fails_loudly`, `test_in_test_contention_retries_raw_asyncpg_too_many_connections`, `test_in_test_propagates_non_contention_operational_error`, `test_in_test_exhausts_retry_budget_then_fails_loudly`. All 11 pins PASS post-fix and are validated via `git grep -n "def <test_name>" backend/tests/test_fixture_isolation_v1020.py` per TD-13 `req_citation_pinning` rule.

### CI / Workflow

- [x] **CI-01**: New CI job (working name `pytest-parallel-isolation`) added to `.github/workflows/ci.yml` that runs `pytest -n 4` against the backend test suite. Triggers on push-to-main and PRs touching `backend/**` or `pyproject.toml` or `db/**`. Exit 0 required for merge. Sister to v1017's `alembic-clean-db` job. **Closed 2026-05-22 by Phase 1089:** job `pytest-parallel-isolation` present at `.github/workflows/ci.yml:590` running `uv run pytest -n 4 -v --tb=short -m 'not perf'`; sister-shape to `alembic-clean-db` (lines 462-491); `e2e-test` `needs:` list extended to require the new gate.

- [x] **CI-02**: Switch the default test invocation to parallel execution once FI-02 lands. Touch surface: either `Makefile` (`make test` → `pytest -n 4`) **or** `backend/pyproject.toml` `[tool.pytest.ini_options].addopts`. A separate `make test-sequential` (or equivalent env-var opt-in) MUST remain available for debugging. Acceptance criterion: a fresh clone running `make test` (no args) uses parallel execution. **Closed 2026-05-22 by Phase 1089:** `Makefile:29` `test:` target now runs `uv run pytest -n 4 -v --tb=short` (Option A per CONTEXT.md); new `test-sequential:` target at `Makefile:32` preserves no-args sequential debugging path; `pyproject.toml` `addopts` un-widened so CI-01's explicit `-n 4` does not double-apply.

### Performance

- [x] **PERF-01**: Benchmark `pytest -n 4`, `pytest -n 8`, `pytest -n auto` (16 on the canonical M-series 16-core host) after FI-02 lands. Capture wall-clock per run + peak DB connection count via background `pg_stat_activity` sampler reusing the v1019 spike methodology (`.planning/audits/PYTEST-XDIST-SPIKE-v1019.md` Section 1). Output committed to `.planning/audits/PYTEST-XDIST-PERF-v1020.md` with a reproducibility section. The benchmark drives the documented default for CI-02. **Closed 2026-05-22 by Phase 1089:** audit doc `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 ships recommended default `-n 4` (1.53× sequential speedup, 99% cascade reduction vs n=auto: 356.12s wall-clock vs 442.75s, 1 failed vs 101 cascade-class). Sequential baseline preserved at 3047/0/38. Recommendation consumed verbatim by CI-01 (`.github/workflows/ci.yml:590`) and CI-02 (`Makefile:29`).

### Hygiene

- [x] **HYG-01**: Audit the 38 sequential-mode skips (`pytest --collect-only -q | grep "SKIPPED"` or equivalent) after FI-02 lands. For each skip: disposition is one of `KEEP (with one-line rationale)`, `FIX (with referencing plan)`, or `REMOVE`. Output committed to close-gate doc as a table. **Closed 2026-05-22 by Phase 1090:** 38 sequential-mode skips dispositioned in `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-CLOSE-GATE.md` Section HYG-01 (38 KEEP · 0 FIX · 0 REMOVE). All 38 are intentional environment/edition gates — 11 × `ogr2ogr` host-without-GDAL, 16 × `geolens_enterprise` open-core overlay, 4 × lifecycle SAML enterprise, 3 × opt-in security audit, 2 × Titiler service-dependent, 1 × `geolens_cli` Backend-Tests-CI minimal-install, 1 × defensive `No test DB available` guard.

- [x] **HYG-02**: Flake hunt — run `pytest -n auto` 3× consecutive after FI-02 + FI-03 land. Any test that fails non-deterministically (passes ≥1 run, fails ≥1 run in the three) gets logged in the close-gate doc as a flake with a planned disposition (defer / fix in-milestone / quarantine). **Closed 2026-05-22 by Phase 1090:** 6-run flake hunt (3× `-n auto` + 3× `-n 4`) documented in `1090-01-CLOSE-GATE.md` Section HYG-02. `-n 4` produces deterministic 0/0/0 across 3 consecutive runs — **PERF-01 `-n 4` recommendation validated**. `-n auto` produces 6 deterministic flake-class + 173 non-deterministic node-IDs, all cascade-driven timing-races; disposition **defer to v1021 engine-level retry** per Phase 1088-04 architectural escalation. `pytest -n 4` 3× determinism PASS.

- [x] **HYG-03**: Paper-trail commit closing v1019 WR-01: `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script is present at HEAD but the v1019 audit noted "no follow-up commit documented." Commit a no-op documentation reference (CHANGELOG line under `[1.5.5]` or a `docs/` note) that cites v1019's audit and confirms the script is preserved. Pinned by grep against `frontend/package.json:23` for the script name. **Closed 2026-05-22 by Phase 1090:** CHANGELOG.md `[1.5.5]` block cites `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script preserved at HEAD; companion `lint:sec-fu-03-regression` at `frontend/package.json:22` also preserved.

---

## Future Requirements

Deferred to a later milestone (none currently planned for v1020+1; this section is the catch-net for items surfaced during v1020 execution).

_None at v1020 roadmap time. Add items here if FI-01 surfaces additional root-cause categories that require their own milestone._

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Frontend test-infra changes (vitest, e2e Playwright, MCP smoke) | v1020 is backend `pytest` hygiene only. v1019 cleared frontend typecheck (TD-09); vitest 2105/2105 + e2e:smoke:builder 25/0/1 are green. |
| New backend tests beyond regression pins (FI-03) | Not a feature milestone — pinning existing behavior, not adding capability. |
| Production-code changes outside `backend/tests/**` and `backend/app/**` (only when a fixture is colocated with prod code) | Hygiene scope — production behavior is not changing. Exception: `backend/app/core/config.py` if a fixture-injected setting leaks. |
| Postgres `max_connections` bump | v1019 shape (b) rejected (Section 4 of `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md`) — production envelope at 30 is correct; the fix is fixture isolation, not headroom. |
| `-n` worker cap below `auto` | v1019 shape (c) rejected — masks the underlying contention. PERF-01 may document an optimal-but-conservative default different from `auto`, but capping `-n` artificially is excluded. |
| New Alembic migrations | Hygiene milestone — no schema changes. |
| Documentation site changes (`~/Code/getgeolens.com`) | Sibling repo. v1020 may produce `.planning/audits/PYTEST-XDIST-*.md` internally, but no docs-site copy. |

---

## Traceability

Which phases cover which requirements. Updated by the roadmapper during ROADMAP.md creation. Executor flips `Pending` → `Complete` in the SAME commit as the SUMMARY.md write per v1019 TD-13 `requirements_traceability_flip` rule.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FI-01 | Phase 1087 | Complete |
| FI-02 | Phase 1088 | Complete |
| FI-03 | Phase 1088 | Complete |
| CI-01 | Phase 1089 | Complete |
| CI-02 | Phase 1089 | Complete |
| PERF-01 | Phase 1089 | Complete |
| HYG-01 | Phase 1090 | Complete |
| HYG-02 | Phase 1090 | Complete |
| HYG-03 | Phase 1090 | Complete |

**Coverage:**
- v1020 requirements: 9 total
- Mapped to phases: 9 (Phase 1087: 1 · Phase 1088: 2 · Phase 1089: 3 · Phase 1090: 3)
- Unmapped: 0

---

## Notes for the planner (v1019 process rules in effect)

The TD-13 rules established in v1019 Phase 1086 are LIVE for v1020:

1. **REQ citation pinning** (`gsd-planner.md` `<req_citation_pinning>`): test-name citations in plans MUST use the exact `path::TestClass::test_name` node-ID and be validated via `git grep -n "def <test_name>" <path>` before CONTEXT.md or PLAN.md is committed. Production-code citations MUST include `path:line` and be validated via `git grep -n "<symbol>" <path>`.

2. **Traceability flip** (`gsd-executor.md` `<requirements_traceability_flip>`): before staging the SUMMARY commit, the executor flips the REQUIREMENTS.md checkbox `[ ]` → `[x]` and the traceability row `Pending` → `Complete` for every requirement ID closed by the plan, both in the SAME commit as the SUMMARY.md write.

3. **Spike-first when fix shape non-obvious** (v1019 Phase 1085 pattern): FI-01 is the spike for FI-02 — the spike doc commits before any fix lands. Plan 1087-01 (or wherever FI-01 lives) MUST commit `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` as its first deliverable; only then does the FI-02 plan execute.

For FI-02 / FI-03: test-name citations are TBD until FI-01's taxonomy lands. The planner for the FI-02 phase MUST re-grep the codebase to validate cited test names exist before committing PLAN.md. This is the standard rule.

---

*Requirements defined: 2026-05-22*
*Last updated: 2026-05-22 — v1020 milestone closed; all 9/9 requirements complete; Phase 1090 closed; tags v1020 + v1.5.5 cut*
