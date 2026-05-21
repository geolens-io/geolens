# Research: Ingest Column Preservation Audit

**Researched:** 2026-04-10
**Domain:** backend/app/ingest — file upload → PostGIS table → Dataset catalog
**Confidence:** HIGH (code read end-to-end; claims are file:line-anchored)

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Scope limited to `backend/app/ingest/` end-to-end (no frontend, no raster, no seeder code).
- "All columns" means every source attribute is queryable in the resulting dataset.
- Outcome is **audit + fix + tests** — not a refactor.
- `backend/tests/test_vrt_ingest_tasks.py` is explicitly out of scope.

### Claude's Discretion
- Depth of test coverage (integration preferred, unit-level acceptable).
- Format of the audit findings section in SUMMARY.md.
- Whether to extend an existing test file or create a new one.

### Deferred Ideas (OUT OF SCOPE)
- Frontend UI review.
- Raster/VRT pipeline.
- CLI seeder scripts.

---

## Summary

The ingest pipeline does NOT use any ogr2ogr column allow-list flags (`-select`, `-where`, `-fieldmap`), so at first glance columns should pass through intact. The real risks are not a single deliberate drop but a small set of quiet coercions and name-collision hazards that can make attributes silently disappear or become unusable. The biggest concrete ones I found:

1. **`-lco PRECISION=NO` is set for both file and service ingests.** Every numeric/decimal column from the source is silently converted to `double precision`. Integer-typed `numeric(p,0)` values survive by value but their declared type is lost. This is a real semantic change worth a regression test and arguably a configurability decision.
2. **Reserved-name collisions are undetected.** If a source file has a column called `gid`, `geom`, or `geom_4326`, the pipeline will either (a) let `ogr2ogr` quietly resolve the conflict and then strip the source's `gid` / `geom` downstream in `get_column_info()` (metadata.py:177), or (b) crash on `ALTER TABLE ... ADD COLUMN geom_4326 ...` (metadata.py:485) because the name already exists.
3. **Shapefile DBF 10-character truncation can silently merge fields** (e.g. `population_2020` and `population_2021` both become `population`). No detection or warning exists anywhere in the pipeline.
4. **The `get_column_info()` exclude-list is unconditional** — it always strips `gid`, `geom`, `geom_4326` from `column_info`, which is fine for internal columns but is the exact mechanism that would hide a source attribute that happened to have one of those names.

None of these currently drop columns *on purpose*, but any of them can drop or silently corrupt a column under a realistic-but-not-contrived input. The recent 7-line uncommitted change in `tasks.py` (confirmed below) is unrelated to column handling — it's a VRT visibility fix.

**Primary recommendation:** Add a small set of regression tests that load real fixture files through `run_ogr2ogr` into the test PostGIS instance, then assert every source attribute name is queryable via `get_column_info`. Cover Shapefile (DBF collision + non-ASCII), GeoJSON (reserved names, JSON/array types, date), CSV (integer, float, boolean), and GeoPackage (rich types) at a minimum.

---

## 1. Column Flow Map (file:line refs)

Upload → query path, for a file ingest:

| Step | File:Line | Operation | Column effect |
|---|---|---|---|
| 1. File hits endpoint | `backend/app/ingest/router.py:291` `upload_file` | Save staging file, magic-byte validation | None — file stream only |
| 2. Commit endpoint queues task | `backend/app/ingest/router.py:457` `commit_import` | Merges user_metadata, defers `ingest_file` | None |
| 3. Job starts, validates file | `backend/app/ingest/tasks.py:218` `ingest_file` | `validate_file_content`/`_size`/`_zip_safety` | None — content-level checks only |
| 4. `run_ogrinfo` detects CRS | `backend/app/ingest/tasks.py:287` → `ogr.py:110` `run_ogrinfo` | `ogrinfo -so -json` | Discovery only, no effect on columns |
| 5. `run_ogr2ogr` imports to PostGIS | `backend/app/ingest/tasks.py:341` → `ogr.py:295` `run_ogr2ogr` | `ogr2ogr -f PostgreSQL ... -lco FID=gid -lco PRECISION=NO -lco GEOMETRY_NAME=geom` | **FIRST opportunity to drop or coerce.** See §2 for details. |
| 6. Optional user-driven geometry construction | `tasks.py:353` `construct_point_geometry` / `:359` `construct_wkt_geometry` | `ALTER TABLE ... ADD COLUMN geom` | If the source already has a `geom` column, `ALTER ADD COLUMN geom` will fail — hard error, not a drop. See metadata.py:56 and :99. |
| 7. `ensure_geom_column` normalizes geom name | `tasks.py:108` → `metadata.py:407` `ensure_geom_column` | `ALTER TABLE ... RENAME COLUMN <name> TO geom` | **Collision hazard**: if the table already has both `geom` and `wkb_geometry`, this path renames `wkb_geometry` to `geom` and will fail with a duplicate column error. Not currently defended. |
| 8. `clip_to_mercator_bounds` | `tasks.py:114` → `metadata.py:452` | `UPDATE ... SET geom = ST_CollectionExtract(ST_Intersection(...))` | Mutates geometry rows but not columns. Safe for this audit. |
| 9. `add_4326_column` | `tasks.py:115` → `metadata.py:472` | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS geom_4326` | **Collision hazard**: source file with a `geom_4326` attribute would be no-op'd by `IF NOT EXISTS`, then the column would be overwritten on UPDATE at metadata.py:491, *and* then stripped from `column_info` at metadata.py:177. |
| 10. `grant_reader_access` | `tasks.py:118` → `metadata.py:513` | `GRANT SELECT` | None |
| 11. `extract_metadata` → `get_column_info` | `tasks.py:121` → `metadata.py:377` → `:161` | Reads `information_schema.columns` | **Unconditional exclude of `gid`, `geom`, `geom_4326`** at metadata.py:177. This is where a source attribute named one of these three literally disappears from `Dataset.column_info`. |
| 12. ArcGIS fallback if column_info is empty | `tasks.py:126-137` | Rebuild column_info from `user_metadata["source_columns"]` | ArcGIS-only; non-ArcGIS paths cannot recover. |
| 13. `get_sample_values` | `tasks.py:140` → `metadata.py:190` | Per-column distinct samples | Silently **skips** any column whose name does not match `^[a-z0-9_]+$` (metadata.py:214). Non-ASCII column names → no sample values. |
| 14. `create_dataset` persists column_info to `catalog.datasets` | `tasks.py:166` → `datasets/service.py` | Stores the filtered list | The Dataset table, Record, and all downstream UI see only what `column_info` contains. |
| 15. `refresh_attribute_metadata` (reupload only) | `ingest/tasks.py:666` → `metadata.py:717` | Marks columns no longer present as `is_current=False` | On reupload, a coercion change between old and new schema is handled gracefully; a silent drop would be recorded as "removed column." |

**Non-file ingest paths** reach the same `_finalize_ingest` helper (`tasks.py:52`) and share steps 7–14, so the same column-flow hazards apply to WFS/ArcGIS service ingests (`tasks.py:455` `ingest_service`) and to reupload flows (`tasks.py:721` `reupload_file`, `tasks.py:913` `reupload_service`).

---

## 2. Drop / Coercion Hotspots (ranked by likelihood)

### 2.1 `-lco PRECISION=NO` silently coerces all numeric types → `double precision` — HIGH likelihood

**Location:** `backend/app/ingest/ogr.py:331` (file ingest) and `:417` (service ingest).

```python
cmd = [
    "ogr2ogr", "-f", "PostgreSQL", ...,
    "-lco", "FID=gid",
    "-lco", "PRECISION=NO",   # <-- every file + service import
    ...
]
```

**Behavior per GDAL docs (PostgreSQL driver):** When `PRECISION=NO`, the GDAL PG driver writes all numeric-family fields as `FLOAT8` / `INTEGER` / `VARCHAR`, ignoring the source's declared `numeric(precision, scale)`. Sources: [GDAL PostgreSQL driver docs](https://gdal.org/en/stable/drivers/vector/pg.html), [PostGIS Intro: loading data](https://postgis.net/workshops/postgis-intro/loading_data.html).

**Concrete impact:**
- A Shapefile DBF field declared `N(18,4)` (fixed-point currency) becomes `double precision`. Values above `2^53` lose integer precision; this is rare but not impossible (e.g., very large IDs stored as numeric).
- A GeoPackage `DECIMAL(12,4)` column becomes `double precision`. Same risk.
- A column that was `numeric(8,0)` (narrow integer) becomes `double precision` with no type info — the frontend/type inference (metadata.py:577 `_infer_semantic_role` / `:_infer_domain_type`) will map it to "continuous / measure" rather than "discrete / identifier". This *is* a behavioral regression versus the default.

**Is this a drop?** No — the column and its values still exist. But the declared type is lost, and callers downstream build attribute metadata and semantic role off that type (`metadata.py:576-640`). Users who rely on exact numeric precision for IDs or currency will see a silent corruption.

**Fix direction:** Either (a) remove `-lco PRECISION=NO` and let GDAL use `numeric(width,precision)` (GDAL's actual default per RFC 94), or (b) make it configurable via a setting, or (c) explicitly document that GeoLens stores all non-integer numerics as `double precision`. The code comment does not explain why `PRECISION=NO` was set. **Worth a decision discussion with the user; treat this as an `[ASSUMED]` preference until confirmed.**

**Confidence:** HIGH (source code directly observed; GDAL behavior cited).

---

### 2.2 Reserved-name collisions with internal columns (`gid`, `geom`, `geom_4326`) — MEDIUM-HIGH likelihood

**Scenario A: source file has a field called `gid`.**
- `ogr2ogr` runs with `-lco FID=gid` (`ogr.py:329`), which asks the PG driver to materialize its own `gid` serial. If the source also has a `gid` field, GDAL's typical behavior is to *skip* the driver-generated FID column and use the source's `gid` value. The outcome is driver-version-dependent and not under GeoLens's control.
- After import, `get_column_info` unconditionally excludes `gid` (`metadata.py:177`). So the source's `gid` attribute, even if it survived the ogr2ogr import, **disappears from `Dataset.column_info`, from `sample_values`, from `attribute_metadata`, and from the Features/OGC surfaces**.

**Scenario B: source has a field called `geom` or `geometry`.**
- `run_ogr2ogr` passes `-lco GEOMETRY_NAME=geom` when the file is spatial (`ogr.py:343-349`). ogr2ogr creates the geometry column as `geom`. If the source also has a non-geometry attribute called `geom`, ogr2ogr will rename that attribute (GDAL auto-renames on collision, typically with `_1` suffix). The renamed attribute survives, but:
  - The user loses the original name and is never warned.
  - If the file is non-spatial (CSV with a text column literally named `geom`), ogr2ogr will not create a geom geometry column, and the source attribute passes through intact — but step 7 `ensure_geom_column` (`metadata.py:407`) never fires because `geometry_columns` has no row, so no collision. **This sub-case is safe**, but it's fragile: if the user later adds geometry via the CSV x/y override at `tasks.py:353`, `ALTER TABLE ... ADD COLUMN geom geometry(Point, srid)` at `metadata.py:56` will hit a hard error because the column already exists.
- Non-spatial WKT geometry construction at `metadata.py:99` has the same risk: `ADD COLUMN geom geometry(..)` fails if a same-named text column already exists.

**Scenario C: source has a field called `geom_4326`.**
- At `metadata.py:485`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS geom_4326 geometry(Geometry, 4326)` will be a **no-op** (because the column already exists with a different type). The next statement at `:491` or `:495` runs `UPDATE ... SET geom_4326 = ST_Transform(geom, 4326)` — this will **silently overwrite** the source attribute with the WGS84 reprojected geometry, and then `get_column_info` strips it from metadata. The user loses their attribute with zero signal. (If the original column was a non-geometry type, the `UPDATE` will error. If it was already a `geometry(..., 4326)` column by coincidence, the user's geometry is silently replaced with the framework's geometry.)

**Fix direction:**
- Before running ogr2ogr, probe the source with `ogrinfo` and reject/rename source fields named `gid`, `geom`, `geometry`, `geom_4326`, `fid`, `ogc_fid`. (The preview step at `ogr.py:197` already has the column list — reuse it.) The cheapest fix is to emit a warning on collision and fail the commit; the nicer fix is to auto-rename to `<name>_src` with a visible note in `collision_warning` on `user_metadata`.
- Alternatively, change `get_column_info`'s exclude set to drop only columns whose PG type actually is geometry or whose name matches the pipeline's own known internal columns via marker rather than name.

**Confidence:** HIGH (all three collision paths observed in source).

---

### 2.3 Shapefile DBF 10-character field truncation goes undetected — MEDIUM-HIGH likelihood

**Observation:** The pipeline doesn't detect or warn when multiple source fields collide after DBF 10-character truncation. The dbf format enforces a 10-char field-name limit, so `population_2020` and `population_2021` both become `population`. GDAL will auto-suffix to disambiguate (usually `population_0`, `population_1`) or, in some versions, drop the second. Either way, the user uploaded `population_2020` and `population_2021` and now has `population`, `population_1` (or worse, only `population`).

There is no code anywhere in `backend/app/ingest` that (a) reads the user-declared/original field names out of the DBF, (b) looks for collisions after truncation, or (c) surfaces a warning. The only "truncation" logic in the module is for the table name itself (`service.py:177`).

**Impact:** The `Dataset.column_info` for a Shapefile upload shows the truncated/suffixed names. The user's original schema is lost. If they used GDAL, they *expected* this (shapefile limitations are widely known); if they uploaded a zipped shapefile made by a client tool they don't control, they may never realize fields got merged/renamed.

**Fix direction:**
- At preview time or inside `ingest_file`, detect when the source is a shapefile (zip containing `.dbf`) and warn if any field exceeds 10 chars. Store the warning on `user_metadata` and surface it in the job result.
- This is a warning, not a hard fail. Shapefile users expect truncation.

**Confidence:** HIGH (code audit + GDAL shapefile driver behavior is well-established).

---

### 2.4 Unconditional exclusion of `gid`, `geom`, `geom_4326` from `column_info` — HIGH impact when it bites

**Location:** `backend/app/ingest/metadata.py:177`

```python
excluded = {"gid", "geom", "geom_4326"}
return [
    { ... }
    for row in result.all()
    if row[0] not in excluded
]
```

This is not a bug on its own — these are genuinely GeoLens-internal columns. It becomes a bug in combination with §2.2: any source attribute with one of these names is stripped from downstream metadata even if it survived ogr2ogr.

**Fix direction:** Either (a) guarantee upstream that no source attribute can ever land under one of these names (via §2.2 collision detection), or (b) track internal columns via a sentinel column comment/extended metadata rather than a blind name-based exclude list.

**Confidence:** HIGH.

---

### 2.5 `get_sample_values` silently skips columns with non-ASCII / non-lowercase names — MEDIUM likelihood

**Location:** `backend/app/ingest/metadata.py:214`

```python
# Validate column name (same safety pattern as other functions)
if not _TABLE_NAME_RE.match(col_name):
    continue
```

Where `_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")`.

**Impact:** Any column whose name contains an uppercase letter, a non-ASCII character (French `é`, German `ß`, Japanese), a hyphen, or a space is silently excluded from `sample_values`. The column itself survives in `column_info` (because `get_column_info` does not filter), but:
- `Dataset.sample_values` never has a key for it.
- `AttributeMetadata.example_values` is never populated (`metadata.py:676`).
- The attribute search and AI-metadata paths see blank samples for that field.
- Semantic role inference in `metadata.py:576` still runs off the column name, but the UX signal is broken.

A shapefile imported from a CP1252-encoded DBF *without* `-oo ENCODING=UTF-8` (which is the default, though `SHAPE_ENCODING=UTF-8` is set at `ogr.py:337` — that handles the DBF case) or an Excel sheet with localized headers can easily trip this.

**Is ogr2ogr already lowercasing?** Per GDAL PG driver, the default `LAUNDER=YES` *does* lowercase and clean attribute names on PG import. That means columns arriving at step 13 should all be `[a-z0-9_]+`. So in practice this bug only bites if `LAUNDER=YES` fails to rewrite a specific character (some Unicode edge cases). Still worth a test.

**Fix direction:** Quote the column name and accept any identifier. The safety rationale (SQL injection) is valid but is better addressed by SQL-quoting the identifier with `"..."`, not by regex-filtering.

**Confidence:** MEDIUM. The regex filter is definitely there and definitely drops samples; whether LAUNDER always saves us in practice is an untested assumption.

---

### 2.6 Timeout / row-level coercion of exotic types (JSON, arrays, booleans) — LOW-to-MEDIUM likelihood

**Observation:** ogr2ogr's PG driver maps types as follows by default:
- GeoJSON `array` → PG `text[]` (or `text` without `-emptyStringAsNull`).
- GeoJSON object → PG `jsonb` (GDAL 3.6+) or `text` (GDAL 3.5 and earlier).
- Shapefile `Logical` / `L` → PG `boolean`.
- Shapefile `Date` / `D` → PG `date`.

These all survive and are listed in `column_info`. The potential issue is in `compute_quality_score`'s per-column `COUNT(...)` scan at `metadata.py:314`:

```python
col_exprs = ", ".join(
    f'COUNT("{col["name"]}") * 100.0 / NULLIF(COUNT(*), 0) AS "s_{i}"'
    for i, col in enumerate(non_geom_cols)
)
```

`COUNT(jsonb_col)` and `COUNT(text_array_col)` both work fine in PG. No row-level issue. **This hotspot is theoretical.**

**Confidence:** LOW as an actual risk; listed here for completeness. No test needed beyond a basic "GeoJSON with an array property round-trips into `column_info`" assertion.

---

### 2.7 CSV `-oo X_POSSIBLE_NAMES=...,Y_POSSIBLE_NAMES=...` — LOW likelihood (by design)

**Location:** `backend/app/ingest/ogr.py:353-364`

```python
if is_csv and not is_non_spatial:
    cmd.extend([
        "-oo", "X_POSSIBLE_NAMES=lon*,lng*,long*,x",
        "-oo", "Y_POSSIBLE_NAMES=lat*,y",
        "-oo", "GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom,shape",
    ])
```

When ogr2ogr materializes CSV with these options, the CSV fields that matched `X_POSSIBLE_NAMES` / `Y_POSSIBLE_NAMES` become the geometry column **and are no longer loaded as separate columns** — they are consumed. This is normally what the user wants, but it is a deliberate column drop: after import, you will NOT see `lat`/`lon` as queryable columns, only as the `geom` geometry.

**This is not a bug**, but it *is* a column that a naive user might expect to still be there. Worth documenting, probably not worth changing (it's the right default for most CSVs).

**Confidence:** HIGH (documented GDAL behavior).

---

### 2.8 Exception swallowing in `compute_quality_score` — NOT a column drop

The `try/except` at `metadata.py:298-300` and `:327-329` swallows any error from quality score computation and falls back to 100.0. Columns are never modified. Not a column-preservation concern.

---

## 3. Recent `tasks.py` Change — What It Does, Relevance

**Diff:**

```diff
--- a/backend/app/ingest/tasks.py
+++ b/backend/app/ingest/tasks.py
@@ -1196,6 +1196,13 @@ async def create_vrt_dataset
         summary=summary,
         record_type="vrt_dataset",
         visibility=visibility,
+        # Mirror the vector ingest path (datasets/service.py
+        # `create_dataset_record`) and the raster ingest helper above, which
+        # commit directly to `published`.
+        # Without this a public VRT stayed in `draft`, and the anonymous
+        # raster tile-access check at tiles/router.py `_resolve_raster_access`
+        # returned 404 for every public VRT tile request.
+        record_status="published",
         updated_by=created_by,
     )
     if meta.get("bbox_wkt"):
```

**What it does:** Inside `create_vrt_dataset`, sets `record_status="published"` on the new `Record`, matching the raster ingest path at `tasks.py:1113`.

**Relevance to column preservation:** **Zero.** VRT is raster-only (out of scope for this audit per CONTEXT), and the change only affects `Record.record_status`. It does not touch `column_info`, `ogr2ogr` invocation, or any metadata extraction.

Conclusion: the change is unrelated to this task and can be ignored for the audit. It should remain as-is.

---

## 4. Existing Ingest Test Coverage

**Existing tests relevant to ingest and columns:**

| File | What it covers | Uses real ogr2ogr? |
|---|---|---|
| `backend/tests/test_ingest.py` | Upload API, CSV upload, extension validation, ArcGIS column_info fallback (line 643+). The ArcGIS test at line 643 is the only one that exercises `_finalize_ingest` and asserts on `column_info` — but it seeds a pre-created table and mocks the ogr2ogr step. | **No** — ogr2ogr is mocked, or the table is pre-created. |
| `backend/tests/test_ingest_ogr_pure.py` | Pure-Python helpers only: `detect_geometry_columns`, `_resolve_source_path`, `_extract_srid_from_json`, `_parse_text_ogrinfo`. Zero subprocess, zero DB. Fast. | No — pure unit. |
| `backend/tests/test_ensure_geom_column.py` | Tests `ensure_geom_column` with hand-constructed tables. Covers rename, noop, non-spatial table. Does NOT test collision where both `geom` and `wkb_geometry` exist. | No — CREATE TABLE directly. |
| `backend/tests/test_reupload.py` | Integration-ish: creates a Dataset directly, mocks ogrinfo_preview and ogr2ogr, verifies endpoints and schema-diff logic. | **No** — ogr2ogr mocked. |
| `backend/tests/test_reupload_service.py` | Same pattern as test_reupload for service reupload. | No — mocked. |
| `backend/tests/test_raster_ingest.py` | Raster, out of scope. | — |
| `backend/tests/test_vrt_ingest_tasks.py` | VRT, out of scope. | — |

**Gap:**
- **No test anywhere in `backend/tests` actually runs `ogr2ogr` against a real fixture file.** Every ingest test either mocks `run_ogr2ogr` / `run_ogr2ogr_service`, or CREATEs the target table directly via SQL and then calls `_finalize_ingest` or metadata helpers.
- **No test asserts that every source attribute from a file is queryable after import.** The closest thing is the ArcGIS fallback test (test_ingest.py:643), which checks column_info length and names, but it bypasses ogr2ogr entirely — it seeds `user_metadata["source_columns"]` by hand.

**Environment note:** `ogr2ogr` is NOT installed on the dev host (`which ogr2ogr` fails). It is installed in the backend Docker image via `backend/Dockerfile:16` (`apt-get install gdal-bin`). So any test that uses real ogr2ogr must be skipped when the binary is missing, or must be run exclusively inside the Docker test environment.

---

## 5. Recommended Test Harness for Column-Preservation Regression Tests

**Core idea:** Write tests that (1) ship a small real fixture file committed to the repo, (2) call `run_ogr2ogr` against the existing `test_db_session` PostGIS, and (3) use `get_column_info` + raw SQL to assert every source attribute name is queryable. Skip the whole file when `ogr2ogr` is not on PATH.

**Proposed structure:**

```
backend/tests/
├── test_ingest_column_preservation.py     # new file
└── fixtures/
    └── ingest/                            # new directory
        ├── basic_attrs.geojson            # ~3 features, mixed types
        ├── reserved_names.geojson         # has fields named 'gid', 'geom_4326'
        ├── unicode_attrs.geojson          # has fields 'Nom', 'Größe', 'Área'
        ├── numeric_precision.geojson      # has decimal(12,4), int64, float
        ├── dbf_collision.zip              # shapefile with 'population_2020' + 'population_2021'
        └── mixed_types.csv                # has bool, date, int, float, text
```

**Test shape:**

```python
# backend/tests/test_ingest_column_preservation.py
import shutil
import pytest
from pathlib import Path
from sqlalchemy import text

from app.ingest.metadata import get_column_info
from app.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo

pytestmark = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None,
    reason="ogr2ogr binary not available on host (runs in backend Docker image)",
)

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


async def _load_and_get_columns(test_db_session, fixture: str, table: str):
    """Run the real ogr2ogr and return (column_info, raw_column_names)."""
    info = await run_ogrinfo(str(FIXTURES / fixture))
    await run_ogr2ogr(
        str(FIXTURES / fixture),
        table,
        build_pg_conn_str(),
        source_srid=info.get("srid"),
        geometry_type=info.get("geometry_type"),
    )
    # What the catalog will see:
    filtered = await get_column_info(test_db_session, table)
    # What PostGIS actually has (source of truth, no filters):
    raw = await test_db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='data' AND table_name=:t ORDER BY ordinal_position"
        ),
        {"t": table},
    )
    return filtered, [r[0] for r in raw.all()]


class TestGeojsonBasicAttrs:
    async def test_all_source_fields_present_in_column_info(self, test_db_session):
        table = f"tst_basic_{uuid.uuid4().hex[:8]}"
        try:
            cols, raw = await _load_and_get_columns(
                test_db_session, "basic_attrs.geojson", table
            )
            # Source has fields: name, population, area_km2, is_capital, founded
            names = {c["name"] for c in cols}
            assert {"name", "population", "area_km2", "is_capital", "founded"} <= names
        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()


class TestReservedNameCollision:
    """Regression for §2.2: source fields named gid/geom/geom_4326."""
    async def test_source_field_named_gid_is_not_silently_dropped(
        self, test_db_session
    ):
        # CURRENT BEHAVIOR: probably gets stripped by get_column_info.
        # EXPECTED BEHAVIOR (after fix): renamed to gid_src and preserved.
        ...
```

**Why this harness is the right fit:**

1. **No new infrastructure.** Reuses `test_db_session`, already wired to a real PostGIS via `conftest.py:314`. Reuses `run_ogr2ogr` and `build_pg_conn_str` as-is — no monkey-patching — so the tests exercise the exact code path that runs in production.
2. **Fixtures are tiny and committed.** A 3-feature GeoJSON is ~500 bytes. A shapefile zip is ~5 KB. No docker build, no CI bandwidth cost.
3. **Skips cleanly on hosts without ogr2ogr.** `pytest.mark.skipif(shutil.which('ogr2ogr') is None, ...)` means the tests no-op on the dev laptop and run fully inside the backend Docker container or in CI when GDAL is installed.
4. **Fast.** Each test is one ogr2ogr invocation (tens of milliseconds) + one `information_schema.columns` query. The whole file should run in under 2 seconds.
5. **Covers each file format once**, as the focus block requires: GeoJSON (basic + reserved-name + unicode + numeric), CSV (mixed types), Shapefile zip (DBF collision). GeoPackage and FGB can be added in a follow-up if needed.

**Table-naming convention:** `tst_<name>_<uuid_hex_8>` so parallel runs don't collide; drop in `finally`.

**Alternate: pure-unit tests for `get_column_info` exclude behavior.** Cheap to add alongside the integration tests — create a data-schema table via `CREATE TABLE data.foo (gid serial, name text, geom_4326 text)` and assert `get_column_info` returns only `name`. This pins the current exclude behavior so any fix is forced to be intentional.

---

## 6. Known GDAL/ogr2ogr Lossless-Translation Gotchas Worth Defending

| Gotcha | How it manifests | GeoLens defense today | Recommended defense |
|---|---|---|---|
| `PRECISION=YES` (default) vs `NO` — numeric precision | `DECIMAL(12,4)` → `double precision` with `NO` | Always `NO` (`ogr.py:331`, `:417`) | Decision point; see §2.1 |
| DBF 10-char field truncation | `population_2020` + `population_2021` → collision | None | Preview-time warning |
| DBF encoding (CP1252 vs UTF-8) | Non-ASCII column names become `?` or mojibake | `SHAPE_ENCODING=UTF-8` at `ogr.py:337` — handles data but not schema | Add `-oo ENCODING=UTF-8` for completeness |
| `LAUNDER=YES` (default) silently renames `Foo Bar` → `foo_bar` | User uploads `First Name`, sees `first_name` | No warning | Document; not a drop but a rename users don't expect |
| GeoJSON property types: object → jsonb or text depending on GDAL version | GDAL 3.5 vs 3.7 difference | None | Pin GDAL version in Dockerfile (already via apt; check version) |
| `-preserve_fid` not set | ogr2ogr assigns new FIDs, source FID is lost | Not used | Acceptable for most sources, but a Shapefile with a meaningful `FID` column loses it |
| `-mapFieldType` for int64 → double on unsupported drivers | Not relevant for PostgreSQL driver | — | No action |
| `-skipfailures` not set | A single bad row aborts the whole import | Not set — good, fail-loud | Keep fail-loud |
| `X_POSSIBLE_NAMES` / `Y_POSSIBLE_NAMES` consume CSV fields into geometry | `lat`/`lon` disappear from column_info after CSV import | Documented above | Acceptable default |
| GeoPackage multiple layers, user picks wrong one | Metadata is for wrong layer | `layer_name` commit param supported at `tasks.py:284` | Good — already handled |

---

## 7. Open Questions / Assumptions to Lock With the Planner

1. **`PRECISION=NO` is intentional vs. historical.** The code has no explanatory comment. Was this a deliberate decision to avoid PG `numeric` quirks, or a legacy copy-paste from a GDAL tutorial? **Recommendation:** ask the user. If intentional, add a comment in `ogr.py:331`. If unintentional, remove it and add a test for numeric precision round-trip. Until confirmed, treat the "remove PRECISION=NO" option as `[ASSUMED]` and do NOT ship the change without sign-off.
2. **Reserved-name collision policy.** When a source file has a `gid` / `geom` / `geom_4326` field, should the pipeline (a) reject the upload with a clear error, (b) auto-rename to `<name>_src` and warn, or (c) keep current silent behavior?  **Recommendation:** (b) auto-rename with a `collision_warning` in `user_metadata` — matches the existing pattern at `service.py:209`. Needs user confirmation.
3. **DBF truncation warning policy.** Warn-only (job proceeds) or fail-loud? **Recommendation:** warn-only, attached to `user_metadata.warnings`. Shapefile users expect truncation; blocking them would be surprising.
4. **Unicode / non-ASCII column sample-value gap.** Is it worth widening the identifier regex in `get_sample_values` (`metadata.py:214`) to accept `[a-zA-Z0-9_\-]`, or quote identifiers properly? **Recommendation:** switch to SQL identifier quoting; regex is not the right tool for SQL-injection defense when the same codebase already uses quoted identifiers elsewhere (e.g., `metadata.py:34` `_qtable`).
5. **Test environment.** Confirmed: `ogr2ogr` runs inside the backend Docker image; the test harness should `skipif` on the dev host and run the full suite in Docker. Does the planner want tests added to the default CI run? (Assumed yes — they're fast.)
6. **How "correct" should column preservation be?** For CSV, the `X_POSSIBLE_NAMES` auto-detection (§2.7) intentionally consumes lat/lon columns. Is that a "silent drop" the user wants fixed, or the expected behavior we should just document? **Recommendation:** document, do not change.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | `PRECISION=NO` was set deliberately and removing it would be a decision, not an unambiguous fix | §2.1, §7.1 | Mislabeling an obvious bug as a decision; small — both options are defensible |
| A2 | Reserved-name collision auto-rename is the preferred fix over hard-fail | §2.2, §7.2 | Policy mismatch with user preference; small — easy to flip |
| A3 | `LAUNDER=YES` (GDAL default) saves the `get_sample_values` regex filter in all practical cases, so §2.5 bites rarely | §2.5 | May understate the real frequency of non-ASCII drops; medium — worth a targeted test |
| A4 | Tests that require real `ogr2ogr` are acceptable to run only inside Docker or on CI with GDAL installed | §5 | If CI doesn't install GDAL the tests become silent no-ops; small — CI already installs GDAL per Dockerfile |
| A5 | The recent uncommitted 7-line change in `tasks.py` (VRT `record_status="published"`) is unrelated to column preservation and should be left alone | §3 | Zero — diff confirmed, only touches raster path |

---

## Sources

### Primary (HIGH confidence) — verified by direct code read
- `backend/app/ingest/ogr.py` (`run_ogr2ogr`, `run_ogr2ogr_service`, `detect_geometry_columns`)
- `backend/app/ingest/metadata.py` (`get_column_info`, `get_sample_values`, `ensure_geom_column`, `add_4326_column`, `_validate_table_name`)
- `backend/app/ingest/tasks.py` (`_finalize_ingest`, `ingest_file`, `ingest_service`, `reupload_file`, `reupload_service`)
- `backend/app/ingest/service.py` (`generate_table_name`, `register_existing_table`)
- `backend/app/ingest/validation.py` (`validate_file_content`, `validate_zip_safety`)
- `backend/app/ingest/router.py` (`upload_file`, `commit_import`, `preview_file`)
- `backend/app/datasets/service.py:123-230` (`column_info` persistence)
- `backend/tests/test_ingest.py`, `test_ingest_ogr_pure.py`, `test_ensure_geom_column.py`, `test_reupload.py`, `test_reupload_service.py`, `conftest.py`
- `backend/Dockerfile:15-19` (`gdal-bin` installation)

### Secondary (MEDIUM confidence) — web-verified GDAL documentation
- [GDAL PostgreSQL driver: layer creation options](https://gdal.org/en/stable/drivers/vector/pg.html) — documents `PRECISION=YES/NO`, `LAUNDER`, `FID`, `GEOMETRY_NAME`
- [GDAL PostgreSQL SQL Dump driver](https://gdal.org/en/stable/drivers/vector/pgdump.html) — shares layer creation options with the PG driver
- [PostGIS Intro: Loading Data](https://postgis.net/workshops/postgis-intro/loading_data.html) — shows `-lco PRECISION=NO` usage in the wild
- [GDAL ogr2ogr program docs](https://gdal.org/en/stable/programs/ogr2ogr.html) — `-select`, `-fieldmap`, `-preserve_fid`, `-mapFieldType`
- [GDAL CSV driver docs](https://gdal.org/en/stable/drivers/vector/csv.html) — `X_POSSIBLE_NAMES`, `Y_POSSIBLE_NAMES`, `GEOM_POSSIBLE_NAMES`
- [GDAL Issue #3345: Integer columns converted to numeric with OGRSQL](https://github.com/OSGeo/gdal/issues/3345) — context on PRECISION handling
- [GDAL RFC 94: Numeric fields width/precision metadata](https://gdal.org/en/stable/development/rfc/rfc94_field_precision_width_metadata.html) — how GDAL tracks precision in-memory

### Environment notes
- Host `ogr2ogr`: NOT installed (confirmed via `which ogr2ogr`)
- Docker image `ogr2ogr`: installed via `apt-get install gdal-bin` (`backend/Dockerfile:15-19`)

---

## Metadata

**Confidence breakdown:**
- Column flow map: HIGH — every step verified against source.
- Drop/coercion hotspots: HIGH for §2.1–§2.5; LOW for §2.6; HIGH for §2.7 as documented behavior.
- Recent tasks.py change analysis: HIGH — diff inspected, unrelated to audit.
- Existing test coverage: HIGH — exhaustive grep across `backend/tests/`.
- Recommended test harness: HIGH — leverages existing `test_db_session` fixture; Docker environment verified.

**Research date:** 2026-04-10
**Valid until:** 2026-05-10 (30 days — ingest pipeline is stable, GDAL releases are slow)
