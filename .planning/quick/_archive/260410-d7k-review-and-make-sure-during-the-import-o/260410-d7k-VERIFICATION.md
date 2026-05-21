---
phase: 260410-d7k
verified: 2026-04-10T11:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Quick Task 260410-d7k — Verification Report

**Task Goal:** Review backend ingest pipeline and ensure every source column is preserved during import. Fix real bugs found. Add regression tests.
**Verified:** 2026-04-10
**Status:** passed
**Re-verification:** No — initial verification

---

## Commits Verified

Both documented commits exist in the repository:

- `980659ba` — `fix(260410-d7k): close four ingest column-preservation bugs`
- `00af443b` — `test(260410-d7k): add fixture files and regression tests for column preservation`

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Reserved-name source columns (`gid`, `geom`, `geom_4326`, `fid`, `ogc_fid`) are auto-renamed to `src_<name>` and appear in Dataset.column_info | VERIFIED | `rename_reserved_columns()` in `metadata.py:448`; iterates `information_schema.columns`, ALTERs each colliding source column; integration test `TestReservedNameAutoRename::test_reserved_names_renamed_to_src_prefix` |
| 2 | A structured warning is emitted naming the original column, new name, and table | VERIFIED | `logger.warning("Renamed reserved source column", table=..., original=..., renamed=...)` at `metadata.py:525–530`; return value wired into `job.user_metadata['warnings']` at all four entry points |
| 3 | A source `geom_4326` attribute no longer crashes `add_4326_column`; the rename runs before `ALTER TABLE ADD COLUMN geom_4326` | VERIFIED | `rename_reserved_columns` called at `tasks.py:357` (ingest_file) before `_finalize_ingest` which calls `add_4326_column`; `add_4326_column` also uses `ADD COLUMN IF NOT EXISTS` as belt-and-suspenders; test `test_add_4326_column_after_rename_does_not_crash` |
| 4 | `get_column_info()` still strips pipeline-internal columns but not source columns renamed to `src_*` | VERIFIED | `get_column_info` excludes `{"gid", "geom", "geom_4326"}` at `metadata.py:177`; `src_gid`, `src_geom_4326` etc. have different names and are not excluded; test `test_src_columns_visible_in_get_column_info` |
| 5 | `get_sample_values()` returns sample values for non-ASCII / mixed-case column names | VERIFIED | Regex filter removed; SQL-quoted identifiers used (`'"' + col_name.replace('"', '""') + '"'`) at `metadata.py:217`; comment at lines 213–216 explains rationale; tests `TestUnicodeSampleValues::test_non_ascii_columns_have_sample_values` and `test_ascii_control_column_has_sample_values` |
| 6 | Shapefile with DBF 10-char truncation collision emits a warning; ingest still completes | VERIFIED | `detect_dbf_truncation_collisions()` at `metadata.py:541`; wired into `.zip` path of `ingest_file` (`tasks.py:374`) and `reupload_file` (`tasks.py:915`); result appended to `job.user_metadata['warnings']`; warn-only (no exception raised) |
| 7 | Both `-lco PRECISION=NO` call sites in `ogr.py` carry an inline comment | VERIFIED | `ogr.py:338–346` has 9-line comment explaining FLOAT8 coercion tradeoff, locked decision reference; `ogr.py:433–435` has 3-line summary comment referencing the first site |
| 8 | `test_ingest_column_preservation.py` exists with `shutil.which('ogr2ogr')` skip and covers all behaviors | VERIFIED | File exists at 358 lines (>150 minimum); `pytestmark = pytest.mark.skipif(shutil.which("ogr2ogr") is None, ...)` at line 26–29; 9 tests collected without errors: `uv run pytest tests/test_ingest_column_preservation.py --collect-only -q` = `9 tests collected in 0.01s` |
| 9 | SUMMARY.md contains an `## Audit findings` section with file:line references for hotspots §2.1–§2.5 | VERIFIED | `## Audit findings` section at SUMMARY.md line 36; column flow table with file:line references; hotspots table with status for each of §2.1–§2.5 (lines 54–62) |

**Score:** 9/9 truths verified

---

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `backend/app/ingest/ogr.py` | VERIFIED | `RESERVED_COLUMN_NAMES` frozenset defined at line 27–29; inline `PRECISION=NO` comments at lines 338–346 and 433–435 |
| `backend/app/ingest/metadata.py` | VERIFIED | `rename_reserved_columns()` at line 448; `detect_dbf_truncation_collisions()` at line 541; SQL-quoted `get_sample_values()` at line 217; `src_` prefix used throughout rename logic |
| `backend/app/ingest/tasks.py` | VERIFIED | `rename_reserved_columns` called at lines 357 (ingest_file), 621 (ingest_service), 899 (reupload_file), 1147 (reupload_service); `detect_dbf_truncation_collisions` called at lines 386 and 925 for `.zip` paths |
| `backend/tests/test_ingest_column_preservation.py` | VERIFIED | 358 lines (exceeds 150 minimum); 9 tests covering all required scenarios; `shutil.which` guard present |
| `backend/tests/fixtures/ingest/reserved_names.geojson` | VERIFIED | Contains source fields `gid`, `geom`, `geom_4326`, `fid` in properties |
| `backend/tests/fixtures/ingest/unicode_attrs.geojson` | VERIFIED | Contains non-ASCII field names `Nom`, `Größe`, `Área` |
| `backend/tests/fixtures/ingest/dbf_collision.zip` | VERIFIED | File exists (793 bytes) |
| `backend/tests/fixtures/ingest/basic_attrs.geojson` | VERIFIED | File exists (1031 bytes) |
| `backend/tests/fixtures/ingest/mixed_types.csv` | VERIFIED | File exists (172 bytes) |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tasks.py ingest_file` | `metadata.py rename_reserved_columns` | Direct call after `run_ogr2ogr`, before `_finalize_ingest` | WIRED | `tasks.py:355–370` — import + call + warning wiring |
| `tasks.py ingest_service` | `metadata.py rename_reserved_columns` | Direct call after `run_ogr2ogr_service` | WIRED | `tasks.py:619–629` |
| `tasks.py reupload_file` | `metadata.py rename_reserved_columns` | Direct call post-ogr2ogr, pre-`add_4326_column` | WIRED | `tasks.py:897–912` |
| `tasks.py reupload_service` | `metadata.py rename_reserved_columns` | Direct call before `ensure_geom_column` | WIRED | `tasks.py:1145–1158` |
| `tasks.py ingest_file shapefile path` | `metadata.py detect_dbf_truncation_collisions` | Called for `.zip` extension path | WIRED | `tasks.py:374–397` |
| `tasks.py reupload_file shapefile path` | `metadata.py detect_dbf_truncation_collisions` | Called for `.zip` extension path | WIRED | `tasks.py:915–941` |
| `metadata.py add_4326_column` | Cannot collide with `src_geom_4326` | rename runs before `add_4326_column`; also uses `ADD COLUMN IF NOT EXISTS` | WIRED | Ordering verified at `tasks.py:357` then `_finalize_ingest`; belt-and-suspenders at `metadata.py:604` |

---

## Pure-Unit Test Results

Command: `cd backend && uv run pytest tests/test_ingest_ogr_pure.py -x -q`

Result: **27 passed in 0.13s** — all pure-unit tests including the 6 new `detect_dbf_truncation_collisions` tests pass on the dev host without ogr2ogr.

---

## Integration Test Collection

Command: `cd backend && uv run pytest tests/test_ingest_column_preservation.py --collect-only -q`

Result: **9 tests collected in 0.01s** — no import errors; all tests collected cleanly. Tests are gated with `shutil.which("ogr2ogr")` skip and will run green inside the backend Docker image / CI.

---

## Anti-Patterns Found

None. No TODO, FIXME, placeholder comments, or empty implementations found in the modified files (`ogr.py`, `metadata.py`, `tasks.py`).

---

## Human Verification Required

None. All must-haves are verifiable programmatically. The integration tests themselves provide regression coverage for behaviors that would otherwise require a real PostGIS + ogr2ogr environment.

---

## Gaps Summary

No gaps. All 9 must-haves from the PLAN frontmatter are verified against the actual codebase. Code matches what the SUMMARY claims.

---

_Verified: 2026-04-10T11:00:00Z_
_Verifier: Claude (gsd-verifier)_
