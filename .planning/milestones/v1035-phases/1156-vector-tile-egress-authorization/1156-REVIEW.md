---
phase: 1156-vector-tile-egress-authorization
reviewed: 2026-05-30T17:25:00Z
depth: deep
files_reviewed: 2
files_reviewed_list:
  - backend/app/processing/tiles/router.py
  - backend/tests/test_vector_tile_auth.py
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 1156: Code Review Report

**Reviewed:** 2026-05-30T17:25:00Z
**Depth:** deep
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the SEC-01 vector-tile egress authorization fix (`backend/app/processing/tiles/router.py`) and its regression test (`backend/tests/test_vector_tile_auth.py`). I traced all five entry points, the raster reference (`_resolve_raster_access`), the delegated authorization chain (`check_dataset_access` → `can_access_dataset`), the dataset metadata cache, and ran the full tile test surface (48 passed locally; 74/74 claim verified against the prior commit message and consistent with the focused run).

**The core security fix is correct and complete.** All five entry points are status-gated, the 401/404 status-code contract matches the raster reference exactly, no over-gating of public+published was found, and no AttributeError-class latent calls remain (the prior non-functional `port.check_dataset_access_or_anonymous` was fully removed in the latest commit `971c8b80`, including its now-dead import — verified clean). There are **no BLOCKER findings**: an anonymous caller cannot mint a token or obtain MVT bytes for a public-unpublished dataset on any of the five surfaces.

The findings below are **test-coverage and hygiene** issues. The most consequential (WR-01) is that the regression test for the cluster-tile auth gate is a **false-positive pass** — it never reaches the SEC-01 auth code it purports to pin, so the `.pbf`/cluster branch of the fix (`_authorize_vector_tile_request` lines 1103–1117) currently has zero executing regression coverage. The fix is correct today; the test does not protect it from future regression.

## Verification performed

- **Five entry points gated:** `_DatasetMeta`/`_resolve_dataset_meta` carry `record_status`+`created_by` (`router.py:85-86,1052-1053`); `get_tile_token` (`:909`) and `get_tile_tokens_batch` (`:976`) call `_enforce_tile_token_access`; `_authorize_vector_tile_request` has the status gate (`:1103-1117`) and `user` is threaded into both `tile_endpoint` (`:1330`) and `cluster_tile_endpoint` (`:1188`). ✓
- **No over-gating:** public+published anon path returns 200+`sig` (test 4 passes; `_enforce_tile_token_access` falls through to allow when `record_status == "published"`). ✓
- **Status-code contract matches raster:** non-public+anon → 401 (`:856-860`), public+unpublished+non-owner → 404 (`:866-874`), identical to `_resolve_raster_access` (`:467-481`). Both vector surfaces (token and `.pbf`) return 404 for public-unpublished — existence not leaked inconsistently. ✓
- **Delegated RBAC is status-aware:** the non-public authenticated branch delegates to `port.check_dataset_access` → `can_access_dataset`, which enforces `record_status != "published" and created_by != user.id → deny` (`defaults.py:115`). So the helper does not need to re-check status on the non-public path. ✓
- **No latent broken port calls:** `port.check_dataset_access` and `port.get_user_roles` both exist on the port interface (`processing_port.py:196,206`) and the default impl (`defaults.py:315,324`). The previously non-functional `check_dataset_access_or_anonymous` (no such port method) was removed; no import or call remains (`grep` clean). ✓
- **No state/cache hazard:** the `_dataset_cache` is keyed by `table_name` and stores the new `record_status`/`created_by` fields; tests use unique random table names so no cross-test contamination. The 60s TTL cache holds metadata only — auth is re-evaluated per request against `meta.record_status`, not cached as an allow/deny decision. ✓
- **API-key callers:** `get_optional_user` resolves the `?api_key=` query param (`auth/dependencies.py:25-29`), so key-authenticated owners/admins are correctly treated as `user` in the gate; no bypass and no over-gate. ✓
- **Test collection:** despite `asyncio_mode = "strict"` and no `@pytest.mark.asyncio`/`pytestmark`, all 4 tests DO collect and run (via AnyIO `anyio_mode = "auto"` + the `anyio_backend` fixture). Verified empirically: `collected 4 items ... 4 passed`. ✓

## Warnings

### WR-01: Cluster-tile regression test is a false-positive pass — never reaches the SEC-01 auth gate

**File:** `backend/tests/test_vector_tile_auth.py:149-181`
**Issue:**
`test_anon_cluster_tile_denied_for_public_unpublished` asserts `resp.status_code in (400, 404)`, but I confirmed empirically that it passes via **400 from the clusterable gate**, not the 404 SEC-01 auth gate:

- The factory (`_create_vector_dataset`) seeds **no `geometry_type`**.
- `cluster_tile_endpoint` ordering is `_resolve_dataset_meta` → `_ensure_clusterable_dataset` → `_authorize_vector_tile_request` (`router.py:1179-1189`).
- `_ensure_clusterable_dataset` raises **400** for `geometry_type is None` (`router.py:1126-1133`) — verified directly: `clusterable gate fired FIRST: 400 Cluster tiles require a vector point dataset`. The request log for the running test confirms `status_code=400`.

Consequence: this test passes **identically with or without** the SEC-01 `record_status` guard in `_authorize_vector_tile_request`. It does not exercise the cluster auth-denial path it claims to pin (the docstring even acknowledges the 400 comes from the clusterable gate). Combined with WR-02, the entire `.pbf`/cluster branch of the SEC-01 fix (`router.py:1103-1117`) has **no executing regression coverage** — a future edit that drops the status check there would not be caught.

This is the security-critical surface that the milestone QA pass measured as leaking "1842 bytes of feature data" (REQUIREMENTS.md SEC-01), so the cluster/`.pbf` branch is exactly the path that most warrants a true regression pin.

**Fix:** Seed a point geometry on the cluster-test dataset so `_ensure_clusterable_dataset` passes and execution reaches the auth gate, then assert the tighter `== 404`. Mirror the `test_tiles.py` fixtures that already create real point data tables (`test_private_cluster_tile_requires_signature`, `:432-461`) — set `geometry_type="Point"` on the `Dataset` and create the backing data table via the `_create_data_table`/`_cleanup_data_table` helpers, e.g.:

```python
# in _create_vector_dataset, accept geometry_type and set it on the Dataset
dataset = Dataset(
    record_id=record.id,
    table_name=...,
    srid=4326,
    geometry_type="Point",        # so _ensure_clusterable_dataset passes
    feature_count=0,
    source_format="geojson",
    column_info=[{"name": "gid", "type": "integer"}],
)
# ... and in the cluster test, create+cleanup the backing table so the auth
# gate (not the clusterable gate) is the thing exercised:
await _create_data_table(test_db_session, dataset.table_name)
try:
    resp = await client.get(f"/tiles/clusters/data.{dataset.table_name}/2/0/0.pbf")
    assert resp.status_code == 404, (
        f"anon must hit the auth 404 (not the clusterable 400); got {resp.status_code}"
    )
finally:
    await _cleanup_data_table(test_db_session, dataset.table_name)
```

If keeping the geometry-free factory is preferred, at minimum add a separate test that DOES reach the auth gate (point geometry + backing table) and asserts `== 404`, so the cluster auth branch is genuinely pinned. As-is, the test's value is limited to proving "anon gets no bytes," which the clusterable gate already guarantees regardless of the security fix.

### WR-02: Raw `.pbf` `tile_endpoint` public-unpublished auth branch has no regression coverage

**File:** `backend/tests/test_vector_tile_auth.py` (absent test) — guards `backend/app/processing/tiles/router.py:1103-1117` (reached via `tile_endpoint`, `:1289-1331`)
**Issue:**
The SEC-01 fix added the `record_status` gate to `_authorize_vector_tile_request`, which serves both the cluster route AND the primary raw vector-tile route `GET /tiles/data.{table}/{z}/{x}/{y}.pbf` (`tile_endpoint`). The plan deliberately excluded the raw `.pbf` from the regression test because the geometry-free factory makes the `ST_AsMVT` query 500/404 on missing data "regardless of auth." The existing `test_tiles.py` `.pbf` auth tests all use `visibility="private"` + `record_status="published"` (`:363-461`) — none cover the public-unpublished case. Net result: the public-unpublished branch of `_authorize_vector_tile_request` (the literal egress leak that was measured leaking feature bytes) has **no test that reaches it** on either route. The fix is correct by inspection, but unprotected against regression.

**Fix:** Add a test that creates a public+unpublished point dataset with a real backing data table (same pattern as `test_tiles.py:432-461`) and asserts the anonymous raw-`.pbf` request returns **404** before any geometry query — the auth gate runs at `router.py:1322-1331`, before the MVT SQL, so missing geometry is not reached when `user is None` and `record_status != "published"`. This closes the gap WR-01 and WR-02 jointly leave: a single test with point geometry + backing table exercises the shared `_authorize_vector_tile_request` 404 path that both the cluster and raw routes depend on.

## Info

### IN-01: Unused `pytest` import in the regression test (ruff F401)

**File:** `backend/tests/test_vector_tile_auth.py:20`
**Issue:** `import pytest` is never referenced — the test class uses plain `async def` methods collected by AnyIO auto-mode, with no `@pytest.mark.*` decorators or `pytestmark`. `ruff check` flags it: `F401 [*] 'pytest' imported but unused`. The analog `test_raster_tiles.py` keeps `import pytest` because it uses `@pytest.mark.asyncio` at module scope (`:545,577`); this file copied the import without the usage. Harmless to behavior (tests pass), but it is a lint failure that will trip a `ruff check` gate.

**Fix:** Remove the unused import:
```python
# delete line 20:
import pytest
```
(Confirmed the file does not otherwise reference `pytest`; the 4 tests collect via AnyIO regardless.)

---

_Reviewed: 2026-05-30T17:25:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
