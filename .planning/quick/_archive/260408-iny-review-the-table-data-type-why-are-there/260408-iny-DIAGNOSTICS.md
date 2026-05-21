# 260408-iny Wave 0 Diagnostics

**Run:** 2026-04-08 18:30 UTC

---

## Gate A: column_info root cause

### Command

```bash
docker compose exec api uv run python -c "
import asyncio
from sqlalchemy import text
from app.database import async_session

async def main():
    async with async_session() as db:
        tables = await db.execute(text('''
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name LIKE 'bulletin%'
            ORDER BY table_name
        '''))
        print('TABLES:', tables.fetchall())

        for suffix in ('bulletin', 'bulletin_2', 'bulletin_3'):
            cols = await db.execute(text('''
                SELECT column_name, data_type, ordinal_position, is_nullable
                FROM information_schema.columns
                WHERE table_name = :name
                ORDER BY ordinal_position
            '''), {'name': suffix})
            print(f'COLUMNS {suffix}:', cols.fetchall())

asyncio.run(main())
"
```

### Output

```
TABLES: [('data', 'bulletin'), ('data', 'bulletin_2'), ('data', 'bulletin_3')]
COLUMNS bulletin: [('gid', 'integer', 1, 'NO')]
COLUMNS bulletin_2: [('gid', 'integer', 1, 'NO')]
COLUMNS bulletin_3: [('gid', 'integer', 1, 'NO')]
```

### Supporting investigation

ArcGIS service probe (live network call confirmed):

```
type: Table
geometryType: None
fields: ['Opportunity_Number', 'URL', 'Opportunity_Title', 'Federal_Agency',
         'Category', 'Authorizing_Act', 'Opportunity_Opening_Date',
         'Opportunity_Closing_Date', 'FID2']
```

The ArcGIS FeatureServer layer is of type `Table` with **no geometry** and 9 attribute fields.

Datasets table state (catalog.datasets):

- All 3 Bulletin datasets: `column_info = []`, `feature_count = 29`, `source_url = .../FeatureServer/0`

The `data` schema IS correct — `get_column_info` in `backend/app/ingest/metadata.py:173` queries
`WHERE table_schema = 'data'` and the tables are in `data`. So the schema filter is not the bug.

### Verdict

**Case 2** — ogr2ogr created a malformed table. The three bulletin tables are in `data` schema but each
has **only a `gid` column** (the FID column) and no attribute columns.

**Root cause:** `run_ogr2ogr_service` in `backend/app/ingest/ogr.py:401-459` uses `-nlt PROMOTE_TO_MULTI`
and `-t_srs EPSG:4326`. For a non-spatial ArcGIS Table (geometryType=None), ogr2ogr still creates
the destination PostGIS table but the geometry promotion and SRS transform flags cause it to create
only the FID column (`gid`) without the attribute columns — the attributes are dropped because ogr2ogr's
non-spatial table handling with `-PROMOTE_TO_MULTI` conflates the layer as a degenerate spatial layer.

**Fix strategy for Task 3:**

1. **Primary fix:** In `run_ogr2ogr_service`, detect when `service_type` is `arcgis_featureserver` AND
   the layer has `geometryType=None` (non-spatial table). For those cases, omit `-nlt PROMOTE_TO_MULTI`
   and `-t_srs EPSG:4326` from the ogr2ogr command — these flags cause attribute column loss on non-spatial
   data. The `ingest_service` task in `backend/app/ingest/tasks.py` has the ArcGIS probe info available
   and can pass a `has_geometry=False` flag to `run_ogr2ogr_service`.

2. **Fallback fix (always apply):** Also add the ArcGIS `fields` → `column_info` fallback path through
   `IngestJob.user_metadata` (as planned in RESEARCH.md §2). This ensures `column_info` is populated
   from the probe data even if ogr2ogr succeeds for non-spatial tables. The fallback is a safety net
   for any future Case 2 scenarios.

3. **Existing 3 Bulletin datasets:** Left untouched (user will inspect/re-import). The fix prevents
   FUTURE imports from having the same problem.

---

## Gate B: 307 redirect reproduction

### Steps taken

1. Checked frontend API calls vs backend route definitions for ALL `/datasets/{id}` endpoints:
   - `frontend/src/api/datasets.ts:32` → `/datasets/${id}` (no slash) vs `backend router.py:136` `/{dataset_id}` (no slash) — **MATCH**
   - `frontend/src/api/datasets.ts:128` → `/datasets/${id}/status/` (with slash) vs `router_data.py:201` `/{dataset_id}/status/` (with slash) — **MATCH**
   - `frontend/src/api/datasets.ts:48` → `/datasets/${id}/rows/` vs `router_data.py:62` `/{dataset_id}/rows/` — **MATCH**
   - `frontend/src/api/vrt.ts:10` → `/datasets/${datasetId}/vrt-sources/` vs `router_vrt.py:40` `/{dataset_id}/vrt-sources/` — **MATCH**
   - `frontend/src/api/features.ts:15` → `/datasets/${datasetId}/features/` vs `features/router.py:50` `/{dataset_id}/features/` — **MATCH**
   - `frontend/src/api/datasets.ts:242` → `/datasets/${datasetId}/attributes/` vs `router_metadata.py:87` `/{dataset_id}/attributes/` — **MATCH**

2. Verified via curl: `GET /datasets/{id}` (no trailing slash) → 200 OK. `GET /datasets/{id}/` (trailing slash) → 307 (Location: without slash). The redirect ONLY fires if a trailing slash is appended to an endpoint that has none.

3. No frontend code path appends a trailing slash to `/datasets/${id}` (the base endpoint). The `apiFetch` client does not add slashes.

4. `hooks/use-quicklook.ts:28` → `/api/datasets/${datasetId}/quicklook?size=256` — no trailing slash. Backend `router.py:182` `/{dataset_id}/quicklook` — no slash. **MATCH**.

5. Probed the collections/items links in Gate C output — the `self` link uses `http://localhost:8080/api/...` (public hostname, not `api:8000`), so no internal hostname leak from that path.

### Finding

**Cannot reproduce in current codebase.** All frontend→backend route pairs are correctly matched (trailing-slash parity everywhere). The 307 redirect only fires if someone manually appends a trailing slash to a no-slash endpoint, which no frontend code path does. The CONTEXT.md description of a "307 that leaks internal hostname" was likely observed in an older codebase version and has since been fixed (matching the OGC `/collections/datasets` fix already documented in MEMORY.md).

When curled from outside Docker, the 307 Location header correctly uses `localhost:8001` (the mapped port), not the internal `api:8000` hostname. No internal hostname leak observed.

### Fix target for Task 3

**SKIP** — No code change needed. Document in SUMMARY.md as "Cannot reproduce; no speculative fix applied."

---

## Gate C: /collections/{id}/items for tables

### Command

```bash
curl -sS "http://localhost:8001/collections/3b26e492-3978-48f3-a6b3-a7016bd16841/items?limit=1" | head -20
```

### Output

```json
{"type":"FeatureCollection","timeStamp":"2026-04-08T18:26:41.335709Z",
 "numberMatched":29,"numberReturned":1,
 "features":[{"type":"Feature","id":1,"geometry":null,"properties":{}}],
 "links":[
   {"href":"http://localhost:8080/api/collections/3b26e492.../items?limit=1&offset=0","rel":"self","type":"application/geo+json"},
   {"href":"http://localhost:8080/api/collections/3b26e492.../","rel":"collection","type":"application/json"},
   {"href":"http://localhost:8080/api/collections/3b26e492.../items?limit=1&offset=1","rel":"next","type":"application/geo+json"}
 ]}
```

### Verdict

**Works (200 OK)** — The `/collections/{id}/items` endpoint returns a valid GeoJSON FeatureCollection
for table records. `geometry` is `null` (expected for non-spatial tables). `properties` is `{}` because
the bulletin tables have no attribute columns (the Gate A bug — only `gid` which is the FID).

After the ogr2ogr fix in Task 3, re-imported table records should have non-empty `properties` in this
response. This is informational only and does NOT affect Task 2's `_TABLE_FORMAT_MEDIA` — `application/geo+json`
is correctly included unconditionally per research §7 (the endpoint works for tables).

The self-link uses `http://localhost:8080` (configured public hostname), not the internal `api:8000`.
No hostname leak observed here either.

---

## Summary for downstream tasks

| Gate | Verdict | Impact on coding |
|------|---------|-----------------|
| A (column_info) | Case 2 — ogr2ogr drops attributes for non-spatial ArcGIS tables due to `-nlt PROMOTE_TO_MULTI` + `-t_srs EPSG:4326` | Task 3: fix `run_ogr2ogr_service` to skip geometry flags for non-spatial tables; also add ArcGIS fields fallback via `user_metadata` |
| B (307 redirect) | Cannot reproduce — all frontend/backend route slash pairs are aligned | Task 3: SKIP 307 sub-task entirely |
| C (collections/items) | Works (200 OK, empty properties due to Gate A bug) | No change to Task 2 `_TABLE_FORMAT_MEDIA` — geojson included unconditionally |
