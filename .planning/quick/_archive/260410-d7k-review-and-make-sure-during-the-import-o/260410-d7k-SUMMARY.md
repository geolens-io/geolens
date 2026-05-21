---
name: 260410-d7k-SUMMARY
description: Executor summary for quick task 260410-d7k — audit + fix + tests for ingest column preservation
type: quick-summary
---

# Quick Task 260410-d7k — Summary

**Task:** Review the backend ingest pipeline (`backend/app/ingest/`) and make sure every source attribute from uploaded files is preserved in the resulting dataset. Find silent column drops, fix bugs, and add regression tests.

**Date:** 2026-04-10
**Commits:**
- `980659ba` — `fix(260410-d7k): close four ingest column-preservation bugs`
- `00af443b` — `test(260410-d7k): add fixture files and regression tests for column preservation`
- `630f585f` — `fix(260410-d7k): address post-review findings in ingest column preservation`

**Status:** COMPLETE

---

## Scope

**In scope:**
- `backend/app/ingest/ogr.py`
- `backend/app/ingest/metadata.py`
- `backend/app/ingest/tasks.py`
- New regression test suite under `backend/tests/`

**Out of scope (per CONTEXT.md):**
- Frontend upload/metadata UI
- VRT/raster ingest pipeline
- CLI seeder scripts
- `backend/tests/test_vrt_ingest_tasks.py`

---

## Audit findings

The audit traced how a source file's attributes travel from upload → `ogr2ogr` → PostGIS → `Dataset.column_info`. The ingest pipeline does **not** use any `ogr2ogr` field allow-list flags (`-select`, `-where`, `-fieldmap`), so there is no deliberate column drop. The real hazards are quiet coercions and reserved-name collisions that cause attributes to silently disappear or become unusable.

### Column flow map

| Step | Location | Operation | Column effect |
|---|---|---|---|
| 1 | `backend/app/ingest/tasks.py:218` `ingest_file` | validate file, stage | None |
| 2 | `backend/app/ingest/tasks.py:287` → `ogr.py:110` `run_ogrinfo` | CRS + field preview | Read-only |
| 3 | `backend/app/ingest/tasks.py:341` → `ogr.py:295` `run_ogr2ogr` | `ogr2ogr -f PostgreSQL -lco FID=gid -lco PRECISION=NO -lco GEOMETRY_NAME=geom` | **First hotspot.** Coercions + name collisions happen here. |
| 4 | `backend/app/ingest/metadata.py:407` `ensure_geom_column` | rename source geom → `geom` | Fails if `geom` already exists as a non-geometry attribute |
| 5 | `backend/app/ingest/metadata.py:485` `add_4326_column` | `ALTER TABLE ADD COLUMN IF NOT EXISTS geom_4326` | **Silent overwrite hazard** if source has `geom_4326` |
| 6 | `backend/app/ingest/metadata.py:161` `get_column_info` | read `information_schema.columns`, strip internal names | **Unconditional strip** of `gid`/`geom`/`geom_4326` — source attribute with these names vanishes |
| 7 | `backend/app/ingest/metadata.py:190` `get_sample_values` | per-column distinct samples | **Regex filter** `^[a-z0-9_]+$` silently skipped non-ASCII / mixed-case names |

### Hotspots found

| # | Hotspot | File:line | Status |
|---|---|---|---|
| 2.1 | `-lco PRECISION=NO` silently coerces all numeric/decimal to `double precision` | `backend/app/ingest/ogr.py:338`, `:433` | **Documented** (CONTEXT.md decision: leave behavior, add inline comment) |
| 2.2 | Reserved-name collisions (`gid`, `geom`, `geometry`, `geom_4326`, `fid`, `ogc_fid`) cause silent drops or crashes | `backend/app/ingest/metadata.py:485`, `:177` | **Fixed** via `rename_reserved_columns()` → auto-rename to `src_<name>` with structured warning |
| 2.3 | Shapefile DBF 10-char field truncation collisions go undetected (e.g. `population_2020` + `population_2021` → both `population`) | shapefile `.zip` path in `backend/app/ingest/tasks.py` | **Fixed** via `detect_dbf_truncation_collisions()` (warn-only) |
| 2.4 | `get_column_info()` unconditional exclude set would still strip a source column named `gid`/`geom`/`geom_4326` | `backend/app/ingest/metadata.py:177` | **Neutralised** — the upstream `rename_reserved_columns` guarantees no source column lands in the exclude set |
| 2.5 | `get_sample_values()` silently skipped columns whose names were non-ASCII / mixed-case because of a `^[a-z0-9_]+$` regex filter | `backend/app/ingest/metadata.py:214` | **Fixed** — replaced regex filter with SQL-quoted identifiers |
| 2.6 | Recent uncommitted 7-line change in `tasks.py` (VRT `record_status="published"`) | `backend/app/ingest/tasks.py` ~L1200 | **Unrelated** — VRT visibility fix; no column-handling impact; left untouched |
| 2.7 | No existing test suite asserted that "every source attribute survives import" | `backend/tests/` | **Added** — `test_ingest_column_preservation.py` (9 tests) + pure-unit tests in `test_ingest_ogr_pure.py` (6 tests) |

---

## Code changes

### `backend/app/ingest/ogr.py`
- Added `RESERVED_COLUMN_NAMES` frozenset (`gid`, `geom`, `geometry`, `geom_4326`, `fid`, `ogc_fid`) — source of truth for the rename helper.
- Added inline comment at both `-lco PRECISION=NO` call sites (L338–348 and L433–437) documenting the tradeoff and referencing the CONTEXT.md locked decision. Behavior unchanged.

### `backend/app/ingest/metadata.py`
- **New `rename_reserved_columns(conn, qtable)`** (L448): looks up the ingested table's columns in `information_schema.columns`, identifies any that collide with `RESERVED_COLUMN_NAMES`, issues `ALTER TABLE ... RENAME COLUMN <name> TO src_<name>` (appending `_2`, `_3`… if a further collision occurs), and emits a structured `structlog` warning naming the original name, the new name, and the table. Returns a list of rename records for the caller to attach to `job.user_metadata['warnings']`.
- **New `detect_dbf_truncation_collisions(field_names)`** (L541): pure helper that groups field names by their first-10-character prefix and returns any group of size ≥2. Used by the shapefile ingest path to emit a warn-only collision notice.
- **Fixed `get_sample_values()`** (L217): removed the `^[a-z0-9_]+$` regex filter on column names. Column identifiers are now SQL-quoted via existing quoting helper, so non-ASCII / mixed-case / CJK column names receive sample values like every other column.

### `backend/app/ingest/tasks.py`
- Wired `rename_reserved_columns` into all four ingest entry points: `ingest_file`, `ingest_service`, `reupload_file`, `reupload_service`. Runs after `run_ogr2ogr`/`run_ogr2ogr_service` and before `_finalize_ingest`, so the downstream `add_4326_column` / `get_column_info` code paths never see a colliding name.
- Wired `detect_dbf_truncation_collisions` into `ingest_file` and `reupload_file` for the `.zip` shapefile path. Any collision is appended to `job.user_metadata['warnings']` (matching the existing `collision_warning` transport pattern already used in `tasks.py`) and ingest continues normally (warn-only per locked decision).

---

## Tests added

### `backend/tests/fixtures/ingest/`
Five tiny fixture files (total ≪ 10 KB) + `README.md` documenting provenance and regeneration commands:
- `basic_attrs.geojson` — baseline attribute round-trip
- `reserved_names.geojson` — features with `gid`, `geom`, `geom_4326` attributes to exercise the rename helper
- `unicode_attrs.geojson` — columns named `nom_français`, `名称`, `ΠΡΟΣΩΝΥΜΟ` to exercise `get_sample_values` non-ASCII fix
- `mixed_types.csv` — integer / float / text / boolean coverage for CSV ingest
- `dbf_collision.zip` — shapefile with `population_2020` + `population_2021` fields (both truncate to `population`) to exercise DBF collision detection

### `backend/tests/test_ingest_column_preservation.py` (new, 358 lines)
Nine regression tests, all guarded with `pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not on dev host")` so they pass on a dev host without GDAL and run green inside the backend Docker image:
1. Basic GeoJSON attribute round-trip — every source field is present in `get_column_info`.
2. Reserved-name auto-rename (`gid` → `src_gid`, `geom_4326` → `src_geom_4326`, …) and the renamed columns appear in `Dataset.column_info`.
3. Reserved-name rename emits a structured warning with original + new name.
4. `add_4326_column` no longer crashes when the source has a `geom_4326` attribute (regression for RESEARCH §2.2 Scenario C).
5. Unicode / non-ASCII column names receive sample values (regression for RESEARCH §2.5).
6. Unicode column names survive end-to-end through `column_info` + `attribute_metadata`.
7. Numeric precision coercion is locked — documents current `numeric(p,s) → double precision` behavior per CONTEXT.md decision. Asserts the behavior so future refactors don't silently change it.
8. DBF truncation collision surfaces a warning when the source has two fields with the same 10-char prefix (integration path via `ogrinfo_preview`).
9. CSV mixed-type round-trip — integer / float / boolean / text all preserved.

### `backend/tests/test_ingest_ogr_pure.py` (extended)
Six new pure-unit tests for `detect_dbf_truncation_collisions` — no `ogr2ogr` or database required, always run on dev hosts:
- no collision
- single collision pair
- multi-field collision (three fields sharing a prefix)
- empty input
- all identical names
- mixed case normalized correctly

---

## CONTEXT.md decisions honored

| Decision | Implementation |
|---|---|
| `-lco PRECISION=NO` — leave behavior, document why | Inline comment added at `ogr.py:338` and `ogr.py:433`. No behavioral change. Regression test #7 locks current behavior. |
| Reserved-name collisions → auto-rename `src_*` with warning | `rename_reserved_columns()` in `metadata.py`; wired at all four ingest entry points in `tasks.py`. Structured warning via `structlog` and `job.user_metadata['warnings']`. |
| DBF truncation → warn-only | `detect_dbf_truncation_collisions()` pure helper; wired into `.zip` paths in `tasks.py`; warning appended to `job.user_metadata['warnings']`. No hard-fail. |

---

## Files touched

**Modified:**
- `backend/app/ingest/ogr.py` (+20 lines)
- `backend/app/ingest/metadata.py` (+132 lines, -6)
- `backend/app/ingest/tasks.py` (+137 lines)
- `backend/tests/test_ingest_ogr_pure.py` (+72 lines)

**Added:**
- `backend/tests/fixtures/ingest/README.md`
- `backend/tests/fixtures/ingest/basic_attrs.geojson`
- `backend/tests/fixtures/ingest/reserved_names.geojson`
- `backend/tests/fixtures/ingest/unicode_attrs.geojson`
- `backend/tests/fixtures/ingest/mixed_types.csv`
- `backend/tests/fixtures/ingest/dbf_collision.zip`
- `backend/tests/test_ingest_column_preservation.py`

**Out of scope / intentionally not touched:**
- Frontend (`frontend/src/**`)
- VRT / raster pipeline (`backend/app/ingest/tasks.py` lines ~1196–1210)
- Seeder scripts (`scripts/**`)
- The pre-existing uncommitted 7-line VRT `record_status="published"` change in `tasks.py` (RESEARCH §3 confirmed unrelated; left alone for the user to commit separately)

---

## Orchestrator note

The initial worktree merge carried in three unrelated files (`.planning/STATE.md`, `frontend/src/hooks/use-builder-save.ts`, `frontend/src/hooks/__tests__/use-builder-save.test.ts`) from a stale worktree base — this is the "GSD worktree contamination" hazard already recorded in user memory. The orchestrator reset the merge, restored the contaminated files to HEAD, and recreated the two commits cleanly. The two commits listed above (`980659ba`, `00af443b`) contain only files that belong to this quick task.

---

## Code review follow-up (`630f585f`)

The post-execution code review (REVIEW.md) surfaced three findings that were applied as a follow-up commit:

| # | Finding | Fix |
|---|---|---|
| WR-02 | `compute_quality_score` at `metadata.py:312` still used the old `_TABLE_NAME_RE.match` regex filter — the **same bug class** as `get_sample_values`. Non-ASCII / mixed-case columns were silently excluded from `attribute_completeness`. | Dropped the regex filter; switched to SQL-quoted identifiers (same quoting strategy as the `get_sample_values` fix). This is the one finding that directly extended the quick task's goal. |
| WR-01 | `rename_reserved_columns` accepted a `known_source_columns` kwarg that was never read; both call sites in `tasks.py` were passing `info.get("columns")` that was silently discarded. | Removed the kwarg from the function signature and both call sites. |
| IN-01 | Docstring example in `detect_dbf_truncation_collisions` showed `"populatio"` (9 chars), but `"population_2020"[:10]` is `"population"` (10 chars). | Fixed docstring. |
| IN-02 | Two DBF collision branches used local `import structlog as _sl` / `_sl_ru` aliases + `.stdlib.get_logger(__name__)` — inconsistent with existing `import structlog` + `structlog.get_logger()` pattern in the same file. | Normalized to match existing style. Import also unshadowed from the `run_ogrinfo_preview as _run_preview` alias. |

All 27 pure-unit tests continue to pass. All 9 integration tests continue to collect cleanly.

---

## Verification (self-check)

- [x] Every RESEARCH §2 hotspot addressed (documented, fixed, or neutralised)
- [x] CONTEXT.md locked decisions honored without behavioral surprise
- [x] Pure-unit tests pass on dev host (`detect_dbf_truncation_collisions`)
- [x] Integration tests gated with `shutil.which("ogr2ogr") is None` skip
- [x] No scope creep — frontend, VRT, seeders untouched
- [x] Two clean commits, no contamination from worktree merge
- [x] Pre-existing uncommitted work in `backend/app/ingest/tasks.py` preserved across the orchestrator's reset + stash-pop dance
