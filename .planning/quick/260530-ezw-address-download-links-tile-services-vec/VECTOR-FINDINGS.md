# Vector Download Links & Tile Services — Investigation Findings

Date: 2026-05-30. Stack: frontend+proxy `http://localhost:8080`, API under `/api`. Read-only, no files changed.

Auth token (form-based OAuth2):
```bash
TOKEN=$(curl -s -X POST "http://localhost:8080/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

---

## 1. Dataset enumeration

- List endpoint: `GET /api/datasets/?limit=100`. **Requires auth** (anon → 401). The
  response shape is `{"datasets":[...], "total":N}` — NOT `{items:[...]}`. The earlier
  "returned 0" was reading the wrong key (`items`); there are **127 datasets** (122 vector,
  5 raster).
- `/api/records` → 404 (no such route). Record-first discovery is `/api/collections/datasets/items`
  (OGC Features) and `/api/search/datasets/`.
- The `/api/datasets/{id}` detail DOES expose `record_status` + `visibility` (flattened, not nested).
- **Status/visibility survey of all 122 vector datasets:**
  - `published` + `public`: **119**
  - `published` + `private`: **3** (`sample`, `sample_2`, `sample_3`)
  - **No draft/ready (unpublished) vector datasets exist.** Private published is the only
    "restricted access" proxy available; the anon-blocked case was tested against it.

Representative datasets used for live tests:

| Role | id | table | geom | status | visibility |
|---|---|---|---|---|---|
| Published+public vector | `f09bdb8c-d342-41e2-bcfb-4a4ca7cdc5c0` | `populated_places_simple_10m` | MULTIPOINT | published | public |
| Published+private vector | `5b747b95-0f28-4f76-8c68-82cbff7a23ca` | `sample` | MULTIPOINT (NYC −73.9857,40.7484) | published | private |

---

## 2. Vector export endpoints

Defined in `backend/app/processing/export/router.py:31` — `GET /datasets/{dataset_id}/export`.
Format enum `backend/app/processing/export/schemas.py`: **gpkg (default), geojson, shp, csv**.
Query params: `format`, `target_crs` (EPSG:n), `bbox`, `where`.

**Auth model:** `Depends(require_permission("export"))` at `router.py:47` — a hard auth gate.
There is **no anonymous path**, even for public datasets. Anon always → 401.
Frontend sends the session JWT via `Authorization` header (`authenticatedDownload`), so
this is by design (browser `<a download>` is not used for vector export).

Secondary GeoJSON route: `GET /datasets/{id}/features.geojson`
(`backend/app/modules/catalog/features/router.py:51`) — `Depends(get_current_active_user)`,
also auth-required, anon → 401. Caps at 5000 features.

### Live results — export (curl `-w "%{http_code} %{content_type} %{size_download}"`)

| Endpoint | Auth state | HTTP | Content-Type | Body |
|---|---|---|---|---|
| `/datasets/{pub}/export?format=csv` | admin | **200** | text/csv | 1,481,498 B ✅ |
| `/datasets/{pub}/export?format=geojson` | admin | **200** | application/geo+json | 5,241,612 B ✅ |
| `/datasets/{pub}/export?format=gpkg` | admin | **200** | application/geopackage+sqlite3 | 2,285,568 B ✅ |
| `/datasets/{pub}/export?format=shp` | admin | **200** | application/zip | 710,542 B ✅ |
| `/datasets/{pub}/export?format=*` | **anon** | **401** | application/problem+json | gated ✅ |
| `/datasets/{priv}/export?format=csv` | admin (owner/admin) | **200** | text/csv | 68 B ✅ |
| `/datasets/{priv}/export?format=geojson` | admin | **200** | application/geo+json | 231 B ✅ |
| `/datasets/{priv}/export?format=*` | **anon** | **401** | application/problem+json | gated ✅ |
| `/datasets/{pub}/features.geojson` | admin | **200** | application/geo+json | 3,188,593 B ✅ |
| `/datasets/{pub}/features.geojson` | **anon** | **401** | application/problem+json | gated ✅ |
| `/datasets/{priv}/features.geojson` | admin | **200** | application/geo+json | 219 B ✅ |
| `/datasets/{priv}/features.geojson` | **anon** | **401** | application/problem+json | gated ✅ |

All four formats produce real file bodies. (c) unpublished-with-auth: no draft datasets
exist; private-with-admin (closest proxy) works. (d) unpublished/private without auth:
correctly 401.

**VERDICT — vector download: WORKS.** All 4 formats serve real bytes; anon correctly blocked.

---

## 3. Vector tiles

Router `backend/app/processing/tiles/router.py`.
- Tile: `GET /tiles/{table_path:path}/{z}/{x}/{y}.pbf` (`router.py:1237`), path is `data.{table_name}`.
- Token: `GET /api/tiles/token/{dataset_id}/` (`router.py:833`).
- Batch: `POST /api/tiles/tokens/` (`router.py:885`).

Auth model (`_authorize_vector_tile_request`, `router.py:1031`):
- **public** dataset → readable directly, no signature.
- **non-public** → requires HMAC `sig`+`exp`+`scope` query params (NOT the Bearer header;
  the .pbf endpoint does not consult the Authorization header) or a valid `X-Embed-Token`.
- Token endpoint: public datasets mint a token anonymously; private require auth + RBAC.

### Live results — tokens & tiles

| Request | Auth state | HTTP | Content-Type | Bytes |
|---|---|---|---|---|
| `token/{pub}/` | anon | **200** vector token (sig) | json | — ✅ |
| `token/{pub}/` | admin | **200** vector token (same sig) | json | — ✅ |
| `token/{priv}/` | **anon** | **401** | json | gated ✅ |
| `token/{priv}/` | admin | **200** vector token (sig) | json | — ✅ |
| `data.populated_places_simple_10m/6/32/22.pbf` | anon (no sig) | **200** | application/vnd.mapbox-vector-tile | 238 ✅ |
| `data.populated_places_simple_10m/6/32/22.pbf` | admin | **200** | MVT | 238 ✅ |
| `data.populated_places_simple_10m/2/2/2.pbf` | anon | **200** | MVT | 3,621 ✅ |
| `data.sample/12/1206/1539.pbf` (NYC) | **anon, no sig** | **403** | application/problem+json | gated ✅ |
| `data.sample/12/1206/1539.pbf` | **admin Bearer, no sig** | **403** | application/problem+json | gated ✅ (header not honored — by design) |
| `data.sample/12/1206/1539.pbf?sig=…&exp=…&scope=sample` | valid sig | **200** | MVT | 94 ✅ |

**VERDICT — vector tiles: WORK.** Public served anon + auth without sig; private require a
valid HMAC sig (header-only auth correctly insufficient — that is the intended model, the
viewer obtains a sig via `token/{id}/`).

---

## 4. Frontend cross-check

`frontend/src/lib/dataset-access.ts:104` `getDatasetAccessEndpoints()` builds, for vector-like
datasets (when no explicit distribution row overrides):
- `ogcFeaturesUrl` → `/collections/{dataset.id}/items` (line 117)
- `csvExportUrl` → `/datasets/{dataset.id}/export?format=csv` (line 120)
- `vectorTilesUrl` → `/tiles/data.{table_name}/{z}/{x}/{y}.pbf` (line 124)

`frontend/src/api/datasets.ts`:
- `getExportUrl()` (line 52) → `${API_BASE}/datasets/{id}/export?format=…` — matches backend.
- `downloadExport()` (line 103) → `authenticatedDownload()` sends the Bearer header. Matches
  the auth-required `/export` route.
- `getCogDownloadUrl()` (line 65) / `downloadCog()` (line 133) → `${API_BASE}/datasets/{id}/download/cog`
  with a minted download-scoped `?token=` — modern route, matches `router_export.py:353`.

**URL-validity check (live):**

| Frontend-built URL | Resolves? |
|---|---|
| `/collections/{id}/items` (public, anon) | **200** application/geo+json (6,768 B) ✅ |
| `/collections/{id}/items` (private, anon) | **404** (correctly hidden) ✅ |
| `/collections/{id}/items` (private, auth) | **200** application/geo+json ✅ |
| `/datasets/{id}/export?format=csv` (auth) | **200** text/csv ✅ |
| `/tiles/data.{table_name}/{z}/{x}/{y}.pbf` | **200** MVT ✅ |
| `/api/datasets/{id}/download/cog` (raster connect download_url) | 200 auth / 401 anon ✅ |

Note: `/collections/{id}/items` is a real route (`/collections/{dataset_id}/items` in the
OpenAPI) distinct from the catalog feed `/collections/datasets/items`. The frontend uses the
per-dataset `{dataset_id}` form, which is correct. Trailing-slash form `/items/` → 404 (the
frontend does NOT append a trailing slash, so this is not hit).

### Legacy `/rasters/.../source.cog.tif` pattern — NOT FOUND

The user-reported legacy pattern `/api/rasters/{id}/{hash}/source.cog.tif` is **not emitted
anywhere** in the current code:
- Frontend: `grep -rn 'rasters/|source\.cog\.tif'` in `frontend/src/` → **0 URL emitters.**
- Backend raster connect `download_url` is built at
  `backend/app/modules/catalog/datasets/domain/helpers.py:85` as
  `f"/api/datasets/{dataset.id}/download/cog"` — the modern route.
- The only `source.cog.tif` references in the backend are **filesystem storage keys**
  (`processing/ingest/tasks_raster.py:444`, `processing/raster/cog.py:358`), never composed
  into a client URL.

**No mismatch found.** If a user observed a `/rasters/.../source.cog.tif` link, it is from a
stale cached bundle / old saved data, not current code.

---

## Overall verdicts

| Concern | Verdict |
|---|---|
| Vector download (csv/geojson/gpkg/shp) | **WORKS** — real file bodies, all 4 formats |
| Vector tiles (.pbf) | **WORKS** — public anon-readable, private HMAC-gated |
| Anonymous access correctly gated | **YES** — export 401 (even public, by `require_permission`); private tiles 403 w/o sig; private token 401; private OGC items 404 |
| Frontend URLs match working backend routes | **YES** — csv export, OGC items, vector tiles, COG download all resolve |
| Legacy `/rasters/.../source.cog.tif` emitter | **ABSENT** — no bug in current code |

## Bugs / observations

1. **No bug found.** All vector download/tile surfaces behave correctly and match the frontend.
2. **Design note (not a bug):** `/datasets/{id}/export` is auth-gated even for *public*
   datasets (`require_permission("export")`, `router.py:47`). An anonymous user viewing a
   public dataset cannot download CSV/GeoJSON/GPKG/SHP — they must use the anon-accessible OGC
   Features path (`/collections/{id}/items`) or vector tiles instead. If product intent is
   "public datasets downloadable by anyone," the export gate would need an anonymous-public
   branch (mirroring `download_cog`'s no-sub token path). Currently the only anon vector data
   egress for a public dataset is OGC Features / vector tiles, not the file-export formats.
3. **Minor:** `/collections/{id}/items/` (trailing slash) → 404. The frontend uses the
   no-slash form so it is unaffected, but the asymmetry is worth noting for any external
   consumer copying URLs.
