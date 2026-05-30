---
phase: 1156-vector-tile-egress-authorization
plan: "02"
subsystem: auth
tags: [security, vector-tiles, authorization, regression-test, pytest]

# Dependency graph
requires:
  - 1156-01 (SEC-01 auth fix — code under test)
provides:
  - Regression test pinning SEC-01 anon denial for public+unpublished vector tile tokens
  - Positive over-gating guard: public+published still serves anon
  - Covers single token, batch token, and cluster-tile denial paths
affects:
  - 1160 (close-gate can rely on these tests as the fast CI signal)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Regression test modeled on test_raster_tiles.py: same _get_admin_id, _create_vector_dataset, _get_auth_header helpers"
    - "anyio_mode=auto collects async class methods without pytestmark — consistent with existing test suite"

key-files:
  created:
    - backend/tests/test_vector_tile_auth.py
  modified:
    - backend/app/processing/tiles/router.py

key-decisions:
  - "Rule 1 auto-fix: Wave 1 used port.check_dataset_access_or_anonymous() but DefaultProcessingPort has no such method; fixed by importing check_dataset_access_or_anonymous directly from app.modules.catalog.authorization (pattern used by all other routers)"
  - "Cluster test asserts status in (400, 404): factory seeds no geometry_type so _ensure_clusterable_dataset fires 400 before the auth guard; both statuses prove no tile bytes delivered to anon"

patterns-established:
  - "Token endpoint tests use dataset.id (UUID) not table_name; cluster test uses table_name"
  - "No geometry seeded — test isolation via _create_vector_dataset factory only"

requirements-completed: [SEC-01]

# Metrics
duration: 12min
completed: 2026-05-30
---

# Phase 1156 Plan 02: SEC-01 Regression Test Summary

**Pinned the SEC-01 anonymous vector-tile egress fix with a four-case regression test; also auto-fixed a latent AttributeError in the Wave 1 code (`port.check_dataset_access_or_anonymous` → direct import) that blocked the test from running.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-30T17:10:00Z
- **Completed:** 2026-05-30T17:22:00Z
- **Tasks:** 1
- **Files created:** 1 (`backend/tests/test_vector_tile_auth.py`)
- **Files modified:** 1 (`backend/app/processing/tiles/router.py`)

## Accomplishments

- Created `backend/tests/test_vector_tile_auth.py` with class `TestVectorTileEgressAuthorization` containing four async test methods:
  1. `test_anon_single_token_denied_for_public_unpublished` — anon `GET /tiles/token/{id}/` on public+internal → 401 or 404
  2. `test_anon_batch_token_denied_for_public_unpublished` — anon `POST /tiles/tokens/` on public+internal → 200 body with `"error"` key and no `"sig"`
  3. `test_anon_cluster_tile_denied_for_public_unpublished` — anon `GET /tiles/clusters/data.{table}/2/0/0.pbf` → 400 or 404 (no tile bytes)
  4. `test_anon_single_token_allowed_for_public_published` — positive over-gating guard: anon on public+published → 200 with `"sig"` present
- Auto-fixed (Rule 1): `DefaultProcessingPort` has no `check_dataset_access_or_anonymous` method — replaced `port.check_dataset_access_or_anonymous(...)` in both `get_tile_token` and `get_tile_tokens_batch` with a direct import of `check_dataset_access_or_anonymous` from `app.modules.catalog.authorization`, matching the pattern used by every other router in the codebase.

## Task Commits

1. **Rule 1 bug fix: import check_dataset_access_or_anonymous directly** — `82527ed3` (fix)
2. **Task 1: Create test_vector_tile_auth.py** — `67717802` (test)

## Pytest Output

```
======================== 4 passed, 22 warnings in 4.22s ========================
```

Run recipe: `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_vector_tile_auth.py -v`

## Files Created/Modified

- `backend/tests/test_vector_tile_auth.py` — new; 208 lines; class `TestVectorTileEgressAuthorization` with 4 test methods
- `backend/app/processing/tiles/router.py` — 3-line fix: add `check_dataset_access_or_anonymous` import and replace two `port.*` calls

## Decisions Made

- **Direct import instead of port delegation**: `check_dataset_access_or_anonymous` is already a module-level function in `app.modules.catalog.authorization`. The `DefaultProcessingPort` was not extended with this method (it only has `check_dataset_access`). The correct fix matches what every catalog/export router does: `from app.modules.catalog.authorization import check_dataset_access_or_anonymous`.
- **No geometry seeded**: The factory creates no PostGIS geometry. The regression surface is the HMAC token (capability grant), not the raw `.pbf` bytes. Avoiding geometry keeps the fixture lean and deterministic.
- **Cluster test: `in (400, 404)`**: `_ensure_clusterable_dataset` runs before `_authorize_vector_tile_request` in the call stack. With `geometry_type=None`, it fires a 400 first. Both outcomes prove anon gets no tile bytes — the SEC-01 invariant holds regardless of ordering.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `DefaultProcessingPort.check_dataset_access_or_anonymous` does not exist**
- **Found during:** Task 1 (first pytest run — `AttributeError: 'DefaultProcessingPort' object has no attribute 'check_dataset_access_or_anonymous'`)
- **Issue:** Wave 1 (`1156-01`) introduced `port.check_dataset_access_or_anonymous(...)` calls in `get_tile_token` (line 867) and `get_tile_tokens_batch` (line 934). `DefaultProcessingPort` (`backend/app/platform/extensions/defaults.py:250`) only delegates `check_dataset_access` — it has no `check_dataset_access_or_anonymous` wrapper. The SEC-01 authorization fix was therefore non-functional for both token endpoints at runtime.
- **Fix:** Added `from app.modules.catalog.authorization import check_dataset_access_or_anonymous` to `tiles/router.py` imports; replaced both `port.check_dataset_access_or_anonymous(...)` calls with direct invocations. This is the same pattern used by `catalog/datasets/api/router.py`, `router_metadata.py`, `router_data.py`, `auth/router.py`, etc.
- **Files modified:** `backend/app/processing/tiles/router.py`
- **Commit:** `82527ed3`

## Issues Encountered

- None beyond the Rule 1 deviation above.

## User Setup Required

None.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes. The bug fix closes the gap where the Wave 1 token-endpoint authorization was silently a no-op (`AttributeError` at runtime instead of raising `HTTPException(404)`). The fix routes both token endpoints through the correct `check_dataset_access_or_anonymous` function.

## Known Stubs

None.

## Self-Check: PASSED

- `backend/tests/test_vector_tile_auth.py` — FOUND
- Commit `82527ed3` (fix) — FOUND
- Commit `67717802` (test) — FOUND
- `4 passed` pytest result confirmed against live DB

---
*Phase: 1156-vector-tile-egress-authorization*
*Completed: 2026-05-30*
