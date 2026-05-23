---
phase: 1092-routing-infra-hygiene
status: complete
completed_date: 2026-05-23
requirements: [ROUTE-01, INFRA-01, INFRA-02]
plans_shipped: 3
public_tag_target: v1.5.6
milestone: v1021
subsystem: routing+infrastructure
tags: [route-01, infra-01, infra-02, hygiene, docker-rebuild-sweep]
---

# Phase 1092: Routing + Infra Hygiene — Phase Summary

**One-liner:** Closed all 3 hygiene requirements surfaced by quick task 260523-at1's docker-rebuild + canonical seed sweep: ROUTE-01 (307 internal-hostname leak on `/api/collections/` + `/api/auth/login/`), INFRA-01 (double `alembic upgrade head` invocation in the migrate service), and INFRA-02 (formal ACCEPT of the `db --platform=linux/amd64` pin). Phase ran 3 sequential plans with TD-13 atomic closes; live docker-stack verification at each plan boundary; sequential pytest baseline preserved at `3049 passed, 2 failed (pre-existing), 38 skipped` across all three plan closes.

## Phase Goal Achievement

All 5 phase-level success criteria from ROADMAP.md Phase 1092 satisfied:

- [x] **(Criterion 1) ROUTE-01**: `curl -s http://localhost:8080/api/collections/` returns 200 directly (no 307, no `api:8000` leak); same for `POST /api/auth/login/`. Documented `/collections/datasets` no-slash exception preserved (regression test pins it). MEMORY.md updated. Backend test `backend/tests/test_redirect_slashes.py` pins the no-leak behavior (5 tests, all PASS).
  - Evidence: Plan 1092-01 SUMMARY + 5 test node-IDs cited in REQUIREMENTS.md closure.
- [x] **(Criterion 2) INFRA-01**: `docker compose logs --no-color migrate | grep -c "Context impl PostgresqlImpl"` returns 1 (was 2). Chosen approach (`entrypoint: []` override on the migrate service) documented inline in `docker-compose.yml`. api service entrypoint still runs the safety-net (api logs show `Running database migrations` count = 1 on cold start).
  - Evidence: Plan 1092-02 SUMMARY + live docker-stack verification post `down -v && up -d --build`.
- [x] **(Criterion 3) INFRA-02**: `db/Dockerfile` carries an inline comment block above the `FROM` directive explaining the `--platform=linux/amd64` pin rationale (pgvector 0.8.2 build reproducibility against `postgis/postgis:17-3.5`) and a TODO link to the future multi-arch path.
  - Evidence: Plan 1092-03 SUMMARY + `head -25 db/Dockerfile` output.
- [x] **(Criterion 4) INFRA-02 doc**: `CHANGELOG.md [Unreleased]` block (target v1.5.6) carries the operator-facing rationale for the platform pin; build warnings still emit (`FromPlatformFlagConstDisallowed` + Apple Silicon platform mismatch) as expected ACCEPT behavior pinned by the inline comment.
  - Evidence: Plan 1092-03 SUMMARY + `docker compose build db 2>&1 | grep -iE "warn|platform"` returns FromPlatformFlagConstDisallowed warning.
- [x] **(Criterion 5) HARD INVARIANT**: Sequential pytest baseline preserved at `3049 passed, 2 failed (pre-existing), 38 skipped` across all three plan closes. The 2 failures (`test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` + `test_ssrf_redirect.py::test_make_safe_client_has_event_hook`) are pre-existing — test_phase_275 is OOS-flagged; test_ssrf_redirect is a flake that reproduces on stash without Phase 1092 changes.
  - Evidence: 3× sequential pytest runs (one per plan close) all returned the same `3049/2/38` numbers.

## Plans Shipped

- **`1092-01-PLAN.md`** (ROUTE-01) — Hybrid (c) fix: `redirect_slashes=False` at the FastAPI app level (`backend/app/api/main.py:443-469`) + stacked decorators on the two leaking surfaces (`backend/app/modules/auth/router.py:54-65` login + `backend/app/modules/catalog/search/router.py:917-925` list_collections) + Vite proxy `Location`-header rewrite (`frontend/vite.config.ts:90-100`) + MEMORY.md trailing-slash bullet refresh. Closed via 5 test node-IDs in `backend/tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak` (all PASS). Commits: `b5c9e4f1` RED, `c7f2d780` GREEN, `829a4194` atomic close.

- **`1092-02-PLAN.md`** (INFRA-01) — Added `entrypoint: []` override on the migrate service in `docker-compose.yml` (immediately above `command:`) with inline comment block cross-referencing `backend/scripts/api-entrypoint.sh:62-68` safety-net rationale. Verified post `down -v && up -d --build` via `docker compose logs --no-color migrate | grep -c "Context impl PostgresqlImpl"` returning 1 (was 2). api/worker safety-net unchanged. Commits: `54be8b4a` fix, `1285e8b9` atomic close.

- **`1092-03-PLAN.md`** (INFRA-02 + phase close) — ACCEPT disposition: 19-line inline comment block above the `db/Dockerfile FROM` directive explaining the pgvector 0.8.2 build reproducibility pin + TODO marker for multi-arch + 2 expected-warning documentation lines. Also populated `CHANGELOG.md [Unreleased]` block (target v1.5.6) with all 5 v1021 hygiene items (INGEST-01, OPS-01, ROUTE-01, INFRA-01, INFRA-02). Build warnings still emit (expected ACCEPT outcome). Commits: `a9cb6794` Dockerfile + CHANGELOG, plus atomic close commit at phase close.

## Coverage

| Requirement | Plan | Test node-IDs / Verification |
|-------------|------|-------------------------------|
| ROUTE-01 | 1092-01 | `tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_collections_slash_returns_200_directly` + `::test_collections_no_slash_returns_200_directly` + `::test_auth_login_slash_returns_correctly_without_leak` + `::test_auth_login_no_slash_returns_correctly` + `::test_collections_datasets_no_slash_preserved` (5 tests; all PASS) |
| INFRA-01 | 1092-02 | Live docker-stack: `docker compose logs --no-color migrate \| grep -c "Context impl PostgresqlImpl"` = 1 (was 2); `docker compose logs --no-color api \| grep -c "Running database migrations"` = 1 (safety-net intact) |
| INFRA-02 | 1092-03 | `head -25 db/Dockerfile` shows INFRA-02 comment block + `docker compose build db` STILL emits `FromPlatformFlagConstDisallowed` warning (expected ACCEPT) |

**3/3 requirements satisfied — no orphans, no carry-forwards.**

## Verification Matrix (Close-Gate)

| Gate | Pre-Phase Baseline | Post-Phase Result | Status |
|------|-------------------|-------------------|--------|
| GET `/api/collections/` | 307 with `Location: http://api:8000/collections` | 200 directly, no Location header | ✓ |
| POST `/api/auth/login/` | 307 with `Location: http://api:8000/auth/login` | 200 with access_token, no Location header, no body strip | ✓ |
| GET `/api/collections` (canonical) | 200 | 200 (preserved) | ✓ |
| GET `/api/collections/datasets` (OGC exception) | 200 | 200 (preserved) | ✓ |
| `migrate` alembic invocation count | 2 (`Context impl PostgresqlImpl` ×2) | 1 (single startup block) | ✓ |
| `api` safety-net invocation count | 1 | 1 (intact) | ✓ |
| `migrate` exit code | 0 | 0 (preserved) | ✓ |
| `db` build warnings | 2 (FromPlatformFlagConstDisallowed + platform mismatch) | 2 (still emitted; now expected per ACCEPT comment) | ✓ (ACCEPT) |
| Sequential `pytest tests/` | 3043 passed + 1 pre-existing failed + 38 skipped (per prompt) | 3049 passed + 2 failed (1 OOS + 1 pre-existing flake) + 38 skipped | ✓ (+6 passing, 0 NEW failures) |

## Patterns Established

- **(A) Phase 280 dual-shape decorator pattern extended to 2 more surfaces**. The original Phase 280 work added stacked `@router.post("/layers")` + `@router.post("/layers/")` decorators on the same handler in `catalog/maps/router.py:1580-1595` to prevent the `redirect_slashes=True`-induced 307 leak. Phase 1092 extended the same pattern to `auth/router.py:54-65` (login) and `catalog/search/router.py:917-925` (list_collections). With `redirect_slashes=False` at the app level (Phase 1092's primary fix), the dual-shape decorators become the per-route mechanism for accepting both shapes without redirect. The canonical (OpenAPI-published) form is no-slash; the trailing-slash variant declares `include_in_schema=False` to keep the OpenAPI surface clean.

- **(B) Vite dev-proxy `proxy.on('proxyRes')` hook as defense-in-depth for upstream `Location`-header leaks**. The hook inspects every proxied response, matches `^https?:\/\/api(:\d+)?\/` in the `Location` header, and rewrites to `http://${req.headers.host}/...`. Catches any future code path that re-introduces a 307 with the in-container hostname. Reference: `frontend/vite.config.ts:90-100`.

- **(C) `docker-compose entrypoint: []` override pattern for decoupling one-shot services from inherited Dockerfile ENTRYPOINTs**. The `migrate` service in this project shares the `api` build target so it inherits the api-entrypoint.sh safety-net. The explicit empty entrypoint override tells docker to treat `command:` as the executable line directly, bypassing the inherited ENTRYPOINT. The `api` + `worker` services keep the safety-net for cold-start protection. Reference: `docker-compose.yml` migrate service block.

- **(D) ACCEPT-shape closure pattern**: when an item is intentional-and-known (e.g., a platform pin), close it by adding the inline rationale + project-level doc rather than chasing the warning. INFRA-02 is the canonical example — comment block above the `FROM` directive + CHANGELOG `[Unreleased]` entry. Future operators see the warning, search for `INFRA-02` in the codebase, find the comment, understand the WHY. Reference: `db/Dockerfile:1-18` + CHANGELOG `[Unreleased]`.

## Findings & Notes

### Pre-existing flake-class failure carried through phase

`tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` fails in the full sequential pytest run with or without Phase 1092 changes (verified by stash/pop early in Plan 1092-01). Passes in isolation. The test is a pure synchronous assertion against `make_safe_client()` factory output — no httpx-event-hook contamination surface in the file itself. The flake is shared-state-class: an earlier test in the suite mutates a global httpx fixture or settings instance. NOT a Phase 1092 regression. Candidate for v1022 Hygiene Tail if it persists.

### docker rebuild required for INFRA-01 verification

Plan 1092-02 verification required `docker compose down -v && up -d --build` (full cycle wipes pgdata). After the rebuild, Natural Earth data was re-seeded via `python3 scripts/seed-natural-earth.py --base-url http://localhost:8080 --username admin --password admin` to leave the stack populated (109/109 succeeded, 0 failed — INGEST-01 + OPS-01 working as expected from Phase 1091). This re-seed adds ~3 minutes to the phase total but ensures the stack stays operational for Phase 1093 work.

## Next Phase

**Phase 1093 — TEST-01 engine-level retry envelope for `pytest -n auto`** (v1020 carry-forward per Phase 1088-04 architectural escalation REPORT). Phase 1092 unblocks Phase 1093 sequencing per ROADMAP.md. Phase 1093 targets the test-fixture engine only (`backend/tests/conftest.py` factory level); app-engine FastAPI request path is out of scope.

## Self-Check: PASSED

- **Files exist:**
  - `db/Dockerfile` (modified, INFRA-02 comment present) ✓
  - `CHANGELOG.md` (modified, [Unreleased] populated with 5 v1021 items) ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-01-SUMMARY.md` ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-02-SUMMARY.md` ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-03-SUMMARY.md` ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-SUMMARY.md` ✓ (this file)
- **All 3 v1021 Phase 1092 requirements closed:** ROUTE-01 + INFRA-01 + INFRA-02 = 3 `[x]` checks ✓
- **ROADMAP.md updates applied:** `[x] Phase 1092` + `[x] 1092-01..03-PLAN.md` + Progress row `3/3 | Complete | 2026-05-23` ✓
- **Commits (Phase 1092):**
  - `b5c9e4f1` test(1092-01): RED test
  - `c7f2d780` fix(1092-01): GREEN fix
  - `829a4194` chore(1092-01): atomic close
  - `54be8b4a` fix(1092-02): entrypoint override
  - `1285e8b9` chore(1092-02): atomic close
  - `a9cb6794` chore(1092-03): Dockerfile + CHANGELOG
  - (this commit) chore(1092-03): atomic close + Phase 1092-SUMMARY
- **Sequential pytest baseline:** 3049 passed + 2 failed (pre-existing) + 38 skipped — preserved across all 3 plan closes ✓
- **Live curl probes at phase close:** GET /api/collections/ → 200; POST /api/auth/login/ → 200; migrate Context impl = 1; api safety-net = 1 ✓
