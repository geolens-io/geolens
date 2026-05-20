---
phase: 1062-medium-severity-remediation
plan: "02"
subsystem: backend-rate-limiting
tags:
  - security
  - rate-limiting
  - slowapi
  - SEC-S10
  - SEC-S11
dependency_graph:
  requires:
    - "app.modules.auth.router (limiter instance)"
    - "app.core.persistent_config (sync cache infrastructure)"
  provides:
    - "Per-route rate limiting on /search/datasets/ (SEC-S11)"
    - "Per-route rate limiting on /search/facets/ (SEC-S11)"
    - "Per-route rate limiting on /datasets/{id}/related/ (SEC-S11)"
    - "Per-route rate limiting on /settings/basemaps/ (SEC-S10)"
  affects:
    - "backend/app/modules/catalog/search/router.py"
    - "backend/app/modules/catalog/datasets/api/router_data.py"
    - "backend/app/modules/settings/router.py"
tech_stack:
  added: []
  patterns:
    - "Per-route @limiter.limit(callable) decorator — callable reads from _sync_rate_limit_cache with TTL fallback"
    - "Sync rate-limit accessor pattern (get_cached_*_rate_limit) — mirrors existing login/global pattern"
key_files:
  created:
    - backend/tests/test_rate_limits.py
  modified:
    - backend/app/core/persistent_config.py
    - backend/app/modules/settings/schemas.py
    - backend/app/modules/catalog/search/router.py
    - backend/app/modules/catalog/datasets/api/router_data.py
    - backend/app/modules/settings/router.py
    - .env.example
decisions:
  - "Per-IP rate limiting only (per-token deferred to SEC-FU): slowapi get_remote_address is the established convention; per-token requires custom key_func reading JWT subject — tracked for Phase 1063"
  - "Threshold defaults: 30/min for semantic search (matches audit recommendation for cost-sensitive endpoints), 120/min for basemap (SPA boot path fires once per page-load across NAT-shared users)"
  - "Module-level _semantic_search_rate_limit duplicate in router_data.py (3 lines): avoids cross-module import coupling between datasets router and search router"
  - "test_rate_limits.py re-enables limiter per-test: conftest disables limiter globally; rate-limit tests enable/reset/disable in try/finally to avoid state leakage"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-20T20:28:00Z"
  tasks_completed: 4
  files_changed: 7
---

# Phase 1062 Plan 02: Per-Route Rate Limiting (SEC-S10 + SEC-S11) Summary

Per-route `@limiter.limit` decorators applied to the three highest-cost/highest-exposure surfaces identified in the 2026-05-19 security audit: `/search/datasets/`, `/search/facets/`, `/datasets/{id}/related/` (OpenAI embedding cost-DoS, SEC-S11), and `/settings/basemaps/` (commercial-tier basemap key replay, SEC-S10). Two new PersistentConfig knobs (`semantic_search_rate_limit=30`, `basemap_proxy_rate_limit=120`) make thresholds configurable via env.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | PersistentConfig knobs + validators + .env docs | `04f5fe3c` | persistent_config.py, schemas.py, .env.example |
| 2 | Rate limit on /search/datasets/ + /search/facets/ | `c29f1fcd` | search/router.py, test_rate_limits.py |
| 3 | Rate limit on /datasets/{id}/related/ | `78865496` | router_data.py |
| 4 | Rate limit + SEC-S10 docstring on /settings/basemaps/ | `5654641b` | settings/router.py |

## What Was Built

### PersistentConfig additions (`persistent_config.py`)

Two new constants and entries adjacent to the existing login/global rate-limit block:
- `_DEFAULT_SEMANTIC_SEARCH_RATE_LIMIT = 30` — matches audit recommendation
- `_DEFAULT_BASEMAP_PROXY_RATE_LIMIT = 120` — loose enough for SPA boot path
- `SEMANTIC_SEARCH_RATE_LIMIT` and `BASEMAP_PROXY_RATE_LIMIT` PersistentConfig[int] (network tab)
- `get_cached_semantic_search_rate_limit()` and `get_cached_basemap_proxy_rate_limit()` sync accessors

### Schema validators (`schemas.py`)

`validate_semantic_search_rate_limit` and `validate_basemap_proxy_rate_limit` — both clamp to 1-1000. Registered in `SETTING_VALIDATORS`.

### Search router (`catalog/search/router.py`)

- Imports `limiter` from `auth.router` + `get_cached_semantic_search_rate_limit`
- Module-level `_semantic_search_rate_limit` callable helper
- `@limiter.limit(_semantic_search_rate_limit)` on `search_datasets_endpoint` and `search_facets_endpoint`

### Related datasets router (`datasets/api/router_data.py`)

- `request: Request` added to `list_related_datasets` signature (required by slowapi)
- Module-level `_semantic_search_rate_limit` duplicate (avoids cross-router coupling)
- `@limiter.limit(_semantic_search_rate_limit)` decorator applied

### Settings router (`settings/router.py`)

- `request: Request` added to `get_basemaps` signature
- `_basemap_proxy_rate_limit` callable helper
- `@limiter.limit(_basemap_proxy_rate_limit)` decorator applied
- SEC-S10 docstring paragraph documenting the `api_key` public-exposure model:
  > Client-side tile-provider keys are designed for browser exposure; do NOT put a backend-only commercial-tier key here; rotate in provider dashboard if misused.

### `.env.example`

Documents both new env keys with rationale:
```
# SEMANTIC_SEARCH_RATE_LIMIT=30  # caps OpenAI embedding cost-DoS
# BASEMAP_PROXY_RATE_LIMIT=120   # caps commercial-tier basemap key replay
```

### `test_rate_limits.py` (new file)

6 tests total:
1. `test_default_semantic_search_limit_is_30` — accessor returns 30 on empty cache
2. `test_default_basemap_proxy_limit_is_120` — accessor returns 120 on empty cache
3. `test_semantic_search_rate_limit_returns_429` — 7 GETs at threshold=5, ≥2 must be 429
4. `test_search_facets_rate_limit_returns_429` — same, against /search/facets/
5. `test_related_datasets_rate_limit_returns_429` — same, against /datasets/{id}/related/
6. `test_basemap_proxy_rate_limit_returns_429` — 10 GETs at threshold=5, ≥5 must be 429

Tests re-enable the limiter per-test (conftest disables it globally via `limiter.enabled = False`). Sync `_reset_limiter_storage()` clears in-memory counters before and after each test.

## Key Decisions

### Per-IP only (per-token deferred to SEC-FU)

The plan explicitly scopes this to per-IP rate limiting only. slowapi's `get_remote_address` key function is the established convention across all GeoLens routes. Per-token caps require a custom `key_func` that reads the JWT `sub` claim — that's a Phase 1063 SEC-FU enhancement. Documented in SUMMARY and tracked accordingly.

The implication: all users behind a corporate NAT or shared IP share the same rate-limit bucket. At 30/min for semantic search, a single attacker behind a NAT can still exhaust the budget for other users. The per-token enhancement closes this gap.

### Threshold rationale

- **30/min for semantic search**: Exact match of the audit recommendation ("Recommend @limiter.limit('30/minute') matching cost-sensitive endpoints"). Limits OpenAI embedding API calls to ≤ $0.000006/min at $0.02/1M tokens.
- **120/min for basemap proxy**: 2× the semantic limit. The SPA boot path fires once per page load; at 120/min per IP, a user refreshing the app every 30 seconds would stay under limit. An attacker systematically extracting the basemap key would hit the limit before bulk-downloading useful data.

## Deviations from Plan

None — plan executed exactly as written. The only implementation note: `_reset_limiter_storage()` used sync call `limiter._storage.reset()` (MemoryStorage is sync), not async. The plan's description of the reset mechanism was agnostic; the sync implementation is correct for slowapi's default in-memory backend.

## Verification Gates Passed

```
grep -c "@limiter.limit" ...
  search/router.py: 2
  router_data.py: 1
  settings/router.py: 1

grep -n "SEC-S10" settings/router.py
  61:  """SEC-S10: per-IP rate limit ...
  726: SEC-S10 (2026-05-20 audit): ...

pytest tests/test_rate_limits.py
  6 passed, 22 warnings
```

Broader regression (231 tests matching "search or related or basemap"):
```
231 passed, 2610 deselected
```

## e2e S11 Test Status

`e2e/sec-audit.spec.ts` test "S11 — burst of unique semantic queries gets rate-limited":
- Pre-fix: always skips (`test.skip(!has429, ...)` fires because all 80 responses are 200)
- Post-fix: 80 concurrent GETs against 30/min limit → 429s appear → `has429=true` → skip condition false → `expect(has429).toBe(true)` passes

## Known Stubs

None. All rate-limit decorators are live; thresholds flow from PersistentConfig at runtime.

## Threat Flags

No new threat surface introduced. The changes add defense-in-depth layers to existing public endpoints.

## Self-Check: PASSED

- `backend/tests/test_rate_limits.py`: exists, 6 tests pass
- Commits `04f5fe3c`, `c29f1fcd`, `78865496`, `5654641b`: verified in git log
- All modified files import cleanly (verified via Python import checks)
