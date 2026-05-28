# 1139 OpenAPI/SDK Decision Record (Pitfall #15)

## Starting Tree State

Before any regeneration, `git diff --stat HEAD -- backend/openapi.json sdks/` returned empty (clean).

---

## Commands Executed (Dual-Snapshot Order: geolens FIRST)

### Step 1: Confirm clean starting tree
```
git diff --stat HEAD -- backend/openapi.json sdks/
# Output: (empty — clean)
```
Exit: 0

### Step 2: make openapi
```
cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py
# Output: Wrote /Users/ishiland/Code/geolens/backend/openapi.json
```
Exit: 0

### Step 3: git diff --stat -- backend/openapi.json (post-regeneration)
```
backend/openapi.json | 136 +++++++++++++++++++++++++++++++++++++++++++++++++++
1 file changed, 136 insertions(+)
```
**CHANGED — not empty.**

### Step 4: make openapi-check
```
cd backend && PYTHONPATH=. uv run python scripts/dump_openapi.py --check
```
Exit: 0 (snapshot now matches runtime)

### Step 5: make sdks-check (pre-commit)
Exit: 2 — `git diff --exit-code` found SDK files out of date relative to updated snapshot.

### Step 6: Commit backend/openapi.json + regenerated SDK files
Commit: `41a57488`

### Step 7: make sdks-check (post-commit)
```
make sdks + git diff --exit-code -- sdks/ ...
```
Exit: 0 — no drift after commit.

---

## Post-Regeneration Diff Summary

```
backend/openapi.json | 136 +++++++++++++++++++++++++++++++++++++++++++++++++++
1 file changed, 136 insertions(+)
```

### Changed Schema Paths

1. **`components/schemas/MapAccessResponse`** (new):
   - `can_view: boolean` — True when the current request may read the map
   - `can_edit: boolean` — True when the current request may open the map builder

2. **`paths["/maps/{map_id}/access/"]`** (new):
   - `GET /maps/{map_id}/access/` — Returns server-confirmed route access for the map viewer gate
   - Operation ID: `get_map_access_endpoint_maps__map_id__access__get`
   - Response 200: `MapAccessResponse`

### Root Cause

The endpoint `GET /maps/{map_id}/access/` was added in commit `3ed5ceb3`
(`fix(builder): gate viewer route on server access + polish share/chat/filters`) which
modified `backend/app/modules/catalog/maps/router.py` and `maps/schemas.py`.

That commit did NOT update `backend/openapi.json`. The subsequent DCAT-US refresh
commit `33b9a9a1` regenerated the snapshot but only for DCAT-US routes — it did not
pick up the maps/access endpoint that was added between runs. This created genuine
schema drift that persisted until this plan's regeneration.

Note: The plan's `<backend_change_inventory>` only inventoried commits since `8fd5f104~1`
(the v1030 branch start). The drift originated in `3ed5ceb3` which predates the branch
but was not captured in the committed snapshot. The runtime always had the endpoint; the
snapshot was simply stale.

---

## OpenAPI surface verdict: CHANGED

The diff was non-empty. The `MapAccessResponse` schema and `GET /maps/{map_id}/access/`
endpoint were missing from the committed snapshot. Both have now been committed.

### SDK Changes (committed in 41a57488)

**Python SDK:**
- New file: `sdks/python/geolens/api/maps/get_map_access_endpoint_maps_map_id_access_get.py`
- New file: `sdks/python/geolens/models/map_access_response.py`
- Modified: `sdks/python/geolens/models/__init__.py` (adds `MapAccessResponse` import + export)

**TypeScript SDK:**
- Modified: `sdks/typescript/src/client/types.gen.ts` (adds `MapAccessResponse` type + request/response types)
- Modified: `sdks/typescript/src/client/sdk.gen.ts` (adds `getMapAccessEndpointMapsMapIdAccessGet` function)
- Modified: `sdks/typescript/src/client/index.ts` (re-exports new function)

---

## Sibling Docs Follow-Up Required

Per the dual-snapshot order convention (project_openapi_dual_snapshot_refresh_order.md):
since the geolens OpenAPI diff was non-empty, the sibling docs repo
(`~/Code/getgeolens.com`) requires `npm run fetch-openapi` as a manual downstream
follow-up to pull the updated snapshot into the docs site. This is outside the scope
of this plan and must be done as a separate manual step before the next docs deploy.

---

## Final Gate Status

| Check | Exit Code | Status |
|-------|-----------|--------|
| `make openapi` | 0 | Regenerated |
| `git diff backend/openapi.json` | non-empty | CHANGED (committed) |
| `make openapi-check` | 0 | PASS |
| `make sdks-check` (post-commit) | 0 | PASS |
