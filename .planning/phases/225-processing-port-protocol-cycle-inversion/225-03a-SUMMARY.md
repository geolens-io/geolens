---
phase: 225
plan: 03a
subsystem: processing-port-protocol
tags: [refactor, architecture, processing-port, catalog-decoupling, deferred-imports]
dependency_graph:
  requires:
    - 225-01
    - 225-02
  provides:
    - PROCESS-02 (partial — batch A of deferred sweep)
  affects:
    - backend/app/processing/embeddings/tasks.py
    - backend/app/processing/ingest/tasks_vector.py
    - backend/app/processing/ingest/tasks_common.py
    - backend/app/processing/ingest/tasks_reupload.py
    - backend/app/core/processing_port.py
    - backend/app/platform/extensions/defaults.py
tech_stack:
  added: []
  patterns:
    - "ORM class helpers (get_dataset_orm_class, get_dataset_version_orm_class, get_record_distribution_orm_class) returned by Port for SQL InstrumentedAttribute use sites"
    - "port.get_*_orm_class() pattern: deferred ORM class acquisition inside function body — replaces direct deferred from app.modules.catalog.* import"
    - "port.create_ingestion_result(**kwargs): replaces IngestionResult.model_validate() / IngestionResult() direct construction"
key_files:
  created: []
  modified:
    - backend/app/core/processing_port.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/processing/embeddings/tasks.py
    - backend/app/processing/ingest/tasks_vector.py
    - backend/app/processing/ingest/tasks_common.py
    - backend/app/processing/ingest/tasks_reupload.py
decisions:
  - "DatasetVersion at tasks_common.py:849 used as ORM constructor (session.add(DatasetVersion(...))), not a select query — migrated via get_dataset_version_orm_class() ORM class helper rather than get_dataset_version() fetch method (plan description was inaccurate about the actual usage pattern)"
  - "IngestionResult.model_validate(ingestion_fields) equivalent to port.create_ingestion_result(**ingestion_fields) because IngestionResult has extra=ignore model_config — migration is behavior-identical"
  - "embeddings/tasks.py:21 was runtime deferred import (not TYPE_CHECKING block as described in plan) — migrated via port.get_record_orm_class() + port.get_dataset_orm_class() since Record and Dataset are used in select() SQL expressions"
  - "get_record_distribution_orm_class added to Port as scaffold for Plan 03b (RecordDistribution constructors in tasks_vrt.py:283 and tasks_raster.py:301)"
metrics:
  duration: "~35 minutes"
  completed_date: "2026-05-01"
  tasks: 4
  files_modified: 6
---

# Phase 225 Plan 03a: Migrate Deferred Imports Batch A Summary

**7 deferred catalog import sites migrated across 4 processing/ files — D-19 deferral preserved throughout, zero `from app.modules.catalog` hits in batch A files, Port surface extended with 3 ORM class helpers for batch B scaffold**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-01T18:55:00Z
- **Completed:** 2026-05-01T19:30:00Z
- **Tasks:** 4
- **Files modified:** 6

## Accomplishments

- Ran comprehensive re-grep across entire `processing/` tree — identified all 8 batch A sites plus 29 batch B sites remaining
- Extended ProcessingPort Protocol and DefaultProcessingPort with 3 new ORM class helpers: `get_dataset_orm_class()`, `get_dataset_version_orm_class()`, `get_record_distribution_orm_class()` — scaffold complete for Plan 03b
- Migrated `embeddings/tasks.py:21`: `Dataset, Record` deferred import → `port.get_dataset_orm_class()` + `port.get_record_orm_class()`
- Migrated `ingest/tasks_vector.py:302`: `build_gdal_source` deferred import → `port.build_gdal_source()`
- Migrated `ingest/tasks_common.py` (3 sites): `create_dataset` → `port.create_dataset()`, `IngestionResult.model_validate()` → `port.create_ingestion_result(**kwargs)` (OQ-1), `DatasetVersion` constructor → `DatasetVersion = port.get_dataset_version_orm_class()` (OQ-2)
- Migrated `ingest/tasks_reupload.py` (3 sites): two `Dataset` deferred imports → `port.get_dataset_orm_class()`, one `build_gdal_source` → `port.build_gdal_source()`
- All 4 batch A files: ZERO `from app.modules.catalog` hits
- All 9 architecture guard tests pass; smoke check `isinstance(DefaultProcessingPort(), ProcessingPort) == True`
- 119 targeted tests pass (test_ingest, ingest_column_preservation, ingest_metadata, ingest_ogr_pure); all pass in isolation

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 0 | Re-grep + Port amendment (3 ORM class helpers) | d84ef2eb | core/processing_port.py, platform/extensions/defaults.py |
| 1 | Migrate embeddings/tasks.py + ingest/tasks_vector.py | 55df77c0 | embeddings/tasks.py, ingest/tasks_vector.py |
| 2 | Migrate ingest/tasks_common.py (3 sites) | 199517d6 | ingest/tasks_common.py |
| 3 | Migrate ingest/tasks_reupload.py (3 sites) | 49553678 | ingest/tasks_reupload.py |

## Files Modified

- `backend/app/core/processing_port.py` — 3 ORM class helper Protocol stubs added
- `backend/app/platform/extensions/defaults.py` — 3 DefaultProcessingPort implementations added
- `backend/app/processing/embeddings/tasks.py` — 1 deferred site migrated (+5 LOC)
- `backend/app/processing/ingest/tasks_vector.py` — 1 deferred site migrated (+4 LOC)
- `backend/app/processing/ingest/tasks_common.py` — 3 deferred sites migrated (+9 LOC)
- `backend/app/processing/ingest/tasks_reupload.py` — 3 deferred sites migrated (+9 LOC)

## Deferred Sites Migrated (Batch A — 8 total)

| File | Line | Before | After |
|------|------|--------|-------|
| embeddings/tasks.py | 21 | `from app.modules.catalog...Dataset, Record` | `Record = port.get_record_orm_class(); Dataset = port.get_dataset_orm_class()` |
| tasks_vector.py | 302 | `from app.modules.catalog.sources.preview import build_gdal_source` | `port.build_gdal_source(...)` |
| tasks_common.py | 618 | `from app.modules.catalog...create_dataset` | `port.create_dataset(...)` |
| tasks_common.py | 697 | `IngestionResult.model_validate(...)` | `port.create_ingestion_result(**ingestion_fields)` (OQ-1) |
| tasks_common.py | 849 | `from app.modules.catalog.collections.models import DatasetVersion` | `DatasetVersion = port.get_dataset_version_orm_class()` (OQ-2) |
| tasks_reupload.py | 38 | `from app.modules.catalog...Dataset` | `Dataset = port.get_dataset_orm_class()` |
| tasks_reupload.py | 257 | `from app.modules.catalog...Dataset` | `Dataset = port.get_dataset_orm_class()` |
| tasks_reupload.py | 273 | `from app.modules.catalog.sources.preview import build_gdal_source` | `port.build_gdal_source(...)` |

## Phase-Wide Grep Snapshot (Informational)

After plan 03a, remaining `from app.modules.catalog` deferred imports across `processing/`:

```
29 hits remaining — all in Plan 03b files:
  ingest/service.py: 3 (Dataset/DatasetORM)
  ingest/tasks_vrt.py: 4 (Dataset, Record, RecordDistribution)
  ingest/metadata.py: 5 (RecordKeyword, AttributeMetadata)
  ingest/router.py: 2 (Dataset, Record)
  ingest/tasks_raster.py: 3 (Dataset, Record, RecordDistribution)
  tiles/router.py: 4 (DatasetGrant, Dataset/DatasetORM)
  ai/service.py: 3 (SearchFilters, Dataset/DatasetORM)
  ai/metadata_service.py: 2 (Dataset, RecordKeyword)
  ai/router.py: 1 (Map)
  export/router.py: 1 (parse_bbox)
```

Plan 03b will reduce this to 0 (except `tasks_raster.py:143` per OQ-4 Outcome B if applicable).

## OQ Outcomes

- **OQ-1 (IngestionResult):** `IngestionResult.model_validate(ingestion_fields)` replaced by `port.create_ingestion_result(**ingestion_fields)` in `tasks_common.py`. Behavior-identical: `IngestionResult` has `extra="ignore"` config so both forms discard unknown keys. No direct `IngestionResult()` constructor call remains in batch A files.
- **OQ-2 (DatasetVersion):** `DatasetVersion` at `tasks_common.py:849` was an ORM **constructor** (`session.add(DatasetVersion(...))`), not a fetch query. Migrated via `DatasetVersion = port.get_dataset_version_orm_class()` — ORM class is obtained through Port but instantiated at the call site. This preserves the existing `session.add(DatasetVersion(**kwargs))` construct.
- **OQ-3 (InstrumentedAttribute SQL):** Plan 02 added SQL encapsulators. Plan 03a adds `get_dataset_orm_class()` for all `select(Dataset)` InstrumentedAttribute uses. Scaffold now covers both 03a batch and 03b batch (see Port amendments in Task 0).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] embeddings/tasks.py had runtime deferred import, not TYPE_CHECKING block**
- **Found during:** Task 1 (reading the actual file)
- **Issue:** Plan description said `embeddings/tasks.py:21` was a `if TYPE_CHECKING:` block, but the actual code has `from app.modules.catalog.datasets.domain.models import Dataset, Record` as a runtime deferred import inside the `embed_record` function body
- **Fix:** Used `port.get_record_orm_class()` + `port.get_dataset_orm_class()` instead of the plan's `from app.core.processing_port import Dataset, Record` TYPE_CHECKING migration. Functionally correct — ORM classes used in `select(Record)` and `select(Dataset)` SQL expressions
- **Files modified:** `backend/app/processing/embeddings/tasks.py`
- **Committed in:** `55df77c0`

**2. [Rule 1 - Bug] tasks_common.py:849 DatasetVersion was ORM constructor, not select query**
- **Found during:** Task 2 (reading the actual code)
- **Issue:** Plan's `<interfaces>` described the BEFORE pattern as `select(DatasetVersion).where(DatasetVersion.dataset_id == ...).order_by(...)` and the AFTER as `port.get_dataset_version(session, dataset_id)`. The actual code at line 849 is `session.add(DatasetVersion(...))` — a constructor/insert, not a fetch
- **Fix:** Added `get_dataset_version_orm_class()` Port method (planned in Task 0 scaffold), assigned `DatasetVersion = port.get_dataset_version_orm_class()`, and left `session.add(DatasetVersion(**kwargs))` call site unchanged. The fetch-based `port.get_dataset_version()` from Plan 01 is unrelated to this site and was not the correct migration target
- **Files modified:** `backend/app/core/processing_port.py`, `backend/app/platform/extensions/defaults.py`, `backend/app/processing/ingest/tasks_common.py`
- **Committed in:** `d84ef2eb` (Port), `199517d6` (tasks_common)

Total deviations: 2 auto-fixed (Rule 1 — both bugs in plan's description vs actual codebase)

## Per-File Grep Results (Acceptance Criteria Verification)

```bash
grep -c "from app.modules.catalog" backend/app/processing/embeddings/tasks.py   → 0 ✓
grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_vector.py → 0 ✓
grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_common.py → 0 ✓
grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_reupload.py → 0 ✓
grep -c "port.create_ingestion_result" backend/app/processing/ingest/tasks_common.py → 1 ✓
grep -c "IngestionResult(" backend/app/processing/ingest/tasks_common.py → 0 ✓
```

## Architecture Guard Results

- `test_core_does_not_import_from_any_module`: PASS
- `test_no_external_imports_of_dataset_domain_submodules`: PASS
- `test_platform_extensions_no_top_level_imports`: PASS
- All 9 layering tests: PASS
- `isinstance(DefaultProcessingPort(), ProcessingPort)`: True

## Plan 03b Readiness Statement

Port scaffold complete. The following ORM class helpers are available for batch B consumers:
- `port.get_dataset_orm_class()` — for `select(Dataset)`, `Dataset(...)` constructor uses
- `port.get_record_orm_class()` — already existed from Plan 02; also covers `Record(...)` constructors
- `port.get_dataset_version_orm_class()` — covers `DatasetVersion(...)` constructor uses
- `port.get_record_distribution_orm_class()` — covers `RecordDistribution(...)` constructor uses in tasks_vrt.py:283 and tasks_raster.py:301

**Batch B (5 files: ingest/service.py, ingest/tasks_vrt.py, ingest/metadata.py, ingest/router.py, ingest/tasks_raster.py + tiles/router.py, ai/service.py, ai/metadata_service.py, ai/router.py, export/router.py) can begin without a Task 0 scaffold pass.**

## Known Stubs

None — all catalog access routes through DefaultProcessingPort which delegates to the same catalog functions as before.

## Self-Check: PASSED

Files exist:
- backend/app/processing/embeddings/tasks.py: FOUND
- backend/app/processing/ingest/tasks_vector.py: FOUND
- backend/app/processing/ingest/tasks_common.py: FOUND
- backend/app/processing/ingest/tasks_reupload.py: FOUND
- backend/app/core/processing_port.py: FOUND (amended)
- backend/app/platform/extensions/defaults.py: FOUND (amended)

Commits exist:
- d84ef2eb: FOUND (Task 0)
- 55df77c0: FOUND (Task 1)
- 199517d6: FOUND (Task 2)
- 49553678: FOUND (Task 3)

---
*Phase: 225-processing-port-protocol-cycle-inversion*
*Completed: 2026-05-01*
