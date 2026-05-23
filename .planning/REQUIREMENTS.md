# Requirements: GeoLens — v1021 Docker Rebuild Sweep + Engine-level Retry

**Defined:** 2026-05-23
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Close the operational findings surfaced by the 2026-05-23 docker-rebuild + canonical-seed sweep (quick task `260523-at1`, SUMMARY at `.planning/quick/260523-at1-rebuild-the-docker-containers-and-import/260523-at1-SUMMARY.md`, commit `e9817603`) and retire v1020's engine-level retry carry-forward. Six requirements: one async-context bug in the ingest worker, one seed-script reconciliation gap, one routing/hostname-leak fix that closes two adjacent symptoms, two infra hygiene items (one fix + one explicit ACCEPT), and the v1020-deferred engine-level retry envelope for `pytest -n auto`.

**Public tag target:** `v1.5.6` (patch — bug fixes + ops hygiene; no user-facing features, no API contract changes, no migrations beyond what the docker-compose+entrypoint fixes touch).

---

## v1021 Requirements

Requirements for this milestone. All `INGEST-*` / `OPS-*` / `ROUTE-*` / `INFRA-*` / `TEST-*` IDs map to phases 1091+ in ROADMAP.md.

### Ingestion

- [ ] **INGEST-01**: Fix the `urban_areas_landscan_10m` quicklook generation failure that surfaces as `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` in `app/processing/ingest/tasks_common.py` during the post-commit quicklook phase. Reproducible: running `python3 scripts/seed-natural-earth.py --base-url http://localhost:8080 --username admin --password admin` against a clean stack reliably trips the failure on `ne_10m_urban_areas_landscan.zip` (1/109 datasets); data lands cleanly (`record_status=published`, `feature_count=6018`, valid `extent_bbox`) but the ingest job row records `status=failed` and the dataset has no quicklook. Acceptance criteria: (a) a fresh `scripts/seed-natural-earth.py` run against a `docker compose down -v && up -d --build` stack produces zero `status=failed` rows in `/api/admin/jobs/`; (b) `urban_areas_landscan_10m` has a non-null quicklook URI after seed completes; (c) a regression test in `backend/tests/test_quicklook_async_context.py` (or equivalent) reproduces the original `MissingGreenlet` shape under the broken code path and passes under the fix. Spike-first: a short investigation deliverable identifies the exact line(s) that cross the async-context boundary before the fix lands.

### Operations

- [ ] **OPS-01**: Add post-loop reconciliation to `scripts/seed-natural-earth.py` so the seed script's "Succeeded: N, Failed: M" summary cannot disagree with the persisted worker job-row status. After the polling loop completes, the script must `GET /api/admin/jobs/?status=failed` (scoped to job IDs from this run — by `started_at` window or job_id capture during enqueue) and report any failed jobs in the Import Summary block with their `source_filename`, `dataset_id`, and `error_message`. Acceptance criteria: (a) when INGEST-01 is regression-pinned by re-introducing the bug, `seed-natural-earth.py` exits non-zero AND prints the failed-job table; (b) when no failures exist, the script preserves its current exit-zero + green-summary behavior; (c) the reconciliation is unit-tested or covered by an integration test that stubs `/api/admin/jobs/` with a known-failed response.

### Routing

- [ ] **ROUTE-01**: Stop the 307 trailing-slash redirect from leaking the internal docker-compose hostname `http://api:8000` in the `Location` header. Symptom surface is broader than the documented `/collections/datasets` exception in `MEMORY.md`: `GET http://localhost:8080/api/collections/` and `POST http://localhost:8080/api/auth/login/` both return `HTTP 307` with `Location: http://api:8000/...`, exposing the internal hostname to any external client (curl, SDKs, external integrations). Root cause is FastAPI's default `redirect_slashes=True` combined with the Vite dev-proxy passing the `Location` header through unmodified. Acceptance criteria: (a) `curl -sI http://localhost:8080/api/collections/` returns either `200` directly OR a 307 whose `Location` is rewritten to `http://localhost:8080/...` (no `api:8000` leak); (b) same for `/api/auth/login/`; (c) the documented `/collections/datasets` no-slash exception is either eliminated (route accepts both shapes) or explicitly preserved with a regression test pinning the chosen behavior; (d) `MEMORY.md` is updated to reflect the post-fix invariant (current note is stale); (e) a backend test in `backend/tests/test_redirect_slashes.py` (or equivalent) pins the no-leak behavior. Closes Issues 2 + 5 from quick task `260523-at1`.

### Infrastructure

- [ ] **INFRA-01**: Eliminate the double `alembic upgrade head` invocation in the `migrate` service. Today the service runs `command: sh -c "uv run --no-dev alembic upgrade head"` AND inherits `backend/scripts/api-entrypoint.sh:62-68` which also runs `uv run --no-dev alembic upgrade head` as a safety-net — both fire on every startup, doubling alembic latency. Acceptance criteria: (a) `docker compose logs --no-color migrate` after `docker compose down -v && up -d --build` shows exactly ONE `alembic.runtime.migration` block; (b) the chosen approach (override `entrypoint:` on the migrate service OR detect "I'm migrate" in `api-entrypoint.sh` and skip the safety-net) is documented inline with a one-line comment; (c) `api` service entrypoint still runs the safety-net (the safety-net's value is for `api`/`worker` cold start when `migrate` failed silently — that protection must remain).

- [ ] **INFRA-02**: ACCEPT — formally accept the `db` image's `--platform=linux/amd64` pin on `./db/Dockerfile:1` so the build warning `FromPlatformFlagConstDisallowed` and the runtime warning `The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8)` are no longer surprises on Apple Silicon hosts. Acceptance criteria: (a) `./db/Dockerfile` carries an inline comment on line 1 (or immediately above) explaining the pin rationale (most likely `pgvector` build reproducibility against the postgis/postgis:17-3.5 base) and a TODO link to the future multi-arch path; (b) one project-level doc (CHANGELOG `[1.5.6]` block, or a section in `./db/README.md` if one exists, or `MEMORY.md`) carries the operator-facing rationale; (c) `docker compose up -d --build` still warns but the warning is now expected behavior pinned by a comment.

### Testing

- [ ] **TEST-01**: Land the engine-level retry envelope for `pytest -n auto` that v1020 deferred. Phase 1088-04 produced the architectural escalation REPORT (not auto-applied) at `.planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md`: the 48 residual failures + 173 non-deterministic node-IDs in HYG-02's 16-worker flake hunt all fire AFTER `await session.commit()` releases the warm-up connection — outside any session-factory-level retry envelope. The fix lives at the engine layer (sqlalchemy `create_async_engine` pool configuration + a retry-on-`OperationalError` wrapper around `engine.connect()` / `engine.dispose()` calls that surface raw asyncpg `TooManyConnectionsError` / `CannotConnectNowError`). Acceptance criteria: (a) `cd backend && uv run pytest -n auto tests/` produces ≤10 failed tests across 3 consecutive runs (down from v1020's HYG-02 baseline of 48 deterministic + 173 non-deterministic = up to 221); (b) `-n 4` sequential 3047/0/38 baseline preserved (no regression on the operationally-default CI gate); (c) at least one regression pin in `backend/tests/test_fixture_isolation_v1020.py` (or a new `test_engine_retry_envelope.py`) covers the engine-level retry shape under the same `TooManyConnectionsError` / `CannotConnectNowError` injection model that v1020 already uses for the fixture-layer pins; (d) PERF-01 default `-n 4` stays unchanged in `Makefile:29` and `.github/workflows/ci.yml:493-595` — the engine envelope is additive defense, not a replacement.

---

## Future Requirements

Deferred to a later milestone. Catch-net for items that surface during v1021 execution.

_None at roadmap time. If INGEST-01's spike surfaces an architectural issue larger than a single async-context fix (e.g., a systemic boundary between commit-phase and quicklook-phase that warrants a phase of its own), promote that to a v1022+ item rather than blooming v1021 scope._

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Other failed ingest jobs (none observed at v1021 start beyond `urban_areas_landscan_10m`) | v1021 closes the surfaced failure shape; new failures that emerge under the same MissingGreenlet code path will be regression-pinned by INGEST-01's test, but discovery of *different* failure shapes is a future milestone. |
| Frontend redirect_slashes UX (axios/fetch handling of 307) | Backend-side hostname leak is the user-visible bug. Frontend already follows redirects transparently. |
| Vite dev-proxy rewrite for non-API routes | ROUTE-01 fix is at the FastAPI layer (preferred) or at the proxy `Location`-rewrite layer (fallback) — either closes the bug. Other proxy paths are not affected. |
| Multi-arch `db` image build pipeline | INFRA-02 is ACCEPT-only with a future TODO. Building multi-arch postgis+pgvector requires CI infrastructure work outside v1021 scope (cross-build matrix, image registry tagging, signature distribution). |
| Production-code changes to `app/processing/ingest/tasks_common.py` beyond the MissingGreenlet fix | INGEST-01 is targeted at the async-context-boundary bug only. Refactoring the broader ingest pipeline is out of scope. |
| Seed-script flag/CLI changes beyond OPS-01's reconciliation | `seed-natural-earth.py`'s argument shape stays compatible with existing operator commands. OPS-01 adds reconciliation output; it does not change the invocation contract. |
| Postgres `max_connections` bump or `-n` worker cap below `auto` | Restated from v1020 Out of Scope. Production envelope at 30 is correct; the fix is engine-layer retry, not headroom or artificial concurrency cap. |
| Engine-level retry for application code (the FastAPI request path) | TEST-01 is scoped to the test-fixture engine, not the app engine. The app engine's connection pool sizing is a separate concern with different acceptance criteria (request latency, not test determinism). |
| Documentation site changes (`~/Code/getgeolens.com`) | Sibling repo. v1021 may produce internal `.planning/` audit docs but no docs-site copy. |

---

## Traceability

Which phases cover which requirements. Updated by the roadmapper during ROADMAP.md creation. Executor flips `Pending` → `Complete` in the SAME commit as the SUMMARY.md write per v1019 TD-13 `requirements_traceability_flip` rule.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1091 | Pending |
| OPS-01 | Phase 1091 | Pending |
| ROUTE-01 | Phase 1092 | Pending |
| INFRA-01 | Phase 1092 | Pending |
| INFRA-02 | Phase 1092 | Pending |
| TEST-01 | Phase 1093 | Pending |
