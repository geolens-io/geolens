---
phase: quick-260322-ndc
verified: 2026-03-22T21:30:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "CSV/XLSX with lat/lng columns auto-detected and imported as spatial point datasets"
    status: partial
    reason: "detect_geometry_columns preserves original column case (e.g. 'Latitude'), but construct_point_geometry and construct_wkt_geometry validate column names with _TABLE_NAME_RE = ^[a-z0-9_]+$, which rejects any column name with uppercase letters or non-alphanumeric characters. A CSV with columns named 'Latitude'/'Longitude' or 'WKT' (common in real-world files) will fail at the geometry construction step with ValueError('Invalid column name'), causing the ingest job to fail."
    artifacts:
      - path: "backend/app/ingest/metadata.py"
        issue: "_TABLE_NAME_RE regex (^[a-z0-9_]+$) used to validate column names at lines 46 and 81 rejects mixed-case column names that detect_geometry_columns correctly returns in original case"
      - path: "backend/app/ingest/ogr.py"
        issue: "detect_geometry_columns docstring says 'Returns original case' but original-case names fail the column name validation downstream"
    missing:
      - "Lowercase the x_column/y_column/geom_column before passing to construct_point_geometry/construct_wkt_geometry in tasks.py, OR relax the column name regex to allow uppercase (add A-Z to _TABLE_NAME_RE pattern for column validation), OR quote column names with double-quotes in the SQL statements instead of using _TABLE_NAME_RE"
---

# Quick Task 260322-ndc: Geometry Column Detection Verification

**Task Goal:** Non-spatial table support — support import of CSV/XLSX with geometry columns (lat/lng, WKT auto-detection with user override). Non-spatial tables as full catalog entries. GDAL for both CSV and XLSX parsing.
**Verified:** 2026-03-22T21:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | CSV/XLSX with lat/lng columns auto-detected and imported as spatial point datasets | PARTIAL | Detection works; column name validation rejects uppercase names in construct_point_geometry |
| 2 | CSV/XLSX with WKT columns auto-detected and imported as spatial datasets | PARTIAL | Same issue: WKT column name validation rejects uppercase (e.g. "WKT") in construct_wkt_geometry |
| 3 | User can override auto-detected geometry columns in the upload form | VERIFIED | ImportMetadataForm.tsx has full geometry override UI wired to x_column/y_column/geom_column in CommitImportRequest |
| 4 | XLSX with lat/lng uses post-import ST_MakePoint (GDAL XLSX driver lacks X/Y open options) | VERIFIED | tasks.py lines 154-159: construct_point_geometry called when not has_geometry and x_column/y_column set; metadata.py uses ST_MakePoint |
| 5 | Files with no geometry columns import as non-spatial tables (record_type='table') | VERIFIED | ogr2ogr skips spatial flags when geometry_type is None; record_type='table' handled by prior phase (NDC dependency) |

**Score:** 4/5 truths verified (Truths 1 and 2 are the same root-cause gap)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/ingest/schemas.py` | CommitRequest with x_column, y_column, geom_column; PreviewResponse with detected_geometry_columns | VERIFIED | Lines 59-61: x_column/y_column/geom_column added. Line 25: detected_geometry_columns added |
| `backend/app/ingest/ogr.py` | detect_geometry_columns function, broadened GEOM_POSSIBLE_NAMES | VERIFIED | Lines 24-38: function exists, correct pattern matching; line 347: GEOM_POSSIBLE_NAMES=WKT,wkt,geometry,geom,the_geom,shape added to CSV ogr2ogr call |
| `backend/app/ingest/tasks.py` | Post-import geometry construction via ST_MakePoint and ST_GeomFromText | VERIFIED (conditional) | Lines 154-173: geometry construction wired; ST_MakePoint called via construct_point_geometry. Gap: uppercase column names fail |
| `backend/app/ingest/metadata.py` | construct_point_geometry and construct_wkt_geometry functions | VERIFIED (with gap) | Functions exist at lines 34-109; use ST_MakePoint and ST_GeomFromText correctly but column validation regex is too strict |
| `frontend/src/components/import/ImportMetadataForm.tsx` | Geometry column override UI with x/y/WKT dropdowns | VERIFIED | Full UI at lines 203-325: mode selector (auto/manual/none), lat/lng vs WKT radio, column dropdowns from previewColumns |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/ingest/router.py` | `PreviewResponse.detected_geometry_columns` | detect_geometry_columns called in preview_file endpoint | WIRED | Lines 389-407: detect_geometry_columns imported (line 18) and called when geometry_type is None and columns present |
| `backend/app/ingest/tasks.py` | PostGIS ST_MakePoint / ST_GeomFromText | construct_point_geometry / construct_wkt_geometry after ogr2ogr | WIRED (conditional) | Lines 154-173: correct control flow; gap is column name validation |
| `frontend/src/components/import/ImportMetadataForm.tsx` | CommitImportRequest.x_column / y_column / geom_column | geometry column dropdowns populate commit request | WIRED | Lines 119-127: handleSubmit correctly sets x_column/y_column/geom_column on request object |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| NDC-01 | Geometry column auto-detection | PARTIAL | Detection logic correct; construction fails for mixed-case column names |
| NDC-02 | Post-import geometry construction for XLSX | PARTIAL | ST_MakePoint/ST_GeomFromText correct; blocked by column name validation |
| NDC-03 | Frontend override UI and type updates | SATISFIED | Full UI implemented and wired in both BulkReviewList and ImportMetadataForm |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/ingest/metadata.py` | 46, 81 | Column name validation using `_TABLE_NAME_RE` (lowercase-only) applied to user-supplied/GDAL column names | BLOCKER | Mixed-case column names (e.g. "Latitude", "Longitude", "WKT") raise ValueError, causing ingest job to fail |

**Details on blocker:** The `_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")` regex was designed for PostgreSQL table names. It is reused to validate column names in `construct_point_geometry` and `construct_wkt_geometry`. Column names from CSV/XLSX files via ogrinfo will often have mixed case (e.g. "Latitude" from a typical Excel spreadsheet). The `detect_geometry_columns` function intentionally preserves original column case (`col_names = {c["name"].lower(): c["name"] for c in columns}` — the value is original case). These original-case column names then fail `_TABLE_NAME_RE.match()` and raise `ValueError("Invalid column name")`, which propagates to the `except Exception` handler in `ingest_file` and marks the job as failed.

**Real-world impact:** A CSV with columns "Latitude", "Longitude" (capital first letter) — the most common naming convention — would detect correctly in preview but fail on commit. The auto-detected values shown to the user in the UI would not work.

**Regression check:** The non-spatial import path (no geometry columns) is unaffected. Shapefile, GeoJSON, and raster imports are unaffected.

### Human Verification Required

#### 1. End-to-end XLSX with lowercase column names

**Test:** Upload an XLSX file with columns `latitude`, `longitude` (all lowercase), confirm preview shows detected columns, commit, and verify the dataset appears as a spatial Point dataset in the catalog.
**Expected:** Import succeeds; dataset has geometry_type = Point.
**Why human:** Requires running Docker environment with PostGIS, GDAL, and a real XLSX file.

#### 2. Non-spatial table catalog entry

**Test:** Upload a CSV/XLSX with no geometry columns, import it, and verify it appears in the catalog as record_type='table'.
**Expected:** Dataset appears with no geometry_type; visible as tabular data.
**Why human:** Requires running Docker environment; depends on NDC predecessor phase behavior.

#### 3. Override to non-spatial

**Test:** Upload a CSV with auto-detected lat/lng columns, then select "Import as non-spatial" mode in the form before committing.
**Expected:** Import succeeds; dataset has no geometry_type (non-spatial table).
**Why human:** Interactive UI test; state machine behavior.

### Gaps Summary

One root-cause gap blocks Truths 1 and 2 (lat/lng and WKT auto-detection for spatial import):

The column name validation in `construct_point_geometry` and `construct_wkt_geometry` uses `_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")`, which only allows lowercase column names. The `detect_geometry_columns` function returns column names in original case as documented. Mixed-case column names (the most common real-world case: "Latitude", "Longitude", "WKT") trigger `ValueError("Invalid column name")`, causing the ingest job to fail.

**Fix options (in order of preference):**
1. Lowercase the column name before the SQL reference in `construct_point_geometry`/`construct_wkt_geometry`, and quote the identifier in SQL with double-quotes for safety: `f'"{ x_column }"::double precision'`. This avoids regex validation entirely.
2. Apply `.lower()` to `x_column`/`y_column`/`geom_column` in `tasks.py` before calling the construction functions (works if GDAL preserves column names in the table — which it does for CSV, lowercasing them).
3. Relax the regex to `^[a-zA-Z0-9_]+$` for column name validation only (not table names).

Option 1 is safest as it also handles special characters. Option 2 is simplest if GDAL always lowercases CSV column names when creating PostGIS tables (which it does by default via ogr2ogr).

---

_Verified: 2026-03-22T21:30:00Z_
_Verifier: Claude (gsd-verifier)_
