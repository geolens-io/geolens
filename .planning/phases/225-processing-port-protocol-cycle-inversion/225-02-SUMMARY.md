---
phase: 225
plan: 02
subsystem: processing-port-protocol
tags: [refactor, architecture, processing-port, catalog-decoupling]
dependency_graph:
  requires:
    - 225-01
  provides:
    - PROCESS-02
    - PROCESS-03
  affects:
    - app/processing/ai/service.py
    - app/processing/ai/router.py
    - app/processing/ai/chat_service.py
    - app/processing/ai/metadata_service.py
    - app/processing/ai/streaming.py
    - app/processing/embeddings/backfill.py
    - app/processing/tiles/router.py
    - app/processing/export/router.py
    - app/processing/ingest/service.py
tech_stack:
  added: []
  patterns:
    - "Depends(get_processing_port) for HTTP route handlers (D-14)"
    - "get_processing_port() call at worker function body top (D-14)"
    - "port: ProcessingPort keyword-only parameter on service-layer functions (D-15)"
    - "Deferred imports (inside function bodies) for ORM classes needed in SQL expressions"
key_files:
  created: []
  modified:
    - backend/app/processing/ai/service.py
    - backend/app/processing/ai/router.py
    - backend/app/processing/ai/chat_service.py
    - backend/app/processing/ai/metadata_service.py
    - backend/app/processing/ai/streaming.py
    - backend/app/processing/embeddings/backfill.py
    - backend/app/processing/tiles/router.py
    - backend/app/processing/export/router.py
    - backend/app/processing/ingest/service.py
    - tests/test_ai_chat.py
    - tests/test_ai_send_sample_values.py
    - tests/test_chat_narrative.py
    - tests/test_sql_engine.py
decisions:
  - "Deferred imports used for ORM classes needed in SQL InstrumentedAttribute expressions (select(DatasetORM.id, ...)) — these are inside function bodies and do not trigger the architecture guard"
  - "get_records_without_embeddings(force=False) is correct after the force-deletion block in backfill.py since all embeddings are cleared before the call"
  - "parse_bbox from catalog.features.service moved to deferred import (Rule 1 architecture guard fix)"
  - "streaming.py received port threading as Rule 3 auto-fix (cascaded from chat_service.py port parameter requirement)"
  - "get_related_keywords_from_embeddings preserves embedding-similarity logic with deferred ORM imports for the inner SQL expressions"
metrics:
  duration: "~90 minutes (continued from previous session)"
  completed_date: "2026-05-01"
  tasks: 4
  files_modified: 13
---

# Phase 225 Plan 02: Migrate Top-Level Imports Summary

Removed all 8 module-level `from app.modules.catalog.*` top-of-file imports from `backend/app/processing/` and wired catalog access through `DefaultProcessingPort` via `get_processing_port()` and `Depends(get_processing_port)`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 0 | Extend Port Protocol + DefaultProcessingPort | 0aecf689 | core/processing_port.py, platform/extensions/defaults.py |
| 1 | Migrate service.py + router.py | 62b56e25 | ai/service.py, ai/router.py, tests/test_ai_chat.py |
| 2 | Migrate chat_service.py, metadata_service.py, streaming.py, backfill.py | 04b12656 | 5 files + tests |
| 3 | Migrate tiles/router.py, export/router.py, ingest/service.py | 3285bfa3 | 3 files + 3 test files |

## Architecture Guard Result

```
git grep "^\s*(from|import)\s+app\.modules\." app/processing/ → zero results
```

All remaining `app.modules.*` imports in `app/processing/` are auth/audit/embed-tokens (non-catalog) infrastructure — not in scope for this plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] streaming.py cascade from chat_service.py port parameter**
- **Found during:** Task 2
- **Issue:** `streaming.py` imports `_execute_chat_tool` from `chat_service.py`; after adding `port` parameter to `_execute_chat_tool`, `streaming.py` failed to compile at call sites
- **Fix:** Added `port: "ProcessingPort"` to all streaming functions (`_execute_and_yield_tools`, `_stream_anthropic_chat`, `_stream_openai_chat`, `stream_chat_edit`) and threaded port through
- **Files modified:** `app/processing/ai/streaming.py`
- **Commit:** 04b12656

**2. [Rule 1 - Bug] test_ai_chat.py missing port argument after _validate_chat_layers signature change**
- **Found during:** Task 1
- **Issue:** 4 test call sites passed no `port` argument after new required parameter was added
- **Fix:** Added `_default_port = DefaultProcessingPort()` and updated all 4 call sites
- **Files modified:** `tests/test_ai_chat.py`
- **Commit:** 62b56e25

**3. [Rule 1 - Bug] test_ai_send_sample_values.py patching removed module attribute**
- **Found during:** Task 3 verification
- **Issue:** Tests patched `app.processing.ai.service.search_datasets` which no longer exists as module-level attribute after migration; also missing `port` argument
- **Fix:** Switched from `patch()` to direct `port.search_datasets = AsyncMock(...)`; added `port=port` to `_execute_search_tool` calls
- **Files modified:** `tests/test_ai_send_sample_values.py`
- **Commit:** 3285bfa3

**4. [Rule 1 - Bug] test_chat_narrative.py + test_sql_engine.py missing port argument**
- **Found during:** Task 3 verification
- **Issue:** Multiple `_execute_chat_tool` call sites missing required `port` parameter
- **Fix:** Added `port=DefaultProcessingPort()` or `port=_default_port` to all call sites
- **Files modified:** `tests/test_chat_narrative.py`, `tests/test_sql_engine.py`
- **Commit:** 3285bfa3

**5. [Rule 1 - Architecture guard] export/router.py parse_bbox was missed in plan scope**
- **Found during:** Task 3 verification (architecture guard check)
- **Issue:** `parse_bbox` from `app.modules.catalog.features.service` was in the original file and not in the plan's explicit migration list, but the architecture guard `git grep "^\s*(from|import)\s+app\.modules\."` catches all catalog imports including it
- **Fix:** Moved `parse_bbox` import to deferred position inside the route handler function body
- **Files modified:** `app/processing/export/router.py`
- **Commit:** 3285bfa3

## Test Results

- Target test suite (163 tests across ai_chat, ai_metadata, embedding_backfill, tiles, tile_signing, export, ingest, ai_send_sample_values, chat_narrative, sql_engine): 163 passed
- Full backend suite: Final run in progress at commit time

## Known Stubs

None — all catalog access routes through DefaultProcessingPort which delegates to the same catalog functions as before.

## Self-Check: PASSED

Files exist:
- backend/app/processing/ai/service.py: FOUND
- backend/app/processing/ai/router.py: FOUND
- backend/app/processing/ai/chat_service.py: FOUND
- backend/app/processing/ai/metadata_service.py: FOUND
- backend/app/processing/ai/streaming.py: FOUND
- backend/app/processing/embeddings/backfill.py: FOUND
- backend/app/processing/tiles/router.py: FOUND
- backend/app/processing/export/router.py: FOUND
- backend/app/processing/ingest/service.py: FOUND

Commits exist:
- 0aecf689: FOUND (Task 0)
- 62b56e25: FOUND (Task 1)
- 04b12656: FOUND (Task 2)
- 3285bfa3: FOUND (Task 3)
