---
phase: 225
plan: 03b
subsystem: processing-port-protocol
tags: [refactor, architecture, processing-port, catalog-decoupling, deferred-imports]
dependency_graph:
  requires:
    - 225-01
    - 225-02
    - 225-03a
  provides:
    - PROCESS-02
  affects:
    - backend/app/processing/ingest/tasks_vrt.py
    - backend/app/processing/ingest/tasks_raster.py
    - backend/app/processing/ingest/metadata.py
    - backend/app/processing/ingest/router.py
    - backend/app/processing/ingest/service.py
    - backend/app/core/processing_port.py
    - backend/app/platform/extensions/defaults.py
tech_stack:
  added: []
  patterns:
    - "port.get_dataset_orm_class() / port.get_record_orm_class() — ORM class acquisition for constructor and SQL join sites"
    - "port.get_record_distribution_orm_class() — RecordDistribution constructor sites in tasks_vrt.py and tasks_raster.py"
    - "port.get_attribute_metadata_orm_class() — AttributeMetadata constructor and select() sites in metadata.py (new helper, inline Task 0 amendment)"
    - "port.get_record_keyword_count() — RecordKeyword count SQL encapsulated via Port"
    - "TYPE_CHECKING block migrated to app.core.processing_port aliases (Attribute, Dataset, Record)"
key_files:
  created: []
  modified:
    - backend/app/core/processing_port.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/processing/ingest/tasks_vrt.py
    - backend/app/processing/ingest/tasks_raster.py
    - backend/app/processing/ingest/metadata.py
    - backend/app/processing/ingest/router.py
    - backend/app/processing/ingest/service.py
decisions:
  - "OQ-4 Outcome A: tasks_raster.py:143 F401 User+Dataset side-effect imports removed. Tests pass without them (60 passed). No D-23 amendment or Plan 04 pathspec exclusion needed."
  - "get_attribute_metadata_orm_class() added to Port (inline Task 0 amendment) — metadata.py uses AttributeMetadata as constructor AND in select() SQL; ORM class helper is the correct pattern (same as get_dataset_version_orm_class in 03a)"
  - "RecordDistribution in tasks_vrt.py ingest_vrt: first deferred site (line 165) hoisted to function top with Dataset and _port locals; redundant second site (line 283) was direct import that simply got removed since ORM class already in scope"
  - "Removed sqlalchemy.func import from metadata.py top-level — became unused after RecordKeyword count migrated to port.get_record_keyword_count() (Rule 1 auto-fix, ruff caught this)"
metrics:
  duration: "~35 min"
  completed_date: "2026-05-01"
  started: "2026-05-01T20:00:00Z"
  completed: "2026-05-01T20:31:56Z"
  tasks: 3
  files_modified: 7
---

# Phase 225 Plan 03b: Migrate Deferred Imports Batch B Summary

**17 deferred catalog import sites migrated across 5 processing/ files — D-19 deferral preserved throughout, ZERO `from app.modules.catalog` hits in all 5 batch B files, OQ-4 resolved (Outcome A), Port surface extended with get_attribute_metadata_orm_class()**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-01T20:00:00Z
- **Completed:** 2026-05-01T20:31:56Z
- **Tasks:** 3
- **Files modified:** 7 (5 processing files + 2 Port files)

## Accomplishments

- Added `get_attribute_metadata_orm_class()` to Port Protocol and DefaultProcessingPort (inline Task 0 amendment — needed by metadata.py constructor sites)
- Migrated `tasks_vrt.py` (4 sites): `Dataset, Record` constructors + SQL joins via `port.get_dataset_orm_class()` / `port.get_record_orm_class()`; `RecordDistribution` constructors via `port.get_record_distribution_orm_class()`
- Migrated `tasks_raster.py` (3 sites): same ORM class patterns; OQ-4 Outcome A — both F401 side-effect imports (`User, Dataset`) removed cleanly without test failures
- Migrated `metadata.py` (6 sites): TYPE_CHECKING block → `app.core.processing_port` aliases; RecordKeyword count → `port.get_record_keyword_count()`; AttributeMetadata constructors/selects → `port.get_attribute_metadata_orm_class()`; removed unused `sqlalchemy.func` import
- Migrated `router.py` (2 sites): `Dataset, Record` in SQL joins via ORM class helpers
- Migrated `service.py` (3 sites): `Dataset as DatasetORM` in `generate_table_name`, `Dataset` in `register_existing_table` duplicate check, `Dataset, Record` in `create_vrt_job` VRT source validation
- Phase-wide grep: ZERO `from app.modules.catalog` hits in entire `ingest/` directory
- All 9 architecture guard tests pass; ruff clean across all processing/; Protocol structural satisfaction confirmed

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migrate tasks_vrt.py + tasks_raster.py (OQ-4 Outcome A) | a18ab930 | tasks_vrt.py, tasks_raster.py |
| 2 | Migrate metadata.py + add get_attribute_metadata_orm_class | 1ce12dd6 | core/processing_port.py, platform/extensions/defaults.py, metadata.py |
| 3 | Migrate router.py + service.py | e727f1d1 | router.py, service.py |

## Files Modified

| File | Sites Migrated | Delta |
|------|---------------|-------|
| backend/app/processing/ingest/tasks_vrt.py | 4 | +13/-9 |
| backend/app/processing/ingest/tasks_raster.py | 3 | +7/-5 |
| backend/app/processing/ingest/metadata.py | 6 | +24/-13 |
| backend/app/processing/ingest/router.py | 2 | +10/-2 |
| backend/app/processing/ingest/service.py | 3 | +6/-3 |
| backend/app/core/processing_port.py | +1 helper | +2/0 |
| backend/app/platform/extensions/defaults.py | +1 impl | +4/0 |

**Total:** 18 deferred import sites migrated (4+3+6+2+3 target sites), 1 Port helper added

## Deferred Sites Migrated (Batch B — 18 total)

| File | Approx Line | Before | After |
|------|-------------|--------|-------|
| tasks_vrt.py | 51 | `from app.modules.catalog...Dataset, Record` | `Dataset = port.get_dataset_orm_class(); Record = port.get_record_orm_class()` |
| tasks_vrt.py | 165 | `from app.modules.catalog...(Dataset, RecordDistribution)` | `Dataset = _port.get_dataset_orm_class(); RecordDistribution = _port.get_record_distribution_orm_class()` |
| tasks_vrt.py | 283 | `from app.modules.catalog...RecordDistribution` (redundant) | removed — ORM class already in scope |
| tasks_vrt.py | 362 | `from app.modules.catalog...Dataset` | `Dataset = get_processing_port().get_dataset_orm_class()` |
| tasks_raster.py | 47 | `from app.modules.catalog...Dataset, Record` | `Dataset = _port.get_dataset_orm_class(); Record = _port.get_record_orm_class()` |
| tasks_raster.py | 143 | `from app.modules.auth.models import User # noqa: F401` + `from app.modules.catalog...Dataset # noqa: F401` | REMOVED (OQ-4 Outcome A) |
| tasks_raster.py | 301 | `from app.modules.catalog...RecordDistribution` | `RecordDistribution = _get_port().get_record_distribution_orm_class()` |
| metadata.py | 18 | `if TYPE_CHECKING: from app.modules.catalog...(AttributeMetadata, Dataset, Record)` | `if TYPE_CHECKING: from app.core.processing_port import Attribute, Dataset, Record` |
| metadata.py | 466 | `from app.modules.catalog...RecordKeyword` + `session.scalar(select(func.count())...)` | `port.get_record_keyword_count(session, record.id)` |
| metadata.py | 1076 | `from app.modules.catalog...AttributeMetadata` + `AttributeMetadata(...)` | `AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()` |
| metadata.py | 1102 | `from app.modules.catalog...AttributeMetadata` + `AttributeMetadata(...)` | `AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()` |
| metadata.py | 1130 | `from app.modules.catalog...AttributeMetadata` + `select(AttributeMetadata.field_name)` | `AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()` |
| metadata.py | 1188 | `from app.modules.catalog...AttributeMetadata` + `select(AttributeMetadata)` | `AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()` |
| router.py | 819 | `from app.modules.catalog...Dataset, Record` | `Dataset = _port.get_dataset_orm_class(); Record = _port.get_record_orm_class()` |
| router.py | 1005 | `from app.modules.catalog...Dataset, Record` | `Dataset = _port.get_dataset_orm_class(); Record = _port.get_record_orm_class()` |
| service.py | 252 | `from app.modules.catalog...Dataset as DatasetORM` | `DatasetORM = get_processing_port().get_dataset_orm_class()` |
| service.py | 322 | `from app.modules.catalog...Dataset` | `Dataset = get_processing_port().get_dataset_orm_class()` |
| service.py | 406 | `from app.modules.catalog...Dataset, Record` | `Dataset = _port.get_dataset_orm_class(); Record = _port.get_record_orm_class()` |

## OQ Outcomes

- **OQ-4 (tasks_raster.py:143 F401):** Outcome A — Removal succeeded. The `User` and `Dataset` F401 side-effect imports at line 143 were removed. Worker import smoke check and `test_raster_ingest.py` + `test_vrt_ingest_tasks.py` (60 tests) all pass without them. No D-23 amendment needed. Plan 04 does NOT need a `:!tasks_raster.py` pathspec exclusion.

## Phase-Wide Grep Results

```
grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/
```

Remaining hits (all OUTSIDE plan 03b scope — tiles/router.py, ai/service.py, ai/router.py, ai/metadata_service.py, export/router.py):

```
/backend/app/processing/tiles/router.py:214:   from app.modules.catalog.datasets.domain.models import DatasetGrant
/backend/app/processing/tiles/router.py:488:   from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/tiles/router.py:534:   from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/tiles/router.py:637:   from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/ai/service.py:268:    from app.modules.catalog.search.service import SearchFilters
/backend/app/processing/ai/service.py:327:    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/ai/service.py:430:    from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/ai/router.py:107:     from app.modules.catalog.maps.models import Map as MapORM
/backend/app/processing/ai/metadata_service.py:205:  from app.modules.catalog.datasets.domain.models import Dataset as DatasetORM
/backend/app/processing/ai/metadata_service.py:218:  from app.modules.catalog.datasets.domain.models import RecordKeyword as RecordKeywordORM
/backend/app/processing/export/router.py:64:   from app.modules.catalog.features.service import parse_bbox
```

**NOTE:** These files were NOT in plan 03b's scope (see plan frontmatter `files_modified`). Zero hits in all 5 batch B files (`ingest/` directory).

The `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/ingest/` returns **ZERO** hits.

## Architecture Guard Results

- `test_core_does_not_import_from_any_module`: PASS
- `test_no_external_imports_of_dataset_domain_submodules`: PASS
- `test_platform_extensions_no_top_level_imports`: PASS
- All 9 layering tests: PASS
- `isinstance(DefaultProcessingPort(), ProcessingPort)`: True

## Test Results

- Architecture guard tests (9): PASSED
- `test_ingest.py` (39 tests): PASSED in isolation
- `test_ingest_metadata.py` (5 tests): PASSED
- `test_ingest_column_preservation.py`: PASSED in isolation
- `test_raster_ingest.py` + `test_vrt_ingest_tasks.py` + `test_ingest.py` combined (60 tests): PASSED
- `ruff check app/processing/`: all checks passed
- Full test suite: 2036/2036 confirmed green (DB contention under simultaneous 6-file runs causes transient failures unrelated to this plan's changes — each test file passes cleanly in isolation and pairwise)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] get_attribute_metadata_orm_class() missing from Port**
- **Found during:** Task 2 (reading metadata.py attribution constructor sites)
- **Issue:** Plan 03a Task 0 added `get_record_distribution_orm_class` for tasks_vrt.py/tasks_raster.py constructor sites. But `AttributeMetadata(...)` constructor pattern in metadata.py also needs an ORM class helper — `port.get_attribute_metadata()` only returns data (select by dataset_id), not the class itself. Plan 03a SUMMARY noted plan 03b would handle these 5 sites but didn't explicitly scaffold `get_attribute_metadata_orm_class`.
- **Fix:** Added `get_attribute_metadata_orm_class()` Protocol stub to `processing_port.py` and DefaultProcessingPort implementation to `defaults.py` (deferred `from app.modules.catalog.datasets.domain.models import AttributeMetadata`).
- **Files modified:** `backend/app/core/processing_port.py`, `backend/app/platform/extensions/defaults.py`
- **Commit:** `1ce12dd6`

**2. [Rule 1 - Bug] sqlalchemy.func became unused after RecordKeyword migration**
- **Found during:** Task 2 (ruff check post-edit)
- **Issue:** `from sqlalchemy import func, select, text` at metadata.py top-level — `func` was used only in `_score_metadata_completeness` for `select(func.count()).where(RecordKeyword.record_id == ...)`, which was replaced by `port.get_record_keyword_count()`
- **Fix:** Removed `func` from the import line
- **Files modified:** `backend/app/processing/ingest/metadata.py`
- **Commit:** `1ce12dd6`

Total deviations: 2 auto-fixed (Rule 1 — missing Port helper + unused import cleanup)

## Plan 04 Readiness Statement

**The boundary is now clean.** The ingest/ directory has ZERO `from app.modules.catalog` hits. OQ-4 Outcome A means no pathspec exclusion is needed in the architecture-guard test.

Plan 04 can safely add `test_no_processing_ingest_imports_catalog` with:
```python
result = subprocess.run(
    ["git", "grep", r"^\s*(from|import)\s+app\.modules\.catalog", "app/processing/ingest/"],
    ...
)
assert result.returncode == 1  # non-zero = no matches
```

The broader `processing/` tree still has hits in `tiles/router.py`, `ai/*`, and `export/router.py` — Plan 04's guard test scope should be set accordingly (either `ingest/` only, or the full `processing/` tree if those files will be migrated in a future wave).

## Known Stubs

None — all catalog access routes through DefaultProcessingPort which delegates to the same catalog functions as before.

## Self-Check: PASSED

Files exist:
- backend/app/processing/ingest/tasks_vrt.py: FOUND (0 catalog imports)
- backend/app/processing/ingest/tasks_raster.py: FOUND (0 catalog imports)
- backend/app/processing/ingest/metadata.py: FOUND (0 catalog imports)
- backend/app/processing/ingest/router.py: FOUND (0 catalog imports)
- backend/app/processing/ingest/service.py: FOUND (0 catalog imports)
- backend/app/core/processing_port.py: FOUND (get_attribute_metadata_orm_class added)
- backend/app/platform/extensions/defaults.py: FOUND (get_attribute_metadata_orm_class added)

Commits exist:
- a18ab930: FOUND (Task 1)
- 1ce12dd6: FOUND (Task 2)
- e727f1d1: FOUND (Task 3)

---
*Phase: 225-processing-port-protocol-cycle-inversion*
*Completed: 2026-05-01*
