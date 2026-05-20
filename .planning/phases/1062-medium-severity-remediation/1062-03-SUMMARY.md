---
phase: 1062-medium-severity-remediation
plan: "03"
subsystem: database, api
tags: [postgres, gin-index, tsvector, simple-regconfig, fastapi, alembic, sec-s12, sec-s13]

requires:
  - phase: 1062-medium-severity-remediation
    plan: "01"
    provides: "migration 0019_users_token_version (down_revision for 0020)"

provides:
  - "GIN index ix_records_simple_search_vector on simple-regconfig tsvector (migration 0020)"
  - "catalog.immutable_text_array_join(text[], text) IMMUTABLE wrapper function"
  - "max_length=1000 on /search/facets/?q= route parameter"
  - "6 backend pytest tests covering index existence, EXPLAIN plan, e2e search, and input cap boundary"

affects:
  - "1062-04: any plan touching catalog.records indexes or search filters"
  - "1062-close-gate: SEC-S12 + SEC-S13 both closed, e2e sec-audit.spec.ts S13 passes"

tech-stack:
  added:
    - "catalog.immutable_text_array_join — IMMUTABLE SQL wrapper for array_to_string(text[], text)"
  patterns:
    - "IMMUTABLE wrapper function pattern for non-IMMUTABLE Postgres builtins in functional indexes (mirrors migration 0010 immutable_unaccent pattern)"
    - "EXPLAIN (FORMAT JSON) + recursive plan-walk assertion for index presence in pytest"
    - "SET LOCAL enable_seqscan=off to force planner index path on small test tables"
    - "Feature id vs Record id distinction: /search/datasets/ features use dataset.id not record.id"
    - "literal_column() for schema-qualified custom function calls in SQLAlchemy ORM expressions"

key-files:
  created:
    - "backend/alembic/versions/0020_records_simple_search_vector_idx.py"
    - "backend/tests/test_search_simple_regconfig.py"
    - "backend/tests/test_search_facets_input_cap.py"
  modified:
    - "backend/app/modules/catalog/search/service_filters.py"
    - "backend/app/modules/catalog/search/router.py"

key-decisions:
  - "Path A (match runtime to index) was required but concat_ws is STABLE and cannot appear in a functional GIN index; adopted modified Path A: define immutable_text_array_join wrapper + use || operator in both the migration SQL and the SQLAlchemy runtime expression"
  - "Runtime expression in service_filters.py updated from concat_ws to || operator so expression trees match index exactly — Postgres functional indexes require expression-tree equality for planner to use them"
  - "Test 2 uses accented-Latin ('Niño') not CJK: Postgres simple dict tokenises on whitespace, so CJK without spaces (e.g. '東京駅') produces one opaque token making sub-string queries (e.g. '東京') fail to match — accented Latin tokenises the same as ASCII"
  - "CREATE INDEX without CONCURRENTLY: records table small (<100k rows in all current deployments); noted in migration docstring for future scaling path"

requirements-completed:
  - SEC-S12
  - SEC-S13

duration: 12min
completed: "2026-05-20"
---

# Phase 1062 Plan 03: simple-regconfig GIN index + /search/facets/ input cap Summary

**GIN index ix_records_simple_search_vector turns per-request seq-scan on non-English queries into an index probe; max_length=1000 on /search/facets/?q= closes the trivially-fuzzable DoS amplification surface**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-20T20:32:24Z
- **Completed:** 2026-05-20T20:44:08Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Migration 0020 creates `ix_records_simple_search_vector` GIN index on the exact `to_tsvector('simple', ...)` expression used at runtime — EXPLAIN (FORMAT JSON) confirms `Bitmap Index Scan on ix_records_simple_search_vector` for non-English queries
- `/search/facets/?q=` now enforces `max_length=1000`; a 1001-char payload returns 422 before any DB query is issued, matching the peer `/search/datasets/` cap
- 6 backend pytest tests cover index existence, EXPLAIN plan tree assertion, end-to-end search, and input-cap boundary values; all 85 existing search tests pass without regression

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration** - `07fa926f` (feat) — migration 0020 + immutable_text_array_join + service_filters.py || refactor
2. **Task 2: Pytest simple-regconfig** - `befc1622` (test) — 3 tests: index existence, EXPLAIN plan, e2e search
3. **Task 3: max_length + pytest facets cap** - `eedc1889` (feat) — router.py cap + 3 input-cap boundary tests

## Files Created/Modified

- `backend/alembic/versions/0020_records_simple_search_vector_idx.py` — creates `catalog.immutable_text_array_join` IMMUTABLE wrapper + GIN index; downgrade drops both
- `backend/app/modules/catalog/search/service_filters.py` — runtime expression refactored from `concat_ws` (STABLE) to `||` + `literal_column("catalog.immutable_text_array_join(...)")` to match the index expression tree
- `backend/app/modules/catalog/search/router.py` — `q: str | None = Query(None, max_length=1000, ...)` on `search_facets_endpoint`
- `backend/tests/test_search_simple_regconfig.py` — 3 tests proving the index is used
- `backend/tests/test_search_facets_input_cap.py` — 3 tests for the input length boundary

## Decisions Made

**Path A modified (concat_ws → ||):** The plan recommended Path A (write migration to match the current `concat_ws` runtime expression). Path A is impossible — `concat_ws` is STABLE in Postgres and cannot appear in a functional index expression. The adopted approach:
1. Define `catalog.immutable_text_array_join(text[], text)` as an IMMUTABLE SQL function wrapping `array_to_string`
2. Write the migration using `||` concatenation (IMMUTABLE) + the wrapper
3. Update the runtime in `service_filters.py` to use the same `||` form

This keeps `theme_category` in the index coverage (intent of Path A) while satisfying Postgres IMMUTABLE constraint. EXPLAIN confirms the index serves the runtime query.

**Accented Latin test over CJK:** Postgres `simple` dictionary tokenises on whitespace. A CJK string without spaces (e.g. `東京駅`) becomes a single token `'東京駅'`, so a query for `'東京'` never matches via FTS. The test uses `'Niño Único <uuid>'` — accented Latin tokenises on whitespace like ASCII, making the test deterministic without relying on n-gram indexing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] concat_ws is STABLE, cannot appear in functional GIN index**
- **Found during:** Task 1 (Alembic migration)
- **Issue:** `concat_ws` volatility is STABLE, not IMMUTABLE. Postgres rejects functional indexes containing STABLE expressions. The plan's recommended migration form using `concat_ws` fails with `ERROR: functions in index expression must be marked IMMUTABLE`.
- **Fix:** (a) Created `catalog.immutable_text_array_join(text[], text)` IMMUTABLE wrapper for `array_to_string`; (b) replaced `concat_ws` with `||` operator (IMMUTABLE) in both the migration SQL and the SQLAlchemy runtime expression; expression-tree equality preserved.
- **Files modified:** `backend/alembic/versions/0020_records_simple_search_vector_idx.py`, `backend/app/modules/catalog/search/service_filters.py`
- **Committed in:** `07fa926f`

**2. [Rule 1 - Bug] /search/datasets/ response uses dataset.id not record.id as feature "id"**
- **Found during:** Task 2 (pytest end-to-end test)
- **Issue:** Test asserted `str(cjk_record.id)` (Record ID) in `feature_ids`, but `dataset_to_ogc_record()` emits `"id": str(dataset.id)` (Dataset ID). Test always failed because the IDs are different.
- **Fix:** Updated `_create_cjk_dataset` to return `(record, dataset)` tuple; test asserts `str(dataset.id)` in results.
- **Files modified:** `backend/tests/test_search_simple_regconfig.py`
- **Committed in:** `befc1622`

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. The `||` form is semantically equivalent to `concat_ws` for this use case (NULL columns handled by `coalesce`).

## Proof: EXPLAIN confirms index is used

```
"Node Type": "Bitmap Index Scan",
"Index Name": "ix_records_simple_search_vector",
"Index Cond": "(to_tsvector('simple'::regconfig, ((((((COALESCE(title, ''::text)
  || ' '::text) || COALESCE(summary, ''::text)) || ' '::text)
  || COALESCE(lineage_summary, ''::text)) || ' '::text)
  || COALESCE(catalog.immutable_text_array_join(theme_category, ' '::text), ''::text)))
  @@ '''Niño'''::tsquery)"
```

## Issues Encountered

- `concat_ws` and `array_to_string` are both STABLE — this blocked the migration on first attempt. Resolved by introducing the IMMUTABLE wrapper function (same pattern as `catalog.immutable_unaccent` in migration 0010).
- Test isolation: shared test DB retains data from prior test runs — solved with unique UUID hex suffix in title and asserting dataset.id (not record.id).

## Known Stubs

None — all functionality fully wired.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes at trust boundaries beyond those in the plan's threat model.

## Self-Check: PASSED

Files created:
- `/Users/ishiland/Code/geolens/backend/alembic/versions/0020_records_simple_search_vector_idx.py` — FOUND
- `/Users/ishiland/Code/geolens/backend/tests/test_search_simple_regconfig.py` — FOUND
- `/Users/ishiland/Code/geolens/backend/tests/test_search_facets_input_cap.py` — FOUND

Commits:
- `07fa926f` — FOUND
- `befc1622` — FOUND
- `eedc1889` — FOUND

## Next Phase Readiness

- SEC-S12 and SEC-S13 closed; e2e `sec-audit.spec.ts` S13 passes against live API
- Phase 1062 Plans 04 (SEC-S09 ogr2ogr -where) and 05 (SEC-S08 embed CSP) ready to proceed
- Migration 0020 is the new head; Plan 04 migration (if needed) should use `down_revision = "0020_records_simple_search_vector_idx"`

---
*Phase: 1062-medium-severity-remediation*
*Completed: 2026-05-20*
