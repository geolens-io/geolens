---
phase: 225-processing-port-protocol-cycle-inversion
reviewed: 2026-05-01T00:00:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - backend/app/core/processing_port.py
  - backend/app/platform/extensions/__init__.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/processing/ai/chat_service.py
  - backend/app/processing/ai/metadata_service.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/ai/service.py
  - backend/app/processing/ai/streaming.py
  - backend/app/processing/embeddings/backfill.py
  - backend/app/processing/embeddings/tasks.py
  - backend/app/processing/export/router.py
  - backend/app/processing/ingest/metadata.py
  - backend/app/processing/ingest/router.py
  - backend/app/processing/ingest/service.py
  - backend/app/processing/ingest/tasks_common.py
  - backend/app/processing/ingest/tasks_raster.py
  - backend/app/processing/ingest/tasks_reupload.py
  - backend/app/processing/ingest/tasks_vector.py
  - backend/app/processing/ingest/tasks_vrt.py
  - backend/app/processing/tiles/router.py
  - backend/tests/test_ai_chat.py
  - backend/tests/test_ai_send_sample_values.py
  - backend/tests/test_chat_narrative.py
  - backend/tests/test_layering.py
  - backend/tests/test_processing_port.py
  - backend/tests/test_sql_engine.py
findings:
  blocker: 2
  warning: 8
  total: 10
status: fixed
---

# Phase 225: Code Review Report

**Reviewed:** 2026-05-01
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Phase 225 introduced a `ProcessingPort` Protocol surface to break the
`processing/ → app.modules.catalog` import cycle and migrated 8 top-level + 26
deferred call sites onto the Port. The core scaffolding (Protocol shape,
DefaultProcessingPort delegation, get_processing_port() accessor) is well
structured and the architecture-guard test `test_no_processing_imports_catalog`
correctly fails on any new module-level catalog edge.

Two BLOCKER issues found:

1. **The architecture-guard regex is broken across the indented `processing/ai/`
   call sites.** The corrected regex `^(from|import) app\.modules\.catalog`
   uses `^` (start-of-line) with NO whitespace allowance, so it matches ONLY
   column-zero unindented imports. The phase docs assert this is intentional
   ("strict zero-hit for module-level"). However, the regex also fails to
   anchor against re-exports through `__init__.py`, which can re-introduce
   the cycle without a direct `from app.modules.catalog` line — see WR-08
   for the related concern.
2. **`DefaultProcessingPort.get_dataset()` (defaults.py:117-121) silently
   diverges from the underlying facade's joinedload semantics.** The Port's
   `get_dataset_with_attributes()` eager-loads `record + record.keywords +
   attributes`, but `get_dataset()` delegates to the facade `get_dataset()`
   with no relationship hint — callers (e.g., `export/router.py:53` →
   `dataset.record.title` at line 95, `dataset.column_info` at line 100)
   will trigger lazy-load on `dataset.record`, which fails async sessions
   with `MissingGreenlet` once the session has been closed/expired.

The remaining findings are warnings about dead code on the Port surface,
unused functions/imports introduced during migration, redundant per-iteration
port lookups inside helper loops, and gaps in the seam test coverage.

## BLOCKER Issues

### B-01: `DefaultProcessingPort.get_dataset()` returns a Dataset without eager-loaded `record` — async lazy-load will MissingGreenlet at every caller

**File:** `backend/app/platform/extensions/defaults.py:117-121`
**Issue:**

The `get_dataset()` method on `DefaultProcessingPort` delegates to
`app.modules.catalog.datasets.domain.service.get_dataset()` without specifying
any eager-load options. The callers below all access
`dataset.record.<attr>` on the returned object inside an async context:

- `backend/app/processing/export/router.py:53` —
  `dataset = await port.get_dataset(db, dataset_id)` then line 95:
  `dataset.record.title` and line 100: `dataset.column_info`. If `get_dataset`
  in the facade does not joinedload `record`, this triggers an implicit lazy
  load on the SQLAlchemy async session, which raises
  `sqlalchemy.exc.MissingGreenlet` (no greenlet in spawn for async lazy
  loads). The previous direct call (pre-Phase-225) might have used a
  `joinedload(Dataset.record)` query at the call site, but the migration
  delegated to a facade with unknown loading semantics.

This is a behavioral change — the export endpoint previously worked because
the call site explicitly loaded the relationship. Now relying on the facade
risks a runtime crash on every dataset export request.

The Port DOES provide `get_dataset_with_attributes()` (which DOES joinedload
record + keywords + attributes) but the export router doesn't use it.

**Fix:** Either (a) update `DefaultProcessingPort.get_dataset()` to
joinedload `Dataset.record` (mirroring the pre-Phase-225 inline query
shape), or (b) document on the Port docstring that callers MUST also call
`get_dataset_with_attributes()` if they need `dataset.record` access, and
update `export/router.py:53` to use that path:

```python
# defaults.py:117 — preferred fix (preserves callers as-is)
async def get_dataset(self, session, dataset_id):
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.modules.catalog.datasets.domain.models import Dataset

    stmt = (
        select(Dataset)
        .options(joinedload(Dataset.record))
        .where(Dataset.id == dataset_id)
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()
```

This preserves byte-for-byte equivalence with the pre-Phase-225 inline
query that `export/router.py` previously used. Without verifying the
facade's loading behavior, you cannot assume callers' `dataset.record.title`
access will work.

---

### B-02: `metadata_service.py` deferred ORM imports duplicate Port surface and bypass the boundary

**File:** `backend/app/processing/ai/metadata_service.py:201-226`
**Issue:**

The function `_get_related_keywords_from_embeddings()` issues two raw SQLAlchemy
queries against `app.modules.catalog.datasets.domain.models.Dataset` (line 205)
and `RecordKeyword` (line 218) using deferred imports. Both queries are
trivial enough to be on the Port:

- Line 207: `select(DatasetORM.record_id).where(DatasetORM.id == dataset_id)`
  — exactly the data the existing `port.get_dataset()` returns.
- Line 220: `select(RecordKeywordORM.keyword).where(RecordKeywordORM.record_id.in_(neighbor_ids)).distinct()`
  — almost identical to the unused `port.get_related_keywords()` (defaults.py:228).

These deferred imports satisfy the architecture-guard regex (which only
matches column-zero `from app.modules.catalog`), but they keep the dependency
edge in place and defeat the purpose of the Port boundary. A future Phase
226 enterprise overlay (referenced in processing_port.py:21) cannot
intercept these queries because they go through ORM imports the overlay
cannot replace.

This pattern was preserved during migration (see commit 1ce12dd6, "migrate
deferred imports in metadata.py + add get_attribute_metadata_orm_class")
but the deferred imports of `Dataset` and `RecordKeyword` here were NOT
migrated. They are gaps in the boundary.

**Fix:** Either (a) extend the Port with a method like
`get_record_id_for_dataset()` and `get_keywords_for_records(record_ids)`,
or (b) delete the existing-unused `port.get_related_keywords()` (which IS
on the Port surface but has no caller — see WR-01), and route this
function through the Port. The simplest fix:

```python
# metadata_service.py:202-226 — replace deferred ORM access with Port calls
async def _get_related_keywords_from_embeddings(
    session: AsyncSession,
    dataset_id: str,
    limit: int = 5,
    *,
    port: "ProcessingPort",
) -> list[str]:
    try:
        import uuid as _uuid
        dataset = await port.get_dataset(session, _uuid.UUID(dataset_id))
        if dataset is None or dataset.record_id is None:
            return []

        neighbor_ids = await get_nearest_record_ids(session, dataset.record_id, limit=limit)
        if not neighbor_ids:
            return []

        # Need a new Port method for batch keyword lookup by record_ids
        return await port.get_keywords_for_records(session, neighbor_ids)
    except Exception:
        logger.debug("Embedding neighbor keyword lookup failed", exc_info=True)
        return []
```

Without a Port method for batch keyword lookup, any enterprise overlay
that wants to add quota/audit hooks around catalog reads loses this code
path entirely.

## WARNING Issues

### W-01: `port.get_related_keywords()` is on the Port surface but has zero callers — dead code, plus the docstring TODO was never resolved

**File:** `backend/app/platform/extensions/defaults.py:228-246`, `backend/app/core/processing_port.py:245-247`
**Issue:**

The Port declares `get_related_keywords(session, dataset_id, limit=10) -> list[str]`
and the default implementation runs:

```python
# Keywords on the same record as the dataset.
# TODO(Plan 02): verify against metadata_service.py — if it uses
# embedding-based similarity, the caller should keep that logic and
# use the port only for catalog access.
stmt = (
    select(RecordKeyword.keyword)
    .join(Record, Record.id == RecordKeyword.record_id)
    .join(Dataset, Dataset.record_id == Record.id)
    .where(Dataset.id == dataset_id)
    .distinct()
    .limit(limit)
)
```

But `grep -rn "get_related_keywords" backend/` shows the only consumer is
`metadata_service._get_related_keywords_from_embeddings`, which uses a
DIFFERENT semantic (embedding-based nearest neighbors, NOT same-record
keywords). Plan 02's TODO acknowledged this divergence but never resolved
it — the Port method was added with placeholder semantics that no caller
uses.

This is dead code on a public Port surface and risks confusing future
callers who think this method does what they need.

**Fix:** Delete `get_related_keywords` from the Port and from
`DefaultProcessingPort`, OR re-implement it to actually call the
embedding-similarity path so the existing caller could use it. Removing
is the simplest fix; leaving stale TODOs in the public Protocol is a
maintenance hazard.

---

### W-02: `_validate_chat_layers` has positional `port` parameter, breaking the keyword-only convention used everywhere else in the codebase

**File:** `backend/app/processing/ai/router.py:92-98`
**Issue:**

```python
async def _validate_chat_layers(
    db: AsyncSession,
    user: Identity,
    map_id: str,
    layers: list[ChatMapLayer],
    port: "ProcessingPort",  # <-- positional, no `*` separator
) -> tuple[list[ChatMapLayer], str | None]:
```

Every other migrated function in the phase uses `*, port: "ProcessingPort"`
for keyword-only ports (e.g., `chat_service.py:625, 686, 758, 811, 924`,
`metadata_service.py:413, 430, 461, 478`, `service.py:265, 423, 615, 652, 730`).
This single inconsistency means callers can pass `port` positionally,
which (a) makes call sites less self-documenting (`_validate_chat_layers(db, user, map_id, layers, my_port)` doesn't telegraph what `my_port` is), and
(b) creates risk that a future signature change (re-ordering or inserting
parameters before `port`) silently mis-binds the wrong argument as the port.

The test `test_validate_rejects_invalid_map_id` passes `_default_port` as
the 5th positional argument (test_ai_chat.py:66), exploiting this.

**Fix:** Add a `*` separator before `port` to make it keyword-only:

```python
async def _validate_chat_layers(
    db: AsyncSession,
    user: Identity,
    map_id: str,
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> tuple[list[ChatMapLayer], str | None]:
```

Then update the four call sites in router.py (lines 278, 326) and the four
test call sites in test_ai_chat.py (lines 66, 93, 117, 155) to pass `port=...`.

---

### W-03: `metadata.py:1071-1131` performs N redundant `get_processing_port().get_attribute_metadata_orm_class()` lookups in tight loop

**File:** `backend/app/processing/ingest/metadata.py:1057-1169`
**Issue:**

The factory `_build_attribute_metadata()` (line 1057) is called inside the
loop in `generate_attribute_metadata()` (line 1143). Each iteration
re-imports `get_processing_port`, fetches the port, and resolves
`get_attribute_metadata_orm_class()`. Same in `_build_geometry_attribute_row()`
(line 1094) and `refresh_attribute_metadata()` (line 1189).

The Python import cache means the cost-per-call is small (microseconds)
but the pattern repeats N times for a dataset with N columns and is
literally re-doing the same lookup. The local `AttributeMetadata` already
resolved at the top of `generate_attribute_metadata` is shadowed inside
the helper.

```python
# metadata.py:1129-1141 — outer scope already has the class
async def generate_attribute_metadata(...):
    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()  # 1
    # ...
    for col in column_info:
        # _build_attribute_metadata calls get_processing_port().get_attribute_metadata_orm_class() AGAIN
        am = _build_attribute_metadata(...)  # 2..N+1
```

**Fix:** Pass the resolved class as a parameter, or hoist the lookup into
a module-level cached function:

```python
def _build_attribute_metadata(
    AttributeMetadata: type,  # injected
    dataset_id: uuid.UUID,
    col_name: str,
    col_type: str,
    *,
    sample_values: dict | None = None,
    ordinal_position: int | None = None,
    is_nullable: bool | None = None,
) -> "Attribute":
    ...
    return AttributeMetadata(...)
```

Then resolve `AttributeMetadata` once at the top of the calling function
and pass it down.

---

### W-04: `processing_port.py` Protocol declarations don't match `DefaultProcessingPort` parameter ordering for `get_distinct_values`

**File:** `backend/app/core/processing_port.py:219-227` vs `backend/app/platform/extensions/defaults.py:170-179`
**Issue:**

Protocol declaration (processing_port.py:219-227):
```python
async def get_distinct_values(
    self,
    session: AsyncSession,
    table_name: str,
    column_name: str,
    limit: int = 100,           # <-- positional with default
    *,
    allowed_tables: set[str] | None = None,
) -> list: ...
```

Default implementation (defaults.py:170-179) accepts `limit` positionally,
which matches. But the FakeProcessingPort in test_processing_port.py:114-117
also matches. Good so far.

The issue: the underlying call in defaults.py:173-178 passes `limit`
positionally to the catalog function (`return await get_distinct_values(session, table_name, column_name, limit, allowed_tables=...)`).
If the catalog implementation ever re-orders its parameters, this breaks.
The Protocol Specifies a specific call shape; defaults should match it
field-by-field.

This is mostly a forward-stability concern, not a bug today. The Protocol
contract is informational; positional vs keyword passing through the Port
is internal.

**Fix:** Use kwargs explicitly when delegating in `DefaultProcessingPort`:

```python
async def get_distinct_values(self, session, table_name, column_name, limit=100, *, allowed_tables=None):
    from app.modules.catalog.datasets.domain.column_stats import get_distinct_values
    return await get_distinct_values(
        session, table_name, column_name,
        limit=limit,  # <-- explicit kw, not positional
        allowed_tables=allowed_tables,
    )
```

---

### W-05: Test `test_chat_narrative.py::test_empty_result_handling` does not pass `port=` — relies on `_handle_query_data` not requiring it

**File:** `backend/tests/test_chat_narrative.py:78-104`
**Issue:**

The test calls `_handle_query_data({...}, AsyncMock(), AsyncMock(), [_make_layer()])`
without a `port` kwarg. This works because `_handle_query_data` (chat_service.py:556)
does NOT take a port parameter — it uses `validate_and_execute` and `generate_sql`
directly, neither of which need the port.

That's structurally fine, but compare to the other test `test_sandbox_error_uses_mapped_message`
on line 110-130 of the same file, which DOES pass `port=DefaultProcessingPort()`
to `_execute_chat_tool`. The asymmetry hints that whoever wrote these tests
during the migration may have been inconsistent about which functions need
ports — and didn't add coverage for the path through `_handle_query_data`
where port-related bugs could surface.

This isn't a bug in the test itself — it's testing what it claims to test.
But it's a gap: there's no test that exercises the `_handle_query_data`
return value being routed through a port-dependent chat tool.

**Fix:** Add a test that calls `_execute_chat_tool("query_data", ..., port=fake_port)`
end-to-end and verifies the GeoJSON extraction in `out["geojson"]` and
`out["bbox"]` (chat_service.py:608-611) is preserved. The current test
validates the empty-result note path but doesn't validate the Port boundary.

---

### W-06: `test_processing_port.py::FakeProcessingPort` doesn't implement all 28 Port methods, but `isinstance()` check still passes — runtime_checkable is structurally weak

**File:** `backend/tests/test_processing_port.py:22-228`
**Issue:**

The `FakeProcessingPort` class in test_processing_port.py implements 25 methods.
The Port Protocol (processing_port.py:138-337) declares 28 methods (15
read + 5 write + 1 build_gdal_source + 6 ORM-class helpers + 1
get_dataset_with_attributes).

Looking at the implementations:
- ✓ `search_datasets`, `get_dataset`, `get_record`
- ✓ `apply_visibility_filter`, `check_dataset_access`, `get_user_roles`
- ✓ `get_column_stats`, `get_distinct_values`, `extract_bbox`
- ✓ All 7 OQ-3 encapsulators (`get_records_without_embeddings`,
  `get_datasets_meta_by_ids`, `get_catalog_vocabulary`, `get_related_keywords`,
  `get_record_keyword_count`, `get_attribute_metadata`, `get_dataset_version`)
- ✓ All 4 write methods (`create_dataset`, `create_map`, `update_map`, `create_ingestion_result`)
- ✓ `build_gdal_source`
- ✓ All 6 ORM-class helpers
- ✓ `get_dataset_with_attributes`

That's 28 methods, matching the Protocol. So the class IS complete. But
the test `test_fake_processing_port_satisfies_protocol` at line 237 uses
`isinstance(port, ProcessingPort)` which on a `@runtime_checkable` Protocol
only checks for ATTRIBUTE PRESENCE, not method signatures. A future
refactor that drops a method body but keeps the name would still pass
`isinstance()`. This is a structural-typing gap, not a bug — but it
limits the value of the seam test as a regression guard.

**Fix:** Either (a) accept this limitation and document it in the test
docstring (PEP 544 runtime_checkable is intentionally weak), or (b) add
explicit method-signature checks for the most-fragile methods (e.g.,
ensure `get_distinct_values` accepts a `limit` parameter):

```python
# Sanity-check signatures explicitly
import inspect
sig = inspect.signature(port.get_distinct_values)
assert "limit" in sig.parameters, "get_distinct_values lost its limit parameter"
```

This wouldn't be a hard guard but would catch the most common drift.

---

### W-07: Test `test_chat_narrative.py::test_empty_result_handling` (line 96) calls `_handle_query_data` with `AsyncMock()` for `user`, but `user.id` is never asserted — asserting nothing about user identity

**File:** `backend/tests/test_chat_narrative.py:96-104`
**Issue:**

```python
result = await _handle_query_data(
    {"question": "How many parks are there?"},
    AsyncMock(),  # session
    AsyncMock(),  # user
    [_make_layer()],
)
```

The user parameter is `AsyncMock()` — any attribute access returns another
`AsyncMock`, including `.id`. `validate_and_execute` (chat_service.py:593)
takes `user` and uses it for table allowlisting. If a regression causes
`validate_and_execute` to require `user.id` to be a real UUID, this test
won't catch it because `AsyncMock().id` returns a Mock, not a UUID, and
the test just checks `result["note"]`.

This pattern is acceptable for narrow note-extraction tests but as a Port
boundary test it's weakly assertive.

**Fix:** Use a stricter `MagicMock(spec=Identity)` or a `SimpleNamespace(id=uuid.uuid4())`
to be explicit about what shape the user must have, so a future refactor
adding stronger user requirements can't silently break this:

```python
fake_user = SimpleNamespace(id=uuid.uuid4(), username="test_user")
result = await _handle_query_data(
    {"question": "How many parks are there?"},
    AsyncMock(),
    fake_user,
    [_make_layer()],
)
```

---

### W-08: `processing_port.py:24-28` imports `Sequence` from `typing` but Python 3.9+ should use `collections.abc.Sequence` for runtime use

**File:** `backend/app/core/processing_port.py:28`
**Issue:**

```python
from typing import Any, Protocol, Sequence, runtime_checkable
```

`typing.Sequence` is deprecated in favor of `collections.abc.Sequence` for
runtime annotations as of Python 3.9 (PEP 585). The Phase 225 docstring
mentions "Uses only stdlib types" but the typing.Sequence import is
backwards-compatible Python; the more idiomatic and forward-compatible
form is `from collections.abc import Sequence`.

This is style/convention, not a bug. The `from __future__ import annotations`
at line 24 means all annotations are stringified anyway, so runtime use
is moot. But for human readers, mixing `typing.Sequence` (deprecated)
with the rest of the typing imports invites confusion.

**Fix:**

```python
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
```

---

## Summary by File

- **processing_port.py** — Protocol shape is sound but check W-04 (parameter ordering)
  and W-08 (Sequence import).
- **defaults.py** — B-01 (get_dataset missing joinedload) is the most serious issue.
  W-01 (dead code) and W-04 (positional-vs-kw delegation) are minor.
- **metadata_service.py** — B-02 (deferred ORM imports defeat the boundary)
  needs to be addressed before claiming PROCESS-04 is complete. The phase
  intentionally left these as deferred imports, but they still constitute
  catalog dependency edges that an enterprise overlay cannot intercept.
- **router.py** (ai) — W-02 (positional port parameter) is an inconsistency.
- **metadata.py** (ingest) — W-03 (redundant per-iteration port lookups).
- **All other migrated files** — clean migration. Top-level imports correctly
  rewired, deferred imports preserved.
- **test_processing_port.py** — W-06 (runtime_checkable structural weakness).
- **test_chat_narrative.py** — W-05 + W-07 (assertions could be stricter).
- **test_layering.py** — Architecture guard regex `^(from|import) app\.modules\.catalog`
  is correctly anchored at column zero. The "no whitespace allowance" is
  intentional per the phase docs and is documented in the test docstring.
  The corrected regex is appropriate — git grep's POSIX ERE doesn't honor
  `\s` on macOS, so the literal-space form is necessary.

---

_Reviewed: 2026-05-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
