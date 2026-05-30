# QA Audit — Data-Egress Authorization Consistency (2026-05-30)

READ-ONLY audit of data-egress authorization across all dataset/map endpoints.
Stack live at http://localhost:8080. Auth = admin/admin (form-encoded OAuth2).

Two failure classes assessed:
- **(A) Over-gating** — public+published data anonymous users CANNOT reach (UX/parity bug; ref issue #121).
- **(B) Under-gating / LEAK** — private/unpublished/restricted data reaches anonymous/unauthorized callers (**production blocker**).

## Headline

- **1 SECURITY LEAK (class B)** — `public` + non-`published` (draft/ready/internal) **vector** datasets leak their tile data and a valid HMAC tile-token to anonymous callers via the vector-tile surfaces. Confirmed live: 1842 bytes of decoded MVT feature data served to anon for a non-published dataset.
- **1 over-gating (class A)** — vector **file export** (`/datasets/{id}/export`) 401s for anonymous on public+published data, while the parallel COG download allows anonymous via a mint-issued download token. This is issue #121; the fix should mirror the COG anon-download pattern.
- All other egress surfaces (COG download, raster tiles, OGC items, STAC, DCAT, quicklook, map GET/thumbnail/share) are **correctly gated** (anon = public+published only; private/unpublished → 401/404).

---

## Authorization model (reference)

Canonical helper: `can_access_dataset()` — `backend/app/platform/extensions/defaults.py:93`.
For `user is None` (anonymous): returns `record.visibility == "public" AND record.record_status == "published"` (`defaults.py:109-110`).
Query-level equivalent: `filter_visible()` anon branch — `defaults.py:61-65` (same two predicates).
Wrappers: `check_dataset_access_or_anonymous()` / `check_dataset_access()` — `backend/app/modules/catalog/authorization.py:75,100`.

Endpoints that route anonymous through one of these (or the equivalent inline 3-branch check) are correct. The leak is the surfaces that gate on **visibility only** and never consult `record_status`.

---

## Live test matrix (anon vs admin, EXPECTED → ACTUAL)

Representatives (only 3 visibility/status combos exist live):
- PUB_VEC `cea84494-…` public+published vector
- PUB_RAS `4767fc35-…` public+published raster
- PRIV_VEC `26b0e7b5-…` private+published vector
- For the unpublished case, dataset `408a4162-…` (table `data.adk_high_peaks_nhd_waterbodies_aoi_2`) was transiently flipped `published → internal` then reverted to `published` (live runtime PATCH, fully reverted — verified).

| Endpoint | Visibility/Status | anon | admin | Expected anon | Verdict |
|---|---|---|---|---|---|
| `GET /datasets/{id}/export?format=geojson` | public+published | **401** | 200 | 200 (allow) | **OVER-GATED (#121)** |
| `GET /datasets/{id}/export` | private+published | 401 | 200 | 401/404 | correct |
| `POST /auth/download-token/{id}` + `GET /datasets/{id}/download/cog?token=` | public+published raster | 200 | 200 | 200 | correct |
| `POST /auth/download-token/{id}` | private+published | 404 | 200 | 404 | correct |
| `GET /tiles/token/{id}/` | public+published vec | 200 | 200 | 200 | correct |
| `GET /tiles/token/{id}/` | private+published vec | 401 | 200 | 401 | correct |
| `GET /tiles/token/{id}/` | **public+INTERNAL vec** | **200 (token minted)** | 200 | **404/401** | **UNDER-GATED — LEAK** |
| `GET /tiles/{table}/{z}/{x}/{y}.pbf` | public+published vec | 200 (feature bytes) | 200 | 200 | correct |
| `GET /tiles/{table}/{z}/{x}/{y}.pbf` | **public+INTERNAL vec** | **200 — 1842B MVT served** | 200 | **404/401** | **UNDER-GATED — LEAK** |
| `GET /tiles/raster-proxy/{id}/{z}/{x}/{y}.png` | public+published ras | 200 | 200 | 200 | correct |
| `GET /tiles/raster-proxy/{id}/…png` | private vec (not raster) | 404 | 404 | 404 | correct |
| `GET /collections/{id}/items` (OGC) | public+published | 200 | 200 | 200 | correct |
| `GET /collections/{id}/items` | private+published | 404 | 200 | 404 | correct |
| `GET /collections/{id}/items` | **public+INTERNAL** | **404** | 200 | 404 | correct (NOT leaked) |
| `GET /datasets/{id}/quicklook` | public+published | 200 | 200 | 200 | correct |
| `GET /datasets/{id}/quicklook` | private+published | 404 | 200 | 404 | correct |
| `GET /datasets/{id}/quicklook` | **public+INTERNAL** | **404** | 200 | 404 | correct (NOT leaked) |
| `GET /stac/collections/{id}/items` | public+published | 404* | 404* | — | correct (404 for admin too — STAC collection-id ≠ dataset-id, not an auth defect) |
| `GET /datasets/{id}/dcat/` | public+published | 200 | 200 | 200 | correct |
| `GET /datasets/{id}/dcat/` | private+published | 404 | 200 | 404 | correct |
| `GET /maps/{id}` | (maps have no publish-status; visibility only) | gated by `_check_map_read_access` | | public→ok, else 404 | correct |
| `GET /maps/{id}/thumbnail/` | visibility-checked | same helper | | | correct |

\* The `/raster-tiles/{id}/tiles/{z}/{x}/{y}.png` path in the task brief is the **nginx production rewrite**; the dev FastAPI route is `/tiles/raster-proxy/{id}/{z}/{x}/{y}.{fmt}`. The `/raster-tiles/…` path 404s for everyone in dev (not deployed in the app router) — not an auth finding.

---

## DEFECT 1 (CLASS B — SECURITY LEAK, production blocker)

**Public + non-published vector datasets leak tile data + a valid HMAC tile-token to anonymous.**

The vector-tile auth surfaces gate on `visibility != "public"` and **never check `record_status == "published"`**. Every other anon-reachable surface routes through `can_access_dataset()` / `check_dataset_access_or_anonymous()` / `apply_visibility_filter()`, all of which require BOTH `visibility=="public"` AND `record_status=="published"` for anonymous. The vector-tile path is the lone exception.

Affected code:
- **`backend/app/processing/tiles/router.py:1053`** — `_authorize_vector_tile_request()`: `if meta.visibility != "public":` … else returns `"public"` and serves the tile. No `record_status` check. Serves the actual `.pbf` feature bytes.
- **`backend/app/processing/tiles/router.py:1015-1025`** — `_resolve_dataset_meta()` builds `_DatasetMeta` and does **not even carry `record_status`**, so the auth helper has no way to enforce it. (`_DatasetMeta` definition lacks the field.)
- **`backend/app/processing/tiles/router.py:866`** — `get_tile_token()`: `if dataset.record.visibility != "public":` … else mints a valid HMAC token. No `record_status` check.
- **`backend/app/processing/tiles/router.py:939`** — `get_tile_tokens_batch()`: same `if dataset.record.visibility != "public":` gate. Same gap.
- **`backend/app/processing/tiles/router.py:1130`** — `cluster_tile_endpoint()` reuses `_authorize_vector_tile_request()`, inheriting the same leak for clustered point tiles.

Reproduce (transient, reversible — flips one dataset to `internal` and back):
```bash
TOKEN=$(curl -s -X POST "http://localhost:8080/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
T=408a4162-8632-42b9-9f5a-835e88ae9a9c
TBL=data.adk_high_peaks_nhd_waterbodies_aoi_2
XY=11/603/744

# Flip to a NON-published status while keeping it public
curl -s -X PATCH "http://localhost:8080/api/datasets/$T/status/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"internal"}'

# ANON gets a valid HMAC token for an unpublished dataset:
curl -s "http://localhost:8080/api/tiles/token/$T/"          # -> 200 {kind:vector, sig:…, scope:…}

# ANON gets the actual feature tile (gzipped MVT) for an unpublished dataset:
curl -s "http://localhost:8080/api/tiles/$TBL/$XY.pbf" -o /tmp/leak.pbf -w "%{http_code}\n"  # -> 200
python3 -c "import gzip;print(len(gzip.decompress(open('/tmp/leak.pbf','rb').read())),'bytes MVT leaked')"  # -> 1842

# REVERT
curl -s -X PATCH "http://localhost:8080/api/datasets/$T/status/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"published"}'
```

Observed: anon `tile-token` → 200 (valid sig), anon `.pbf` → 200 with 1842 bytes of decoded MVT feature data. EXPECTED: 404 (matches OGC/quicklook/DCAT behavior on the same dataset, which all correctly returned 404 anon during the same flip).

**Severity:** raster tiles (`_resolve_raster_access`, router.py:354) correctly enforce status (see `:438`, `:467`) — only the **vector** tile surfaces are vulnerable. Raster is the model to copy.

**Fix pattern (mirror existing correct code):**
1. Add `record_status` (and ideally `created_by`) to `_DatasetMeta` and populate it in `_resolve_dataset_meta()` (`router.py:1015`).
2. In `_authorize_vector_tile_request()` (`router.py:1053`), in the `visibility == "public"` branch, replicate the raster path's status guard (`router.py:465-479`): if `record_status != "published"` and the caller is not the owner/admin/embed-token, raise 404. The embed-token branch (`:1042`) can short-circuit as it does for raster.
3. In `get_tile_token()` (`:866`) and `get_tile_tokens_batch()` (`:939`), replace the bare `visibility != "public"` gate with the same status-aware check (or simply call `check_dataset_access_or_anonymous()` which already enforces both predicates — the cleanest fix, since these handlers already have the full ORM `dataset` object).

Note: this is only exploitable for datasets that are simultaneously `public` AND non-`published`. The default workflow only permits `published → internal` (one step back), so the live attack surface is "a published-then-unpublished public dataset." Still a real leak — an admin pulling a public dataset back to `internal` (e.g. to fix bad data) continues serving its tiles + tokens to the world.

---

## DEFECT 2 (CLASS A — OVER-GATING, ref issue #121)

**Vector file export 401s for anonymous on public+published datasets.**

- **`backend/app/processing/export/router.py:47`** — `user: Identity = Depends(require_permission("export"))`. `require_permission` chains through `get_current_active_user`, so any unauthenticated caller is rejected with 401 **before** the public-visibility check at `:65` is ever reached.

Contrast — the COG download reference path supports anonymous egress for public data:
- **`backend/app/modules/catalog/datasets/api/router_export.py:354`** `download_cog` uses `Depends(_resolve_download_user)` (`:254`) which returns `None` for a valid no-sub download token, then branches on `user is None` (`:385-397`) to enforce `check_dataset_access_or_anonymous` + `visibility == "public"`.

Reproduce:
```bash
PUB_VEC=cea84494-72d1-4242-aaca-c901a96c8d1b
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8080/api/datasets/$PUB_VEC/export?format=geojson"   # -> 401 (should allow anon)
```

**Fix pattern:** mirror `download_cog`. Either (a) add a `POST /auth/download-token/{id}` equivalent and accept a download-scoped `?token=` for vector export, or (b) swap `require_permission("export")` for `get_optional_user` + the same `user is None → check_dataset_access_or_anonymous + public-visibility` branch, keeping the `export` capability check only on the authenticated branch (exactly as `download_cog` does at `:398-407`). Apply uniformly across `format ∈ {gpkg,geojson,shp,csv}` (single handler, so one fix covers all formats).

---

## Auth-pattern inventory (so fixes mirror the right model)

| Surface | File:line | Pattern | Status-aware? |
|---|---|---|---|
| Vector export | `processing/export/router.py:47` | `require_permission("export")` (auth-forced) | n/a (over-gated) |
| COG download | `…/datasets/api/router_export.py:354,254` | `_resolve_download_user` + `check_dataset_access_or_anonymous` + public check | YES (reference for egress) |
| Download-token mint | `modules/auth/router.py:247,284` | `get_optional_user` + `check_dataset_access_or_anonymous` | YES |
| Raster tile proxy | `processing/tiles/router.py:354` | inline 3-branch (embed / non-public / public-status) | YES (`:438,:467`) |
| Vector tile `.pbf` | `processing/tiles/router.py:1053` | `_authorize_vector_tile_request` (visibility-only) | **NO — leak** |
| Vector tile token (single/batch) | `processing/tiles/router.py:866,939` | visibility-only | **NO — leak** |
| Cluster tile `.pbf` | `processing/tiles/router.py:1130` | reuses `_authorize_vector_tile_request` | **NO — leak (inherited)** |
| OGC items/feature | `standards/ogc/router.py:49,258` | `apply_visibility_filter` | YES |
| STAC items | `standards/stac/router.py:231-250` | explicit `record_status=='published'` + `apply_visibility_filter` | YES |
| DCAT record | `…/datasets/api/router_export.py:179` | `get_optional_user` + visible-dataset query | YES |
| Quicklook | `…/datasets/api/router.py:200,217` | `check_dataset_access_or_anonymous` | YES |
| Map GET/thumbnail | `…/maps/router.py:618,1444` + `_router_helpers.py:217` | `_check_map_read_access` (maps have no publish-status) | n/a |

---

## Verdict summary

- **UNDER-GATED (SECURITY LEAK):** vector tiles `.pbf`, vector tile-token (single + batch), cluster tiles — `processing/tiles/router.py:{1053,866,939,1130}` (+ missing field at `:1015`). **Production blocker.**
- **OVER-GATED:** vector file export — `processing/export/router.py:47` (issue #121).
- **CORRECT:** COG download, raster tile proxy, download-token mint, OGC items/feature, STAC items, DCAT record/catalog, quicklook, map GET/thumbnail/access, share/embed paths.

Recommended fix ordering: Defect 1 first (security), Defect 2 alongside #121.
