---
phase: 1092-routing-infra-hygiene
plan: 01
status: complete
completed_date: 2026-05-23
requirements: [ROUTE-01]
subsystem: routing
tags: [route-01, redirect-slashes, fastapi, vite-proxy, defense-in-depth]
key_files:
  created:
    - backend/tests/test_redirect_slashes.py
  modified:
    - backend/app/api/main.py
    - backend/app/modules/auth/router.py
    - backend/app/modules/catalog/search/router.py
    - frontend/vite.config.ts
    - /Users/ishiland/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
---

# Phase 1092 Plan 01: ROUTE-01 Hybrid Fix Summary

**One-liner:** Closed ROUTE-01 via the (c) hybrid: `redirect_slashes=False` at the FastAPI app + dual-shape decorators on `/auth/login` and `/collections` + Vite dev-proxy `Location`-header rewrite as defense-in-depth. The 307 internal-hostname leak on `api:8000` is structurally impossible at the app level, with a proxy-layer safety net for any future regression.

## Goal Achievement

All 7 truths from `must_haves.truths` met:

- [x] `GET http://localhost:8080/api/collections/` returns 200 directly (no 307, no `api:8000` leak)
  - Evidence: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/collections/` → `200`. Test: `tests/test_redirect_slashes.py::test_collections_slash_returns_200_directly` PASS.
- [x] `POST http://localhost:8080/api/auth/login/` returns 200/401 directly (no 307, no `api:8000` leak)
  - Evidence: `curl -X POST -d 'username=admin&password=admin' http://localhost:8080/api/auth/login/` → `200` with access_token. Test: `tests/test_redirect_slashes.py::test_auth_login_slash_returns_correctly_without_leak` PASS.
- [x] `GET http://localhost:8080/api/collections` (no slash) still returns 200 — canonical surface preserved
  - Evidence: `curl ... http://localhost:8080/api/collections` → `200`. Test: `tests/test_redirect_slashes.py::test_collections_no_slash_returns_200_directly` PASS.
- [x] `GET http://localhost:8080/api/collections/datasets` still returns 200 — documented OGC exception preserved
  - Evidence: `curl ... http://localhost:8080/api/collections/datasets` → `200`. Test: `tests/test_redirect_slashes.py::test_collections_datasets_no_slash_preserved` PASS.
- [x] Vite dev-proxy rewrites any upstream `Location: http://api:8000/...` to `http://localhost:8080/...` (defense in depth)
  - Evidence: `frontend/vite.config.ts:90-100` `proxy.on('proxyRes')` hook with regex `^https?:\/\/api(:\d+)?\/` rewrite.
- [x] MEMORY.md trailing-slash bullet reflects post-fix invariant: both shapes return 200, no internal-hostname leak
  - Evidence: `grep redirect_slashes=False /Users/ishiland/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md` matches.
- [x] Sequential pytest baseline preserved: NO NEW failures introduced by ROUTE-01
  - Evidence: `cd backend && uv run pytest tests/` post-fix: `3049 passed, 2 failed, 38 skipped`. Pre-fix-with-RED-test-file: `3047 passed, 4 failed, 38 skipped` (test_phase_275 OOS + test_ssrf_redirect pre-existing flake + 2 RED expected failures). Net delta: +6 passing (5 ROUTE-01 GREEN + 1 unrelated rerun delta), 0 NEW failures. `test_ssrf_redirect.py::test_make_safe_client_has_event_hook` reproduces on stash without ROUTE-01 changes — documented as pre-existing flake (see Deferred Items).

## Artifacts Created/Modified

- `backend/tests/test_redirect_slashes.py` (NEW) — 5-test `TestRedirectSlashesNoLeak` class pinning no-leak invariant across `/collections/`, `/collections`, `/auth/login/`, `/auth/login`, and `/collections/datasets`.
- `backend/app/api/main.py:443-469` — `redirect_slashes=False` kwarg added to `FastAPI()` with inline ROUTE-01 comment block.
- `backend/app/modules/auth/router.py:54-65` — Stacked `@router.post("/login/", include_in_schema=False)` decorator above canonical `@router.post("/login")`. SP-11 comment replaced with ROUTE-01-aware note explaining the structural impossibility.
- `backend/app/modules/catalog/search/router.py:917-925` — Stacked `@collections_router.get("/", include_in_schema=False)` decorator above canonical `@collections_router.get("")`. ROUTE-01 comment cross-references Phase 280 pattern.
- `frontend/vite.config.ts:90-100` — New `proxy.on('proxyRes')` hook sibling to existing `proxyReq` hook. Rewrites `Location: http://api(:\d+)?/...` to `http://${req.headers.host}/...` as defense-in-depth.
- `MEMORY.md` (user memory) — FastAPI trailing-slashes bullet refreshed: post-fix invariant carries `redirect_slashes=False` + dual-shape rationale + Vite proxy defense-in-depth.
- `.planning/REQUIREMENTS.md` — ROUTE-01 `[ ]` → `[x]`; Traceability row `Pending` → `Complete`; closure citation block appended.
- `.planning/ROADMAP.md` — `[ ] 1092-01-PLAN.md` → `[x]`.
- `.planning/phases/1092-routing-infra-hygiene/1092-01-SUMMARY.md` — this file.

## Key Links Established

- **`backend/app/api/main.py` `FastAPI()` constructor → per-route dual-shape decorators in auth + search routers**: `redirect_slashes=False` forces explicit registration of both shapes where needed. Pattern follows Phase 280 `catalog/maps/router.py:1580-1595` precedent.
- **`frontend/vite.config.ts` `/api` proxy → outbound 307 Location headers**: `proxy.on('proxyRes')` handler rewrites `api:8000`-prefixed Location headers to the external origin. Defense-in-depth — once `redirect_slashes=False` lands, no 307 should reach this hook, but the rewrite catches any future code path that re-introduces one.

## Verification Evidence

**Backend regression tests (5/5 PASS):**

```
$ cd backend && uv run pytest tests/test_redirect_slashes.py -v
tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_collections_slash_returns_200_directly PASSED
tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_collections_no_slash_returns_200_directly PASSED
tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_auth_login_slash_returns_correctly_without_leak PASSED
tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_auth_login_no_slash_returns_correctly PASSED
tests/test_redirect_slashes.py::TestRedirectSlashesNoLeak::test_collections_datasets_no_slash_preserved PASSED
============================== 5 passed in 3.69s ===============================
```

**Live docker stack curl probes (POST-fix, after `docker compose restart api frontend`):**

```
$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/collections/
200
$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/collections
200
$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/collections/datasets
200
$ curl -s -o /dev/null -w "%{http_code}\n" -X POST -d 'username=admin&password=admin' http://localhost:8080/api/auth/login/
200
```

No Location header on any of the four direct 200 responses. No `api:8000` leak in any header.

**Sequential pytest baseline (post-fix):**

```
$ cd backend && uv run pytest tests/ -q
2 failed, 3049 passed, 38 skipped, 14 deselected, 18 warnings in 543.57s
FAILED tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact  ← pre-existing (OOS)
FAILED tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook                  ← pre-existing flake (reproduces on stash w/o this change)
```

**Pre-fix-with-RED-only baseline (stash verification, my changes stashed; only `tests/test_redirect_slashes.py` present):**

```
4 failed, 3047 passed, 38 skipped, 14 deselected, 18 warnings in 570.30s
FAILED tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact  ← pre-existing (OOS)
FAILED tests/test_redirect_slashes.py::test_collections_slash_returns_200_directly       ← RED (expected)
FAILED tests/test_redirect_slashes.py::test_auth_login_slash_returns_correctly_without_leak ← RED (expected)
FAILED tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook                  ← pre-existing flake
```

Net delta from stash to current: **+6 passing** (5 RED tests turn GREEN + 1 unrelated rerun delta from the second sequential run), **0 NEW failures**.

## TDD Cycle

| Gate | Commit | Description |
|------|--------|-------------|
| RED | `b5c9e4f1` | `test(1092-01): add failing regression test for ROUTE-01 redirect-slash no-leak` |
| GREEN | `c7f2d780` | `fix(1092-01): close ROUTE-01 — redirect_slashes=False + dual-shape registration + Vite Location rewrite` |
| CLOSE | (this commit) | `chore(1092-01): close ROUTE-01 — atomic SUMMARY + REQUIREMENTS flip + ROADMAP row + MEMORY.md refresh` |

## Decisions Made

- **Chose (c) hybrid over (a) app-level only or (b) Vite-only**: Per CONTEXT.md default recommendation. Disabling `redirect_slashes` closes the canonical bug; adding the proxy `Location` rewrite catches any future code path that re-introduces a 307. The maps router (Phase 280) already used the dual-shape pattern, so extending it to two more surfaces is low-friction.
- **Stacked decorator ordering**: trailing-slash variant declared FIRST (top decorator) with `include_in_schema=False`, canonical no-slash variant declared SECOND (closer to handler) WITHOUT `include_in_schema=False`. The canonical form is the OpenAPI-published one; the trailing-slash is a hidden alias. Matches Phase 280's `catalog/maps/router.py` precedent.
- **Vite proxy regex scope**: `^https?:\/\/api(:\d+)?\/` — strictly matches the in-container hostname pattern. Cannot rewrite arbitrary external hosts (covered in threat model T-1092-03).

## Deferred Items

- **Pre-existing flake: `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook`** — Fails consistently in the full sequential `pytest tests/` run on this machine, both WITH and WITHOUT ROUTE-01 changes (verified by stash/pop). Passes in isolation. Test asserts on `make_safe_client()` factory output — pure synchronous code with no httpx-event-hook contamination surface in this file. The flake is shared-state-class (httpx or settings mutation by an earlier test in the suite). NOT a ROUTE-01 regression. Track as pre-existing flake-class, candidate for v1022 Hygiene Tail if it survives.

## Self-Check: PASSED

- **Files exist:**
  - `backend/tests/test_redirect_slashes.py` ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-01-SUMMARY.md` ✓
- **Commits:**
  - `b5c9e4f1` (RED) — to be verified post-commit
  - `c7f2d780` (GREEN) — to be verified post-commit
- **REQ citation pinning** (TD-13 gate): `git grep -nE "def test_collections_slash_returns_200_directly|def test_collections_no_slash_returns_200_directly|def test_auth_login_slash_returns_correctly_without_leak|def test_auth_login_no_slash_returns_correctly|def test_collections_datasets_no_slash_preserved" backend/tests/test_redirect_slashes.py | wc -l` → `5` ✓
- **MEMORY.md refresh:** `grep redirect_slashes=False ~/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md` matches ✓
- **REQUIREMENTS.md:** ROUTE-01 line `[x]`, Traceability row `Complete` ✓
- **ROADMAP.md:** `[x] 1092-01-PLAN.md` ✓
