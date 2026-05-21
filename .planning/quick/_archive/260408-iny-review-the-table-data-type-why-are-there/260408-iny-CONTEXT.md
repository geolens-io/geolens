---
name: 260408-iny Context
description: Locked decisions for Table data type review + enhancement quick task
type: quick-task-context
---

# Quick Task 260408-iny: Table Data Type Review — Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Task Boundary

Review the `table` record_type in GeoLens. Diagnose why the local database contains 3 duplicate "Bulletin" tables, decide on a thumbnail strategy for tables, and identify/fix gaps and easy wins. Per user direction, this is a **full enhancement pass** — not just a review doc.

</domain>

<diagnosis>
## Live Investigation Findings (via Playwright MCP)

### The 3 "duplicates" — actual data

All 3 are identical except for UUIDs and `table_name` suffixes:

| # | id | table_name | created_at |
|---|----|-----------|------------|
| 1 | `3b26e492-3978-48f3-a6b3-a7016bd16841` | `bulletin`   | 2026-03-31T19:10:20.517907Z |
| 2 | `0bb3372b-331a-43c2-bb9b-bef26f5aa069` | `bulletin_2` | 2026-03-31T19:10:22.426968Z |
| 3 | `da315ee0-0bca-4e75-8f29-3c1f4654a248` | `bulletin_3` | 2026-03-31T19:10:24.092717Z |

**Identical fields across all 3:**
- `title`: "Bulletin"
- `summary`: "Initial creation 11/6/23"
- `feature_count`: 29
- `source_format`: `arcgis_featureserver`
- `source_filename`: "Bulletin"
- `source_url`: `https://services6.arcgis.com/EbVsqZ18sv1kVJ3k/arcgis/rest/services/Funding_Opportunities_Table_Data/FeatureServer/0`
- `created_by`: `30c19df6-52c3-404b-aee9-04f433b83df1` (admin)
- `column_info`: `[]` (empty!)
- `geometry_type`, `extent_bbox`, `srid`: all `null`

**Root cause:** The ArcGIS FeatureServer registration flow does not check whether a dataset with the same `source_url` already exists. The user triggered the same ingest 3 times (roughly 2 seconds apart) and got 3 identical records with auto-suffixed table names. The backend's auto-suffix logic is masking an idempotency bug — it's trying to "help" by making the import succeed, when it should instead detect the duplicate and refuse/warn/return existing.

### Additional bugs surfaced during investigation

1. **`column_info` is empty `[]`** for all 3 Bulletin tables. The ArcGIS ingest path is not populating column metadata even though ArcGIS exposes `fields` in its service JSON. This is unrelated to the duplicate issue but affects the same code path.

2. **Quality score inflation for tables** (`quality_detail`):
   - `geometry_validity`: 100 (but there IS no geometry — should be N/A/skipped)
   - `crs_defined`: 100 (but `srid` and `crs` are `null` — should be N/A/skipped)
   - `metadata_completeness`: 10 (honest — all metadata null)
   - `attribute_completeness`: 100
   - `overall`: 73 (inflated by meaningless 100s from skipped dimensions)
   Tables should not be scored on geometry/CRS dimensions at all; overall should compute from applicable dimensions only.

3. **307 redirect leaks internal hostname** — Frontend calls `/api/datasets/{id}/` (trailing slash) and the route is defined WITHOUT trailing slash. FastAPI returns a 307 to `http://api:8000/datasets/{id}` (the internal docker hostname, unreachable from browser). Affects DatasetDetail page load. This is the exact pattern that's already documented in memory for OGC `/collections/datasets` — a second instance.

4. **Misleading `feature_count` field for tables** — The OGC Records search response exposes `"feature_count": 29` for tables. Tables have ROWS, not features. The UI already displays "29 rows" but the underlying field name is confusing API consumers. Either rename or add a `row_count` alias in the response.

5. **Formats list advertises incompatible formats** — Tables advertise `application/geo+json` and `application/x-shapefile` downloads which don't make sense for non-spatial data. Only `text/csv` and `application/geopackage+sqlite3` are appropriate.

6. **Thumbnail is the generic "image missing" icon** — Every Table card in the search results shows the gray `ImageOff` placeholder that visually reads as "this is broken" rather than "this has no visual preview". See `before-table-filter.png`.

7. **`distributions` list includes OGC Features link** for tables — `/api/collections/{id}/items` works for tables (treats them as non-spatial features) but may confuse users since the collection isn't spatial.

</diagnosis>

<decisions>
## Implementation Decisions

### Scope (LOCKED by user)
- **Full enhancement pass** — diagnose, fix duplicates root cause, implement thumbnail system, add all P1/P2 improvements identified during review.
- Not "review doc only"; the task ships working code.

### Thumbnail strategy (LOCKED by user)
- **Styled icon tile** — Replace the `ImageOff` placeholder for tables with a styled tile that visually communicates "this is a table" rather than "this is broken".
- Implementation: Frontend-only. A distinct background (orange gradient matching the Table badge color from `status-colors.ts`) with the `Table2` lucide icon, and a row/column count overlay (e.g., "29 rows · 5 cols").
- No backend changes for thumbnails. No generated PNG, no SVG mini-spreadsheet, no manual upload support. Keep the surface area minimal.

### Duplicate detection strategy (Claude's discretion)
- **Backend must detect duplicates by `source_url` + `source_format` + `created_by`** during ArcGIS service registration.
- Default behavior: **refuse with 409 Conflict** and a structured error body containing the existing dataset id. This forces the client to make an explicit choice.
- Do NOT change the auto-suffix logic for actual table name collisions (that's a different concern for physical PostgreSQL table names).
- Existing 3 Bulletin duplicates should be cleaned up via a follow-up manual step — this task will NOT automatically delete them (user data is sacred, plus the user may want to inspect before deleting).
- Cover other ingest paths too (file upload, bulk register) if they share the same root cause — check during research.

### Column introspection fix (Claude's discretion)
- Fix the empty `column_info` for ArcGIS table registrations. ArcGIS services expose `fields` in their service JSON — that should be mapped to the column_info schema during registration.

### Quality scoring fix (Claude's discretion)
- For `record_type='table'`, skip `geometry_validity` and `crs_defined` from the quality score entirely. Recompute `overall` from applicable dimensions only.
- Backfill: do NOT re-run scoring for all existing datasets. Just fix forward. Existing scores can be corrected on next edit.

### 307 redirect fix (Claude's discretion)
- Frontend fix: drop trailing slash in `/api/datasets/{id}/` calls (match the backend route definition).
- Match the existing pattern in memory for OGC (`/collections/datasets` without trailing slash).

### feature_count aliasing (Claude's discretion)
- Add `row_count` as an alias in the OGC Records response for `record_type='table'` (copy value from `feature_count`). Do NOT remove `feature_count` from the response — that would break existing consumers.
- Frontend search card already renders "rows" for tables, so this is a documentation/API ergonomic fix.

### Formats list (Claude's discretion)
- Strip incompatible formats from the `formats` list for tables. Only emit formats actually supported for non-spatial data: `text/csv`, `application/geopackage+sqlite3`, and `application/geo+json` is OK if the backend accepts it for non-spatial collections (verify in research). Shapefile MUST be dropped.

### Schema documentation fix (Easy win)
- Update `DatasetResponse.record_type` field description in `backend/app/datasets/schemas.py:234-236` to list all valid values.

### Claude's Discretion — explicitly out of scope
- Vector/raster thumbnail pipeline changes (keep isolated to tables)
- Backfilling quality scores for all datasets
- Auto-deleting the 3 Bulletin duplicates
- Changes to map/collection/service record types
- OGC Collections facet exposure (P3 from scout — defer)
- Documentation site updates (FEATURES.md, README) — defer
- Empty state for DataTab (separate concern from search/listing)

</decisions>

<specifics>
## Specific Ideas & References

- **ArcGIS `fields` endpoint example**: `GET {service_url}?f=json` returns `{ fields: [{ name, type, alias, length, nullable, ... }] }`. The registration code at `backend/app/services/arcgis.py` already fetches this — the fix is to propagate `fields` → `column_info`.
- **Quality scoring location**: Likely in `backend/app/datasets/service.py` or a dedicated quality module. Research should find it.
- **Duplicate detection location**: `backend/app/ingest/router.py` bulk_register_tables and the FeatureServer registration endpoint. Research should map them.
- **Thumbnail placeholder file**: `frontend/src/components/search/SearchResultCard.tsx:312-315` (confirmed by scout).
- **Table badge color**: `frontend/src/lib/status-colors.ts:59` — orange — use as the tile background gradient source.

</specifics>

<canonical_refs>
## Canonical References

- **Live investigation screenshots** (committed with this task):
  - `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/before-3-duplicates.png`
  - `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/before-table-filter.png`
- **API data dump** (see `<diagnosis>` section above — captured via Playwright `/api/search/datasets/?record_type=table` and `/api/datasets/{id}`)
- **Related prior scout**: The Explore agent's initial report identified ~11 items across P1–P4 tiers; this CONTEXT.md narrows those to the in-scope set.
- **FastAPI trailing slash pattern**: Already documented in memory (`MEMORY.md` → Known Issues) for the OGC `/collections/datasets` route — same fix pattern applies here.

</canonical_refs>
