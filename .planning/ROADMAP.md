# Roadmap: v1021 Docker Rebuild Sweep + Engine-level Retry

**Milestone:** v1021
**Public tag target:** `v1.5.6` (patch — bug fixes + ops hygiene; no API/schema changes)
**Local tag target:** `v1021`
**Phases:** 1091–1093 (continues from v1020 1087–1090)
**Plans:** TBD (refined during `/gsd:plan-phase`)
**Requirements:** 6 (INGEST-01 + OPS-01 + ROUTE-01 + INFRA-01 + INFRA-02 + TEST-01)
**Granularity:** Mid (operational-findings shape — ingest correctness → routing/infra hygiene → engine-level retry)
**Coverage:** 6/6 requirements mapped — no orphans
**Source of scope:** `.planning/quick/260523-at1-rebuild-the-docker-containers-and-import/260523-at1-SUMMARY.md` (commit `e9817603`) + v1020 carry-forward (engine-level retry envelope per Phase 1088-04 architectural escalation REPORT at `.planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md`).

---

## Phases

- [x] **Phase 1091: Ingest Correctness Sweep** — Fix the `urban_areas_landscan_10m` quicklook `MissingGreenlet` async-context bug AND add post-loop reconciliation to `scripts/seed-natural-earth.py` so the seed's "Succeeded: N" summary cannot disagree with `/api/admin/jobs/` status. Spike-first per v1019/v1020 pattern.
- [ ] **Phase 1092: Routing + Infra Hygiene** — Stop the 307 trailing-slash redirects from leaking the internal `http://api:8000` hostname (closes `/api/collections/` + `/api/auth/login/` + revisits the documented `/collections/datasets` exception); eliminate the double alembic `upgrade head` invocation in the `migrate` service; formally ACCEPT the `db` image `--platform=linux/amd64` pin with rationale doc.
- [ ] **Phase 1093: Engine-level Retry Envelope** — Land the v1020-deferred engine-level retry envelope for `pytest -n auto` so the 48 deterministic + 173 non-deterministic node-IDs flagged in v1020 HYG-02 stop being a developer-environment papercut. Targets the test-fixture engine only (app-engine path is out of scope per REQUIREMENTS.md `Out of Scope`).

---

## Phase Details

### Phase 1091: Ingest Correctness Sweep
**Goal:** An operator running `docker compose down -v && up -d --build` and then `python3 scripts/seed-natural-earth.py --base-url http://localhost:8080 --username admin --password admin` sees zero `status=failed` rows in `/api/admin/jobs/` AND any failures that *do* appear in the future cannot escape the seed script's exit-print summary.
**Depends on:** Nothing (first phase of v1021; sequential pytest baseline `3047/0/38` from v1020 close-gate is the start state)
**Requirements:** INGEST-01, OPS-01
**Success Criteria** (what must be TRUE):
  1. A fresh `scripts/seed-natural-earth.py` run against a `docker compose down -v && up -d --build` stack produces zero `status=failed` rows in `/api/admin/jobs/` (acceptance criterion (a) from INGEST-01).
  2. The `urban_areas_landscan_10m` dataset has a non-null quicklook URI after a clean seed completes (acceptance criterion (b) from INGEST-01).
  3. A regression test in `backend/tests/test_quicklook_async_context.py` (or equivalent) reproduces the original `MissingGreenlet: greenlet_spawn has not been called` shape under the pre-fix code path and passes under the fix (acceptance criterion (c) from INGEST-01); node-ID pinned in REQUIREMENTS.md traceability table per TD-13 `req_citation_pinning` rule.
  4. A short spike deliverable (`.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` or inline in `1091-01-SUMMARY.md`) identifies the exact line(s) in `app/processing/ingest/tasks_common.py` that cross the async-context boundary BEFORE the fix lands — spike-first per v1019/v1020 pattern.
  5. When INGEST-01 is regression-pinned by re-introducing the bug, `scripts/seed-natural-earth.py` exits non-zero AND prints a failed-job table with `source_filename`, `dataset_id`, and `error_message` (acceptance criterion (a) from OPS-01); when no failures exist, the script preserves its current exit-zero + green-summary behavior (acceptance criterion (b)); reconciliation logic is covered by unit test or integration test that stubs `/api/admin/jobs/` (acceptance criterion (c)).
**Plans:** 3 plans
- [x] 1091-01-PLAN.md — Spike: locate the MissingGreenlet async-context boundary (audit doc, no code edits)
- [x] 1091-02-PLAN.md — Apply the audit-proposed fix to tasks_common.py + regression test + live docker-rebuild verification
- [x] 1091-03-PLAN.md — OPS-01 reconciliation in seed-natural-earth.py + 4 unit tests + phase close

### Phase 1092: Routing + Infra Hygiene
**Goal:** A reader of `MEMORY.md` can see one consistent rule for trailing-slash behavior across all `/api/*` routes (no internal-hostname leak in any 307 `Location` header), and an operator running `docker compose down -v && up -d --build` sees exactly one alembic upgrade block in `migrate` logs plus a documented (no longer surprising) `--platform=linux/amd64` warning on the `db` image.
**Depends on:** Phase 1091 (sequencing; no hard code-level dependency, but routing fix is verified after `migrate` runs clean)
**Requirements:** ROUTE-01, INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):
  1. `curl -sI http://localhost:8080/api/collections/` returns either `HTTP 200` directly OR a `307` whose `Location` header is rewritten to `http://localhost:8080/...` (no `api:8000` leak); same for `POST http://localhost:8080/api/auth/login/` (acceptance criteria (a) + (b) from ROUTE-01). The documented `/collections/datasets` no-slash exception is either eliminated (route accepts both shapes) or explicitly preserved with a regression test pinning the chosen behavior (acceptance criterion (c)); `MEMORY.md` updated to reflect the post-fix invariant (acceptance criterion (d)); backend test in `backend/tests/test_redirect_slashes.py` pins the no-leak behavior (acceptance criterion (e)).
  2. `docker compose logs --no-color migrate` after `docker compose down -v && up -d --build` shows exactly ONE `alembic.runtime.migration` block — eliminating today's double-invocation in the `migrate` service (acceptance criterion (a) from INFRA-01). Chosen approach (override `entrypoint:` on the migrate service OR detect "I'm migrate" in `api-entrypoint.sh` and skip the safety-net) is documented inline with a one-line comment (acceptance criterion (b)). The `api` service entrypoint still runs the safety-net for `api`/`worker` cold-start protection (acceptance criterion (c)).
  3. `./db/Dockerfile` carries an inline comment on line 1 (or immediately above) explaining the `--platform=linux/amd64` pin rationale (pgvector build reproducibility against `postgis/postgis:17-3.5`) and a TODO link to the future multi-arch path (acceptance criterion (a) from INFRA-02).
  4. One project-level doc (CHANGELOG `[1.5.6]` block, `./db/README.md`, or `MEMORY.md`) carries the operator-facing rationale for the `db` image platform pin (acceptance criterion (b) from INFRA-02); `docker compose up -d --build` still warns but the warning is now expected behavior pinned by a comment (acceptance criterion (c)).
  5. Sequential pytest baseline `3047/0/38` preserved at phase close (HARD INVARIANT — non-negotiable per v1020 close-gate).
**Plans:** TBD

### Phase 1093: Engine-level Retry Envelope
**Goal:** A developer running `cd backend && uv run pytest -n auto tests/` on a canonical 16-core M-series host sees ≤10 failed tests across 3 consecutive runs (down from v1020's HYG-02 baseline of 48 deterministic + 173 non-deterministic = up to 221), while the `-n 4` CI default and sequential baseline stay green.
**Depends on:** Phase 1092 (sequencing; engine-level retry work is independent in code but lands after the routing/infra hygiene work to keep the close-gate matrix coherent)
**Requirements:** TEST-01
**Success Criteria** (what must be TRUE):
  1. `cd backend && uv run pytest -n auto tests/` produces ≤10 failed tests across 3 consecutive runs (down from v1020's HYG-02 baseline of up to 221) (acceptance criterion (a) from TEST-01).
  2. Sequential `-n 4` baseline preserved at `3047/0/38` — no regression on the operationally-default CI gate (acceptance criterion (b) from TEST-01).
  3. At least one regression pin in `backend/tests/test_fixture_isolation_v1020.py` (or a new `test_engine_retry_envelope.py`) covers the engine-level retry shape under the same `TooManyConnectionsError` / `CannotConnectNowError` injection model that v1020 already uses for the fixture-layer pins (acceptance criterion (c) from TEST-01); node-ID(s) pinned in REQUIREMENTS.md traceability table per TD-13 `req_citation_pinning` rule.
  4. PERF-01 default `-n 4` stays unchanged in `Makefile:29` and `.github/workflows/ci.yml:493-595` — the engine envelope is additive defense, not a replacement (acceptance criterion (d) from TEST-01).
  5. Close-gate matrix green at v1021 tag-cut: sequential pytest `3047/0/38`, `pytest -n 4` `3047/0/0/38`, frontend typecheck exit 0, vitest 2105/2105, e2e:smoke:builder 25/0/1, live Playwright MCP 5/5 surfaces clean. Tags `v1021` (local) + `v1.5.6` (public) both deref to the close commit.
**Plans:** TBD

---

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1091. Ingest Correctness Sweep | 3/3 | Complete | 2026-05-23 |
| 1092. Routing + Infra Hygiene | 0/TBD | Not started | - |
| 1093. Engine-level Retry Envelope | 0/TBD | Not started | - |

**Total:** 0/TBD plans complete across 3 phases.

---

## Coverage

| Requirement | Phase | Notes |
|-------------|-------|-------|
| INGEST-01 | Phase 1091 | `MissingGreenlet` async-context fix in `app/processing/ingest/tasks_common.py` quicklook commit-phase; spike-first per v1019/v1020 |
| OPS-01 | Phase 1091 | Post-loop reconciliation against `/api/admin/jobs/?status=failed` in `scripts/seed-natural-earth.py`; regression test needs INGEST-01's `MissingGreenlet` shape to verify |
| ROUTE-01 | Phase 1092 | 307 internal-hostname leak — closes `/api/collections/` + `/api/auth/login/` + revisits `/collections/datasets` exception; MEMORY.md update |
| INFRA-01 | Phase 1092 | Double alembic `upgrade head` in `migrate` service deduped (entrypoint override OR safety-net skip) |
| INFRA-02 | Phase 1092 | ACCEPT `db` image `--platform=linux/amd64` pin with inline rationale comment + project-level doc (multi-arch is future TODO only) |
| TEST-01 | Phase 1093 | Engine-level retry envelope for `pytest -n auto` (v1020 carry-forward per Phase 1088-04 architectural escalation REPORT); test-fixture engine only, NOT app engine |

**6/6 requirements mapped — no orphans, no duplicates.**

---

## Project Conventions (LIVE from v1019 TD-13)

- **REQ citation pinning** — planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit. Applies to INGEST-01 (`test_quicklook_async_context.py`), OPS-01 (seed-script reconciliation unit/integration test), ROUTE-01 (`test_redirect_slashes.py`), and TEST-01 (engine-retry regression pin). REQUIREMENTS.md traceability table will cite exact node-IDs at plan close.
- **Traceability flip** — executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in the SAME commit as the SUMMARY.md write. ROADMAP.md phase-row update lands in the SAME commit per TD-13 atomic-4-file invariant established across v1019/v1020 (7 phases of clean track record).

---

## Out-of-Scope Reaffirmations (from REQUIREMENTS.md)

| Item | Reason |
|------|--------|
| Postgres `max_connections` bump | Production envelope at 30 is correct; the fix is engine-layer retry, not headroom (restated from v1020). |
| Artificial `-n` cap below `auto` (e.g., capping to 4 to dodge the fix) | Masks the underlying contention; PERF-01 may document an optimal-but-conservative CI default different from `auto`, but the engine retry envelope still must close the residual for max-parallelism dev envs. |
| Engine-level retry for application code (FastAPI request path) | TEST-01 is scoped to the test-fixture engine ONLY. App engine connection pool sizing has different acceptance criteria (request latency, not test determinism). |
| Multi-arch `db` image build pipeline | INFRA-02 is ACCEPT-only with a future TODO. Cross-build matrix + image registry tagging + signature distribution is outside v1021. |
| Other failed ingest jobs (none observed beyond `urban_areas_landscan_10m` at v1021 start) | v1021 closes the surfaced failure shape; new failures under the same `MissingGreenlet` code path get caught by INGEST-01's regression test, but discovery of *different* failure shapes is a future milestone. |
| Production-code refactor of `app/processing/ingest/tasks_common.py` beyond the `MissingGreenlet` fix | INGEST-01 is targeted at the async-context-boundary bug only. Broader ingest pipeline refactor is out of scope. |
| Frontend redirect_slashes UX (axios/fetch handling of 307) | Backend hostname leak is the user-visible bug. Frontend follows redirects transparently. |
| Documentation site changes (`~/Code/getgeolens.com`) | Sibling repo. v1021 may produce internal `.planning/` audit docs but no docs-site copy. |

---

## Sequencing Rationale

1. **Phase 1091 first (Ingest Correctness):** OPS-01's reconciliation regression test needs the `MissingGreenlet` shape from INGEST-01 to verify the seed script surfaces failures — natural intra-phase dependency. Spike-first per v1019/v1020 pattern (audit doc or inline SUMMARY identifies the exact async-context boundary BEFORE the fix lands).
2. **Phase 1092 second (Routing + Infra Hygiene):** Three hygiene items that share the `docker compose down -v && up -d --build` verification surface — running them after Phase 1091's ingest-correctness fix keeps each phase's verification matrix focused. ROUTE-01 is the largest item; INFRA-01 + INFRA-02 are bundled into the same docker-compose change-set to minimize rebuild noise.
3. **Phase 1093 last (Engine-level Retry):** Architecturally distinct from Phases 1091/1092 — touches `backend/tests/conftest.py` engine factory only. Sequencing it last keeps the v1020 carry-forward closure isolated for the close-gate matrix; close-gate cuts tags `v1021` + `v1.5.6`.

---

## Anticipated Migrations

None. All v1021 changes are async-context fix (`tasks_common.py`) + script logic (`seed-natural-earth.py`) + FastAPI routing config + docker-compose entrypoint + `db/Dockerfile` comment + test-infra engine factory. Public tag `v1.5.6` is SemVer **patch** — bug fixes + hygiene; no migrations, no schema changes, no API contract changes, no user-facing features.

---

## v1021 Carry-Forwards

_None at roadmap time. If INGEST-01's spike surfaces an architectural issue larger than a single async-context fix (e.g., a systemic boundary between commit-phase and quicklook-phase that warrants a phase of its own), promote to v1022+ per REQUIREMENTS.md `Future Requirements`._

---

## Milestone History

Active v1021 milestone above. Shipped milestones live in `.planning/milestones/v{N}-ROADMAP.md` archives:

- ✅ **v1020 Fixture Isolation** — Phases 1087-1090 (shipped 2026-05-22, local tag `v1020`, public tag `v1.5.5` at `8a924bb6`) — see [archive](milestones/v1020-ROADMAP.md). Closed v1019's 192-failure carry-forward (measured to 648; spike found ALL 4 v1019 hypotheses were 0; real cause was lifecycle-race silent-swallow). Cascade 648→76 (-88.3%). 3 retry helpers + 11 regression pins. `-n 4` CI default (NOT `-n auto`). 1 v1021 carry-forward: engine-level retry envelope for `-n auto` (closed by v1021 TEST-01).
- ✅ **v1019 Hygiene Tail** — Phases 1084-1086 (shipped 2026-05-22, local tag `v1019`, public tag `v1.5.4` at `02cb25db`) — see [archive](milestones/v1019-ROADMAP.md).
- ✅ **v1018 Hygiene — v1017 Tech-Debt Tail** — Phases 1080-1083 (shipped 2026-05-21, local tag `v1018`, public tag `v1.5.3` at `d1b76061`) — see [archive](milestones/v1018-ROADMAP.md).
- ✅ **v1017 Test Infra & Audit Tail** — Phases 1075-1079 (shipped 2026-05-21, local tag `v1017`, public tag `v1.5.2`).
- ✅ **v1016 Hardening Sweep** — Phases 1071-1074 (shipped 2026-05-21, local tag `v1016`, public tag `v1.5.1` at `70241f96`) — see [archive](milestones/v1016-ROADMAP.md).
- ✅ **v1015 Ingest/Export Lifecycle Hardening** — Phases 1065-1070 (shipped 2026-05-20, local tag `v1015`, public tag `v1.5.0`) — see [archive](milestones/v1015-ROADMAP.md).

Earlier milestones (v1.0 → v1014) live in `MILESTONES.md` and per-version archives under `.planning/milestones/`.

---

## Backlog

Backlog items (deferred to future milestones) are preserved in the project-wide history at `.planning/milestones/` archives. The previous in-progress backlog section (Phase 999.6 tenant scoping, 999.13 connector registry, 999.14 Helm/AMI pipeline, 999.15 SBOM signed images, 999.16 geolens-schemas package, 999.17 EBT key rotation, plus 11 captured-todo Phase 999.x items) is preserved in `MILESTONES.md` and accessible via `/gsd-review-backlog` for promotion to a future milestone.

---

*Roadmap created: 2026-05-23*
*Milestone: v1021 Docker Rebuild Sweep + Engine-level Retry*
*Phase numbering continued from v1020 (1087-1090 → 1091-1093). Source of scope: `.planning/quick/260523-at1-rebuild-the-docker-containers-and-import/260523-at1-SUMMARY.md`.*
