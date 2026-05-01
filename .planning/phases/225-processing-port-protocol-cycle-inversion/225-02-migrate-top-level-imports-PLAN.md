---
phase: 225
plan: 02
type: execute
wave: 2
depends_on:
  - 225-01
files_modified:
  - backend/app/processing/ai/service.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/ai/chat_service.py
  - backend/app/processing/ai/metadata_service.py
  - backend/app/processing/tiles/router.py
  - backend/app/processing/export/router.py
  - backend/app/processing/embeddings/backfill.py
  - backend/app/processing/ingest/service.py
autonomous: true
requirements:
  - PROCESS-02
  - PROCESS-03
threat_model:
  block: false
  rationale: "Refactor-only — no new attack surface introduced. Imports relocate; calls go through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. No endpoint surface change, no auth/authz semantics change, no data flow change. Threats inherited from existing catalog services; Phase 225 does not change their authorization, validation, or trust boundaries."

must_haves:
  truths:
    - "All 8 module-level top-of-file `from app.modules.catalog` imports in the listed files are removed"
    - "Each migrated route function (HTTP) acquires port via `Depends(get_processing_port)`"
    - "Each migrated worker entry-point function calls `get_processing_port()` directly at the task body top"
    - "Service-layer functions in `processing/ai/{service,chat_service,metadata_service}.py` accept `port: ProcessingPort` as keyword-only parameter (D-15 / SC#5)"
    - "InstrumentedAttribute SQL uses (`select(Dataset...)`, `select(RecordKeyword...)`, `select(AttributeMetadata...)`) are replaced by Port method calls (`port.get_datasets_meta_by_ids`, `port.get_catalog_vocabulary`, `port.get_attribute_metadata`, etc.) — Pitfall 3 / Pitfall 12 resolution"
    - "AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data ONLY via Port — verifiable by grep returning zero `from app.modules.catalog` matches in those files"
    - "Type annotations use the Protocol aliases (`Dataset`, `Record`, `Map`, `DatasetGrant`) imported from `app.core.processing_port`"
    - "Full backend test suite remains green (2036/2036) — behavior is byte-for-byte identical via DefaultProcessingPort"
  artifacts:
    - path: "backend/app/processing/ai/service.py"
      provides: "Migrated AI map generation — uses Port for all catalog access"
      contains: "from app.platform.extensions import get_processing_port"
    - path: "backend/app/processing/ai/router.py"
      provides: "Migrated AI router — Depends(get_processing_port); port.get_datasets_meta_by_ids replaces InstrumentedAttribute SQL"
      contains: "Depends(get_processing_port)"
    - path: "backend/app/processing/ai/chat_service.py"
      provides: "Migrated chat editor — port: ProcessingPort parameter on chat_edit_map / chat_stream"
      contains: "port: ProcessingPort"
    - path: "backend/app/processing/ai/metadata_service.py"
      provides: "Migrated metadata service — uses Port for vocabulary/related-keywords/attributes; port: ProcessingPort parameter"
      contains: "port: ProcessingPort"
    - path: "backend/app/processing/tiles/router.py"
      provides: "Migrated tiles router — Depends(get_processing_port); Protocol-typed annotations"
      contains: "Depends(get_processing_port)"
    - path: "backend/app/processing/export/router.py"
      provides: "Migrated export router — Depends(get_processing_port)"
      contains: "Depends(get_processing_port)"
    - path: "backend/app/processing/embeddings/backfill.py"
      provides: "Migrated embeddings backfill — port.get_records_without_embeddings replaces direct SQL"
      contains: "port = get_processing_port()"
    - path: "backend/app/processing/ingest/service.py"
      provides: "Migrated ingest service top-level imports — port.create_dataset / port.get_user_roles via direct call"
      contains: "from app.platform.extensions import get_processing_port"
  key_links:
    - from: "backend/app/processing/ai/router.py"
      to: "get_processing_port"
      via: "FastAPI Depends"
      pattern: "Depends\\(get_processing_port\\)"
    - from: "backend/app/processing/ai/service.py:generate_map_from_prompt"
      to: "port: ProcessingPort parameter"
      via: "explicit kwarg"
      pattern: "port: ProcessingPort"
    - from: "backend/app/processing/embeddings/backfill.py"
      to: "port.get_records_without_embeddings"
      via: "Port method replacing direct select(Record) query"
      pattern: "port\\.get_records_without_embeddings"
---

<objective>
Migrate the **8 module-level top-of-file** `from app.modules.catalog.*` imports out of `backend/app/processing/`. Replace each with the Protocol-aliased typing import (`from app.core.processing_port import Dataset, Record, ...`), the Port accessor (`from app.platform.extensions import get_processing_port`), and call-site rewrites (`port.method(...)` instead of direct `function(...)`).

Service-layer functions in `processing/ai/` get `port: ProcessingPort` as a **keyword-only** parameter (D-15) so the FakeProcessingPort seam test in Plan 04 can swap in a stub. HTTP routes acquire the port via `Depends(get_processing_port)`. Worker entry-point functions call `get_processing_port()` directly.

InstrumentedAttribute SQL uses (`select(Dataset.id, Dataset.table_name, ...)`, `select(RecordKeyword.keyword).distinct()`, `select(AttributeMetadata)...`) — the Pitfall 3 / Pitfall 12 cases — are replaced with Port method calls (`port.get_datasets_meta_by_ids(...)`, `port.get_catalog_vocabulary(...)`, `port.get_attribute_metadata(...)`).

Behavior is byte-for-byte identical because every Port call routes to `DefaultProcessingPort` which delegates to the original catalog function. The 2036/2036 backend test suite must remain green at the end of this plan.

Purpose: Close the AI / tiles / export / ingest top-level coupling. After this plan + Plan 03, `grep -RE "^(from|import) app\.modules\.catalog" backend/app/processing/` returns zero hits.

Output: 8 modified files. No new files.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-CONTEXT.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-01-SUMMARY.md
@backend/app/core/processing_port.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/app/processing/ai/service.py
@backend/app/processing/ai/router.py
@backend/app/processing/ai/chat_service.py
@backend/app/processing/ai/metadata_service.py
@backend/app/processing/tiles/router.py
@backend/app/processing/export/router.py
@backend/app/processing/embeddings/backfill.py
@backend/app/processing/ingest/service.py

<interfaces>
<!-- Plan 01 produced these. Plan 02 consumes them. -->

From backend/app/core/processing_port.py (after Plan 01):
```python
class ProcessingPort(Protocol):
    # Read methods
    async def get_dataset(self, session, dataset_id) -> DatasetProtocol | None: ...
    async def get_record(self, session, record_id) -> RecordProtocol | None: ...
    async def search_datasets(self, session, user, user_roles, filters) -> tuple[list[DatasetProtocol], int]: ...
    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None) -> Select: ...
    async def check_dataset_access(self, session, dataset, dataset_id, user, *, user_roles=None) -> set[str]: ...
    async def get_user_roles(self, session, user) -> set[str]: ...
    async def get_column_stats(self, session, table_name, column_name, *, class_count=5, allowed_tables=None) -> dict: ...
    async def get_distinct_values(self, session, table_name, column_name, limit=100, *, allowed_tables=None) -> list: ...
    def extract_bbox(self, dataset) -> list[float] | None: ...
    # OQ-3 InstrumentedAttribute encapsulators
    async def get_records_without_embeddings(self, session, *, force=False) -> list[RecordProtocol]: ...
    async def get_datasets_meta_by_ids(self, session, ids) -> list[tuple[uuid.UUID, str, str | None]]: ...
    async def get_catalog_vocabulary(self, session) -> list[str]: ...
    async def get_related_keywords(self, session, dataset_id, limit=10) -> list[str]: ...
    async def get_record_keyword_count(self, session, record_id) -> int: ...
    async def get_attribute_metadata(self, session, dataset_id) -> list[AttributeProtocol]: ...
    async def get_dataset_version(self, session, dataset_id) -> DatasetVersionProtocol | None: ...
    # Write methods
    async def create_dataset(self, session, table_name, title, created_by, *, summary=None, visibility="private", ingestion=None) -> DatasetProtocol: ...
    async def create_map(self, session, name, description, created_by, notes=None) -> MapProtocol: ...
    async def update_map(self, session, map_id, **kwargs) -> tuple[MapProtocol, list, str | None, str | None]: ...
    def create_ingestion_result(self, **kwargs) -> "IngestionResult": ...
    # Source preview
    def build_gdal_source(self, service_type, base_url, layer_name, layer_id=None, token=None, order_field=None, result_limit=None) -> tuple[str, str]: ...

# Type aliases
Dataset = DatasetProtocol
Record = RecordProtocol
Map = MapProtocol
DatasetGrant = DatasetGrantProtocol
DatasetVersion = DatasetVersionProtocol
```

From backend/app/platform/extensions/__init__.py (after Plan 01):
```python
def get_processing_port() -> "ProcessingPort":
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]
```

From RESEARCH.md §Caller Migration Inventory — concrete BEFORE/AFTER for each of the 8 files (verbatim):

### `processing/ai/service.py` BEFORE (lines 31-39):
```python
from app.core.identity import Identity
from app.core.config import settings
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.modules.catalog.datasets.domain.column_stats import get_column_stats
from app.modules.catalog.maps.service import create_map, update_map
from app.processing.ai.token_usage import record_token_usage
from app.modules.catalog.search.service import SearchFilters, search_datasets
```

### `processing/ai/service.py` AFTER:
```python
from typing import TYPE_CHECKING

from app.core.identity import Identity
from app.core.config import settings
from app.core.processing_port import Dataset, DatasetGrant, Record
from app.platform.extensions import get_processing_port
from app.processing.ai.token_usage import record_token_usage

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
    from app.modules.catalog.search.service import SearchFilters
```

All call-site rewrites in this file:
- `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` → `port.apply_visibility_filter(stmt, user, user_roles, Record_orm, DatasetGrant_orm)` — but Record/DatasetGrant aliases are now Protocol typing constructs, NOT ORM classes. **The ORM classes are still needed for `record_cls` / `grant_cls` arguments to apply_visibility_filter** (Pitfall 3). RESOLUTION: Since `apply_visibility_filter`'s `record_cls`/`grant_cls` are typed `Any` and used in SQL expressions, callers must obtain the ORM classes themselves. **Use a deferred import inside the calling function**: `from app.modules.catalog.datasets.domain.models import Record as RecordORM, DatasetGrant as DatasetGrantORM` — but this trips the architecture guard. **Final resolution**: Add `port.get_record_cls()` and `port.get_grant_cls()` Port helper methods returning the concrete ORM classes — but this leaks ORM through the Port. **Best resolution**: Inline the visibility filter call by exposing a higher-level Port method that takes the user/roles and returns the filtered query. Add to Plan 02 — refine `apply_visibility_filter` Port semantics: instead of accepting `record_cls`/`grant_cls`, the Port method internally references the ORM classes via deferred import inside DefaultProcessingPort. **The Port signature changes (in Plan 01) to OMIT record_cls/grant_cls**, and the implementation in DefaultProcessingPort imports them locally. See action item below for refactoring this.

Actually — re-reading the existing `catalog/authorization.py:34` signature: `apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls=None)`. The reason `record_cls` is passed is so the catalog function doesn't have to import the ORM class itself (since callers may pass `Record`, but also possibly other entity classes). It's a flexible API.

**Resolution for Phase 225 (kept from Plan 01)**: The Port's `apply_visibility_filter` signature DOES take `record_cls` and `grant_cls` as `Any` (Pitfall 3 — InstrumentedAttribute is opaque to typing). Callers in `processing/*` need the concrete ORM classes. Adding deferred imports of `Record`/`DatasetGrant` inside processing/ai/service.py would trip the architecture guard.

**Best resolution (this plan adopts)**: Add NEW Port helper methods on `ProcessingPort` (Plan 01 already declared them — see check below):
- `port.get_record_orm_class() -> type` — returns the concrete `Record` ORM class
- `port.get_grant_orm_class() -> type` — returns the concrete `DatasetGrant` ORM class

Wait — Plan 01 did NOT declare these. They need to be added. **Action: amend Plan 01 in this plan via Task 0 by adding the two helper methods to the Port + Default impl.** OR — simpler — restructure `apply_visibility_filter` on the Port so callers don't need to pass the ORM class.

**The cleanest resolution that does NOT amend Plan 01**: The Port already exposes `get_records_without_embeddings`, `get_datasets_meta_by_ids`, `get_catalog_vocabulary`, etc. — these encapsulate the SQL queries that need the ORM classes. For `apply_visibility_filter`, change the Port semantic: provide a high-level method `port.filter_visible_datasets(stmt, user, user_roles)` that internally constructs the visibility filter using the concrete ORM classes inside DefaultProcessingPort. Callers no longer pass `record_cls`/`grant_cls`. The `apply_visibility_filter` Port method (taking record_cls/grant_cls) STAYS for genericity (e.g., if called against a non-Dataset entity), but call sites in processing/* migrate to the new high-level helper.

**Final design choice for Plan 02**: 
1. Add Task 0 at the start of this plan to AMEND Plan 01's outputs by adding two helper methods on the Port:
   - `port.get_record_orm_class() -> type` 
   - `port.get_grant_orm_class() -> type`
2. Each call site does:
   ```python
   Record_cls = port.get_record_orm_class()
   DatasetGrant_cls = port.get_grant_orm_class()
   filtered_stmt = port.apply_visibility_filter(stmt, user, user_roles, Record_cls, DatasetGrant_cls)
   ```
3. This is the same pattern existing code uses, just routed through the Port.

This adds minimal complexity and preserves the existing query semantics.

### `processing/ai/router.py` AFTER:
```python
from typing import TYPE_CHECKING
from fastapi import Depends
from app.core.processing_port import Dataset, Map
from app.platform.extensions import get_processing_port

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```
Function signatures gain `port: "ProcessingPort" = Depends(get_processing_port)`. The InstrumentedAttribute SQL at line 139 (`select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(Dataset.id.in_(dataset_uuids))`) becomes `await port.get_datasets_meta_by_ids(db, dataset_uuids)` returning `list[tuple[uuid.UUID, str, str | None]]`. Callers iterate `for dataset_id, table_name, geometry_type in result:`.

### `processing/ai/chat_service.py` AFTER:
- Remove `from app.modules.catalog.datasets.domain.column_stats import get_column_stats, get_distinct_values`
- Add `from typing import TYPE_CHECKING`
- Add `if TYPE_CHECKING: from app.core.processing_port import ProcessingPort`
- Service-layer function signatures gain `*, port: "ProcessingPort"` parameter
- Calls: `await get_column_stats(...)` → `await port.get_column_stats(...)`, same for `get_distinct_values`

### `processing/ai/metadata_service.py` AFTER:
- Remove `from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword`
- Add `from app.core.processing_port import Dataset, Record` (Protocol aliases for type annotations)
- Add `from typing import TYPE_CHECKING`
- Add `if TYPE_CHECKING: from app.core.processing_port import ProcessingPort`
- Service-layer function `_build_dataset_context(...)` gains `port: "ProcessingPort"` keyword-only parameter
- `select(RecordKeyword.keyword).distinct()` → `await port.get_catalog_vocabulary(session)`
- `select(RecordKeyword)...` related-keywords query → `await port.get_related_keywords(session, dataset_id, limit)`
- `select(AttributeMetadata).where(AttributeMetadata.dataset_id == ...)` → `await port.get_attribute_metadata(session, dataset_id)`
- The `select(Dataset).options(joinedload(...))` query that joins record + attributes — convert to a Port method or keep using `port.get_dataset()` and accept that attributes load lazily. **Pitfall 2 mitigation**: if the existing `_build_dataset_context` query does `joinedload(Dataset.attributes)` then call site uses `dataset.attributes` directly without await. Plan 02 must preserve this — use `port.get_attribute_metadata(session, dataset.id)` to fetch attributes separately, OR add a new Port method `port.get_dataset_with_attributes(session, dataset_id)` that does the joinedload. **Action**: add `port.get_dataset_with_attributes(session, dataset_id)` to the Port (Task 0 amendment) so the existing semantics are preserved exactly.

### `processing/tiles/router.py` AFTER:
- Remove `from app.modules.catalog.authorization import check_dataset_access, get_user_roles`
- Remove `from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant`
- Add `from app.core.processing_port import Dataset, DatasetGrant` (aliases)
- Add `from typing import TYPE_CHECKING`
- Add `if TYPE_CHECKING: from app.core.processing_port import ProcessingPort`
- Routes gain `port: "ProcessingPort" = Depends(get_processing_port)`
- `await check_dataset_access(...)` → `await port.check_dataset_access(...)`
- `await get_user_roles(...)` → `await port.get_user_roles(...)`
- `select(Dataset).where(...)` SQL InstrumentedAttribute uses — replace via `port.get_record_orm_class()` if absolutely required (rare in tiles router) OR refactor to use existing Port methods. **Plan 02 must grep tiles/router.py for all `select(Dataset)`, `select(DatasetGrant)`, `Record.id`, `DatasetGrant.dataset_id` SQL uses and route each through the Port (or via `port.get_record_orm_class()` helper).**

### `processing/export/router.py` AFTER:
- Remove `from app.modules.catalog.authorization import check_dataset_access`
- Remove `from app.modules.catalog.datasets.domain.service import get_dataset`
- Add `from typing import TYPE_CHECKING`
- Add `if TYPE_CHECKING: from app.core.processing_port import ProcessingPort`
- Routes gain `port: "ProcessingPort" = Depends(get_processing_port)`
- `await check_dataset_access(...)` → `await port.check_dataset_access(...)`
- `await get_dataset(...)` → `await port.get_dataset(...)`
- This file has the cleanest migration — no SQL InstrumentedAttribute uses (per RESEARCH.md).

### `processing/embeddings/backfill.py` AFTER:
- Remove `from app.modules.catalog.datasets.domain.models import Record`
- Add `from app.core.processing_port import Record` (Protocol alias for type annotation)
- Add `from app.platform.extensions import get_processing_port`
- Function entry-point body adds: `port = get_processing_port()`
- `select(Record).outerjoin(RecordEmbedding)...options(joinedload(Record.keywords))` query → `records = await port.get_records_without_embeddings(session, force=force)`
- Iterate `records` as `RecordProtocol` instances — fields `record.id`, `record.title`, `record.keywords`, `record.created_at`

### `processing/ingest/service.py` AFTER:
- Remove `from app.modules.catalog.authorization import get_user_roles`
- Remove `from app.modules.catalog.datasets.domain.models import Dataset`
- Remove `from app.modules.catalog.datasets.domain.service import create_dataset`
- Add `from app.core.processing_port import Dataset` (Protocol alias)
- Add `from app.platform.extensions import get_processing_port`
- Worker entry-point function body adds: `port = get_processing_port()`
- `await get_user_roles(...)` → `await port.get_user_roles(...)`
- `await create_dataset(...)` → `await port.create_dataset(...)`
- Lines 320, 368, 405 are deferred imports — those are Plan 03's scope, not Plan 02. Plan 02 only touches lines 20, 22, 23 (top-level imports).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0: Amend Plan 01 outputs — add three Port helper methods (get_record_orm_class, get_grant_orm_class, get_dataset_with_attributes)</name>
  <files>backend/app/core/processing_port.py, backend/app/platform/extensions/defaults.py</files>
  <read_first>
    - backend/app/core/processing_port.py (Plan 01 output — read entire file)
    - backend/app/platform/extensions/defaults.py (Plan 01 output — read DefaultProcessingPort class)
    - backend/app/modules/catalog/datasets/domain/models.py (confirm Record, DatasetGrant, AttributeMetadata are exposed)
    - backend/app/processing/ai/metadata_service.py (read existing _build_dataset_context query — line ~120-200, and joinedload patterns)
  </read_first>
  <action>
This task amends Plan 01's outputs to support three needs Plan 02 surfaces:

**1. Add `get_record_orm_class()` and `get_grant_orm_class()` to the Port** — these helper methods return the concrete SQLAlchemy ORM classes so callers can pass them to `apply_visibility_filter` (which uses InstrumentedAttribute SQL expressions). Add to `core/processing_port.py` Protocol declaration:

```python
def get_record_orm_class(self) -> type: ...
def get_grant_orm_class(self) -> type: ...
```

(Both are sync — they return type objects.)

In `defaults.py` `DefaultProcessingPort` class, add:
```python
def get_record_orm_class(self):  # type: ignore[no-untyped-def]
    from app.modules.catalog.datasets.domain.models import Record
    return Record

def get_grant_orm_class(self):  # type: ignore[no-untyped-def]
    from app.modules.catalog.datasets.domain.models import DatasetGrant
    return DatasetGrant
```

**2. Add `get_dataset_with_attributes()` Port method** — preserves the `joinedload(Dataset.attributes)` semantics that `metadata_service.py:_build_dataset_context` requires (Pitfall 2). Add to `core/processing_port.py` Protocol:

```python
async def get_dataset_with_attributes(
    self, session: AsyncSession, dataset_id: uuid.UUID
) -> DatasetProtocol | None: ...
```

In `defaults.py`:
```python
async def get_dataset_with_attributes(self, session, dataset_id):  # type: ignore[no-untyped-def]
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    stmt = (
        select(Dataset)
        .options(
            joinedload(Dataset.record).joinedload(Record.keywords),
            joinedload(Dataset.attributes),
        )
        .where(Dataset.id == dataset_id)
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()
```

**3. Verify the new methods don't violate guards** — the methods sit on `DefaultProcessingPort` (in `platform/extensions/defaults.py`), which is allowed to import from `app.modules.catalog.*` (Phase 214 IDENT-01 only restricts `core/`). The Protocol declarations in `core/processing_port.py` use `type` and `DatasetProtocol` — both stdlib / Protocol-typed, no `app.modules.*` runtime edge.

Save both files. Run smoke import tests to confirm `DefaultProcessingPort()` still satisfies `ProcessingPort`.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.core.processing_port import ProcessingPort; from app.platform.extensions.defaults import DefaultProcessingPort; port = DefaultProcessingPort(); assert isinstance(port, ProcessingPort), 'DefaultProcessingPort no longer satisfies ProcessingPort after amendment'; assert callable(port.get_record_orm_class), 'get_record_orm_class missing'; assert callable(port.get_grant_orm_class), 'get_grant_orm_class missing'; assert callable(port.get_dataset_with_attributes), 'get_dataset_with_attributes missing'; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - `core/processing_port.py` declares `get_record_orm_class`, `get_grant_orm_class`, `get_dataset_with_attributes` (verifiable: `grep -cE "(get_record_orm_class|get_grant_orm_class|get_dataset_with_attributes)" backend/app/core/processing_port.py` returns ≥ 3).
    - `defaults.py` `DefaultProcessingPort` implements all three (verifiable: `awk '/^class DefaultProcessingPort/,/^class [^D]/' backend/app/platform/extensions/defaults.py | grep -cE "(get_record_orm_class|get_grant_orm_class|get_dataset_with_attributes)"` returns ≥ 3).
    - DefaultProcessingPort still structurally satisfies ProcessingPort: smoke import passes (above command).
    - Phase 214 / Phase 224 architecture guards still pass: `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -x` exits 0.
    - Full backend test suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
  </acceptance_criteria>
  <done>
    Three new Port helpers added without breaking Plan 01 invariants. DefaultProcessingPort still satisfies ProcessingPort. All architecture guards still pass. 2036/2036 baseline holds.
  </done>
</task>

<task type="auto">
  <name>Task 1: Migrate processing/ai/service.py and processing/ai/router.py top-level imports</name>
  <files>backend/app/processing/ai/service.py, backend/app/processing/ai/router.py</files>
  <read_first>
    - backend/app/processing/ai/service.py (entire file — read top imports + every call site of apply_visibility_filter, extract_bbox, get_column_stats, create_map, update_map, search_datasets, SearchFilters)
    - backend/app/processing/ai/router.py (entire file — read top imports + InstrumentedAttribute SQL at line ~139)
    - backend/app/core/processing_port.py (after Task 0 — confirm Port surface)
    - backend/app/platform/extensions/__init__.py (after Plan 01 — confirm get_processing_port reachable)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Caller Migration Inventory — `processing/ai/service.py` and `ai/router.py` subsections)
  </read_first>
  <action>
**File 1: `backend/app/processing/ai/service.py`**

Read the file end-to-end first; identify every call site that uses one of: `apply_visibility_filter`, `extract_bbox`, `get_column_stats`, `create_map`, `update_map`, `search_datasets`, `SearchFilters`, `Dataset`, `DatasetGrant`, `Record`.

Apply this exact migration:

a) Replace the top imports. Remove these lines:
```python
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.datasets.domain.utils import extract_bbox
from app.modules.catalog.datasets.domain.column_stats import get_column_stats
from app.modules.catalog.maps.service import create_map, update_map
from app.modules.catalog.search.service import SearchFilters, search_datasets
```

Replace with:
```python
from typing import TYPE_CHECKING

from app.core.processing_port import Dataset, DatasetGrant, Record

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
    from app.modules.catalog.search.service import SearchFilters
```

b) Add `port: "ProcessingPort"` keyword-only parameter to ALL service-layer function signatures that today call any of the removed functions. Per D-15, the parameter is keyword-only with no default. Targets (planner re-greps for completeness):
- `generate_map_from_prompt`
- `stream_generate_map`
- `_execute_search_tool`
- `_execute_get_dataset_details`
- `_build_map_spec_and_persist` (or whatever the inner helper is named — re-grep)
- Any helper invoked by these that touches catalog data

Pattern: `async def fn(...existing params..., *, port: "ProcessingPort", language=None) -> ...`

The `port=` parameter goes AFTER any existing `*` divider. If the function lacks a `*` divider, add one before `port`. Plumb `port` through to inner calls (each inner function that invokes a Port method takes `port` as a keyword-only parameter and the outer function passes it explicitly).

c) Rewrite call sites:
- `await search_datasets(session, user, user_roles, filters)` → `await port.search_datasets(session, user, user_roles, filters)`
- `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` → 
  ```python
  Record_orm = port.get_record_orm_class()
  DatasetGrant_orm = port.get_grant_orm_class()
  filtered_stmt = port.apply_visibility_filter(stmt, user, user_roles, Record_orm, DatasetGrant_orm)
  ```
- `extract_bbox(dataset)` → `port.extract_bbox(dataset)`
- `await get_column_stats(session, table_name, column_name, ...)` → `await port.get_column_stats(session, table_name, column_name, ...)`
- `await create_map(session, name, description, created_by, notes)` → `await port.create_map(session, name, description, created_by, notes)`
- `await update_map(session, map_id, **kwargs)` → `await port.update_map(session, map_id, **kwargs)`

The local name `Dataset` (from `from app.core.processing_port import Dataset`) is still usable in type annotations (`dataset: Dataset`). For SQL expressions where `Dataset` was used as InstrumentedAttribute (`select(Dataset).where(...)`), use `port.get_record_orm_class()` if `Dataset` was the target — but check the file: `processing/ai/service.py` likely doesn't use `Dataset` in SQL expressions. If it does use SQL queries, those need to be replaced with Port methods or the ORM class fetched via Port helper.

d) Verify: run `cd backend && uv run ruff check app/processing/ai/service.py` clean. Run `grep -n "from app.modules.catalog" backend/app/processing/ai/service.py` returns no output (exit 1).

**File 2: `backend/app/processing/ai/router.py`**

Read the file end-to-end. Identify the route function signatures and the line ~139 InstrumentedAttribute SQL.

a) Replace top imports. Remove:
```python
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps.models import Map
```

Replace with:
```python
from typing import TYPE_CHECKING
from app.core.processing_port import Dataset, Map
from app.platform.extensions import get_processing_port

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```

b) Add `port: "ProcessingPort" = Depends(get_processing_port)` to every route function in this file. Pattern:
```python
async def some_route(
    ...,
    db: AsyncSession = Depends(get_db),
    current_user: Identity = Depends(get_current_active_user),
    port: "ProcessingPort" = Depends(get_processing_port),
):
    ...
```

c) Rewrite call sites:
- `await get_user_roles(db, user)` → `await port.get_user_roles(db, user)`
- The InstrumentedAttribute SQL at line ~139:
  ```python
  result = await db.execute(
      select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(
          Dataset.id.in_(dataset_uuids)
      )
  )
  ```
  becomes:
  ```python
  rows = await port.get_datasets_meta_by_ids(db, dataset_uuids)
  # rows is list[tuple[UUID, str, str | None]] — (id, table_name, geometry_type)
  ```
  Then iterate `for dataset_id, table_name, geometry_type in rows:` instead of `for row in result:`.

d) Pass `port` to any service-layer call (e.g., `await generate_map_from_prompt(..., port=port)`). The `service.py` functions now require `port` per Task 1's File 1 changes.

e) Verify: run `cd backend && uv run ruff check app/processing/ai/router.py` clean. Run `grep -n "from app.modules.catalog" backend/app/processing/ai/router.py` returns no output (exit 1).
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ai/service.py app/processing/ai/router.py && grep -REn "^(from|import) app\.modules\.catalog" backend/app/processing/ai/service.py backend/app/processing/ai/router.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ai/service.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/ai/router.py` returns 0.
    - `grep -c "from app.core.processing_port import" backend/app/processing/ai/service.py` returns ≥ 1.
    - `grep -c "from app.core.processing_port import" backend/app/processing/ai/router.py` returns ≥ 1.
    - `grep -c "from app.platform.extensions import get_processing_port" backend/app/processing/ai/service.py` returns ≥ 0 (service.py uses port via parameter, may not import get_processing_port at top — but if it does for tests, that's fine).
    - `grep -c "Depends(get_processing_port)" backend/app/processing/ai/router.py` returns ≥ 1.
    - `grep -c "port: ProcessingPort\|port: \"ProcessingPort\"" backend/app/processing/ai/service.py` returns ≥ 1 (D-15 keyword-only parameter present).
    - `grep -c "port.search_datasets\|port.apply_visibility_filter\|port.extract_bbox\|port.create_map\|port.update_map\|port.get_column_stats" backend/app/processing/ai/service.py` returns ≥ 5 (most Port calls replaced).
    - `grep -c "port.get_user_roles\|port.get_datasets_meta_by_ids" backend/app/processing/ai/router.py` returns ≥ 2.
    - ruff clean: `cd backend && uv run ruff check app/processing/ai/service.py app/processing/ai/router.py` exits 0.
    - Targeted tests still pass: `cd backend && uv run pytest tests/test_ai_chat.py tests/test_ai_metadata.py tests/test_ai_service.py tests/test_ai_router.py -x` exits 0 (or whichever subset of tests covers `ai/service.py` + `ai/router.py`).
    - Full suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
  </acceptance_criteria>
  <done>
    `processing/ai/service.py` and `processing/ai/router.py` no longer import from `app.modules.catalog`. All call sites route through Port. Service-layer functions take `port` as keyword-only parameter (D-15 / SC#5). InstrumentedAttribute SQL at router.py:139 replaced by `port.get_datasets_meta_by_ids`. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 2: Migrate processing/ai/chat_service.py, processing/ai/metadata_service.py, processing/embeddings/backfill.py top-level imports</name>
  <files>backend/app/processing/ai/chat_service.py, backend/app/processing/ai/metadata_service.py, backend/app/processing/embeddings/backfill.py</files>
  <read_first>
    - backend/app/processing/ai/chat_service.py (entire file)
    - backend/app/processing/ai/metadata_service.py (entire file — particularly `_build_dataset_context`, `_get_catalog_vocabulary`, `_get_related_keywords_from_embeddings` and the joinedload Dataset query)
    - backend/app/processing/embeddings/backfill.py (entire file — particularly the `select(Record).outerjoin(RecordEmbedding)` query)
    - backend/app/core/processing_port.py (after Task 0)
    - backend/app/platform/extensions/defaults.py (after Task 0 — confirm get_records_without_embeddings, get_catalog_vocabulary, get_related_keywords, get_attribute_metadata, get_dataset_with_attributes implementations)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Caller Migration Inventory — `chat_service.py`, `metadata_service.py`, `backfill.py` subsections)
  </read_first>
  <action>
**File 1: `backend/app/processing/ai/chat_service.py`**

a) Remove top import:
```python
from app.modules.catalog.datasets.domain.column_stats import (
    get_column_stats,
    get_distinct_values,
)
```

b) Add at top:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```

c) Identify all service-layer functions that today call `get_column_stats` or `get_distinct_values`. Add `*, port: "ProcessingPort"` keyword-only parameter (no default — D-15). Plumb through to callers if needed.

d) Replace call sites:
- `await get_column_stats(session, table_name, column_name, ...)` → `await port.get_column_stats(session, table_name, column_name, ...)`
- `await get_distinct_values(session, table_name, column_name, ...)` → `await port.get_distinct_values(session, table_name, column_name, ...)`

e) The router that calls these chat-service functions passes `port` explicitly. If the router is `processing/ai/router.py`, that file already received `port` via Task 1. Update the call: `await chat_edit_map(..., port=port)`.

**File 2: `backend/app/processing/ai/metadata_service.py`**

This file is the most complex migration in Plan 02. Read it end-to-end.

a) Remove top import:
```python
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordKeyword,
)
```

b) Add at top:
```python
from typing import TYPE_CHECKING

from app.core.processing_port import Dataset, Record

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```

c) `_build_dataset_context(session, dataset_id, ...)` — gains `*, port: "ProcessingPort"` parameter. Replace its existing `select(Dataset).options(joinedload(Dataset.record).joinedload(Record.keywords), joinedload(Dataset.attributes)).where(Dataset.id == dataset_id)` query with:
```python
dataset = await port.get_dataset_with_attributes(session, dataset_id)
```
The returned `dataset` has `record` (with `keywords`) and `attributes` already loaded (Task 0's get_dataset_with_attributes does the same joinedload).

d) `_get_catalog_vocabulary(session)` (or wherever the `select(RecordKeyword.keyword).distinct()` query lives) — gains `*, port: "ProcessingPort"` parameter. Replace the SQL with:
```python
return await port.get_catalog_vocabulary(session)
```

e) `_get_related_keywords_from_embeddings(session, dataset_id, ...)` — gains `*, port: "ProcessingPort"` parameter. **NOTE**: Read the existing logic carefully. If it uses embedding similarity (e.g., calls into `embeddings_service` or computes vector similarity), the existing semantics may be richer than the simple `port.get_related_keywords` from Task 0. **Two paths**:
- If the function is just keyword join across records: replace with `await port.get_related_keywords(session, dataset_id, limit)`.
- If the function uses embedding similarity: keep the existing logic for the embedding step, but replace any SQL that uses `RecordKeyword`/`Record` directly with Port method calls. The embedding similarity computation may use `embeddings_service` (which lives in `processing/embeddings/`, NOT catalog) — that part stays.

f) Any helper that uses `select(AttributeMetadata)` directly — replace with `await port.get_attribute_metadata(session, dataset_id)`. Iterate the returned list to mirror existing semantics.

g) Quality scoring helpers that use `select(func.count()).where(RecordKeyword.record_id == ...)` — replace with `await port.get_record_keyword_count(session, record_id)`.

h) `RecordKeyword` is no longer in scope as a runtime symbol; if any annotation references it, switch to `KeywordProtocol` (import from `app.core.processing_port`). The Protocol matches structurally.

**File 3: `backend/app/processing/embeddings/backfill.py`**

a) Remove top import:
```python
from app.modules.catalog.datasets.domain.models import Record
```

b) Add at top:
```python
from app.core.processing_port import Record
from app.platform.extensions import get_processing_port
```

c) The function entry-point body (e.g., `backfill_embeddings`) — add at the top:
```python
port = get_processing_port()
```

d) Replace the existing `select(Record).outerjoin(RecordEmbedding, ...)` query (likely around line 50-100) with:
```python
records = await port.get_records_without_embeddings(session, force=force)
```
Iterate `records` — each is a `RecordProtocol` with fields `.id`, `.title`, `.summary`, `.keywords`, `.created_at`. The `RecordEmbedding` lookup logic stays in this file (it's processing-domain), only the catalog-side `Record` access goes through the Port.

e) Verify the keyword field access still works: `record.keywords` returns `Sequence[KeywordProtocol]`; iterate `kw.keyword for kw in record.keywords`.

f) For each file: `cd backend && uv run ruff check {file}` clean. `grep -n "from app.modules.catalog" {file}` returns no output (exit 1).
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ai/chat_service.py app/processing/ai/metadata_service.py app/processing/embeddings/backfill.py && grep -REn "^(from|import) app\.modules\.catalog" backend/app/processing/ai/chat_service.py backend/app/processing/ai/metadata_service.py backend/app/processing/embeddings/backfill.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ai/chat_service.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/ai/metadata_service.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/embeddings/backfill.py` returns 0.
    - `grep -c "port: ProcessingPort\|port: \"ProcessingPort\"" backend/app/processing/ai/chat_service.py` returns ≥ 1 (D-15 parameter present).
    - `grep -c "port: ProcessingPort\|port: \"ProcessingPort\"" backend/app/processing/ai/metadata_service.py` returns ≥ 1.
    - `grep -c "port.get_column_stats\|port.get_distinct_values" backend/app/processing/ai/chat_service.py` returns ≥ 2.
    - `grep -c "port.get_dataset_with_attributes\|port.get_catalog_vocabulary\|port.get_attribute_metadata\|port.get_related_keywords" backend/app/processing/ai/metadata_service.py` returns ≥ 2.
    - `grep -c "get_processing_port()\|port.get_records_without_embeddings" backend/app/processing/embeddings/backfill.py` returns ≥ 2.
    - ruff clean for all three files.
    - Targeted tests pass: `cd backend && uv run pytest tests/test_embedding_backfill.py tests/test_ai_metadata.py tests/test_ai_chat.py -x` exits 0.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
  </acceptance_criteria>
  <done>
    `chat_service.py`, `metadata_service.py`, `backfill.py` no longer import from `app.modules.catalog`. AI features (per PROCESS-03) consume catalog data exclusively through the Port. Service-layer functions take `port` as keyword-only parameter. SQL InstrumentedAttribute uses (RecordKeyword, AttributeMetadata, Record) replaced by Port method calls. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 3: Migrate processing/tiles/router.py, processing/export/router.py, processing/ingest/service.py top-level imports</name>
  <files>backend/app/processing/tiles/router.py, backend/app/processing/export/router.py, backend/app/processing/ingest/service.py</files>
  <read_first>
    - backend/app/processing/tiles/router.py (entire file — note all SQL InstrumentedAttribute uses of Dataset, DatasetGrant, Record)
    - backend/app/processing/export/router.py (entire file — should be cleanest migration)
    - backend/app/processing/ingest/service.py (top of file — only lines 20, 22, 23 are top-level imports; lines 320, 368, 405 are deferred and belong to Plan 03)
    - backend/app/core/processing_port.py (after Task 0 — confirm Port helper methods)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Caller Migration Inventory — `tiles/router.py`, `export/router.py`, `ingest/service.py` subsections)
  </read_first>
  <action>
**File 1: `backend/app/processing/tiles/router.py`**

a) Remove:
```python
from app.modules.catalog.authorization import check_dataset_access, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant
```

If the file also imports `Record` from catalog (re-grep — RESEARCH.md notes that `tiles/router.py` may use `Record` in `apply_visibility_filter` calls), remove that too.

b) Add:
```python
from typing import TYPE_CHECKING

from app.core.processing_port import Dataset, DatasetGrant
from app.platform.extensions import get_processing_port

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```

If `Record` was imported, add `Record` to the alias list.

c) Add `port: "ProcessingPort" = Depends(get_processing_port)` to every route function in the file.

d) Replace call sites:
- `await check_dataset_access(...)` → `await port.check_dataset_access(...)`
- `await get_user_roles(...)` → `await port.get_user_roles(...)`
- `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` → 
  ```python
  Record_orm = port.get_record_orm_class()
  DatasetGrant_orm = port.get_grant_orm_class()
  filtered_stmt = port.apply_visibility_filter(stmt, user, user_roles, Record_orm, DatasetGrant_orm)
  ```
- Any `select(Dataset).where(Dataset.id == ...)` SQL needs evaluation: if the file does its own dataset SQL (rather than calling `port.get_dataset(...)`), check whether to (a) replace with `port.get_dataset` (preferred), or (b) use `port.get_record_orm_class()` to obtain the ORM and keep the SQL. **Default**: prefer `port.get_dataset` (or `port.get_dataset_with_attributes`) when the SQL is essentially a simple lookup. For exotic queries (joins to other tables), fetch the ORM class via `port.get_record_orm_class()` / `port.get_grant_orm_class()`.

e) Verify: `cd backend && uv run ruff check app/processing/tiles/router.py` clean. `grep -n "from app.modules.catalog" backend/app/processing/tiles/router.py` returns exit 1.

**File 2: `backend/app/processing/export/router.py`**

a) Remove:
```python
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.service import get_dataset
```

b) Add:
```python
from typing import TYPE_CHECKING

from app.platform.extensions import get_processing_port

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort
```

c) Add `port: "ProcessingPort" = Depends(get_processing_port)` to every route function.

d) Rewrite calls:
- `await check_dataset_access(...)` → `await port.check_dataset_access(...)`
- `await get_dataset(...)` → `await port.get_dataset(...)`

e) Verify: ruff clean and grep returns exit 1.

**File 3: `backend/app/processing/ingest/service.py`**

ONLY the top-level imports are in scope for Plan 02. Lines 320, 368, 405 are deferred imports (Plan 03's scope).

a) Remove (these are at lines 20, 22, 23 — re-grep at plan time to confirm exact line numbers):
```python
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import create_dataset
```

b) Add:
```python
from app.core.processing_port import Dataset
from app.platform.extensions import get_processing_port
```

c) Identify the entry-point function bodies (the ones called by ingest workers / routes that today call `get_user_roles`, `create_dataset` from the removed top-level imports). Add at the top of each such function body:
```python
port = get_processing_port()
```

(Worker functions don't go through FastAPI dependency injection per D-14.)

d) Rewrite calls in the top-level scope:
- `await get_user_roles(...)` → `await port.get_user_roles(...)`
- `await create_dataset(...)` → `await port.create_dataset(...)`

For any `IngestionResult.model_validate(...)` or `IngestionResult(...)` direct construction: replace with `port.create_ingestion_result(**kwargs)` (the new Port helper). This avoids needing a direct import of `IngestionResult`.

For any `select(Dataset).where(...)` SQL InstrumentedAttribute use, choose `port.get_dataset(...)` if the query is a simple lookup, or use `port.get_record_orm_class()` for exotic queries.

e) **CRITICAL**: only modify lines 20, 22, 23 and their call sites. Do NOT touch lines 320, 368, 405 (those are Plan 03's scope). The grep `grep -n "from app.modules.catalog" backend/app/processing/ingest/service.py` after this task should return SOME hits (the deferred ones), zero in the top of file.

f) Verify: `cd backend && uv run ruff check app/processing/ingest/service.py` clean. Top-of-file imports clean: `head -30 backend/app/processing/ingest/service.py | grep -c "from app.modules.catalog"` returns 0.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/tiles/router.py app/processing/export/router.py app/processing/ingest/service.py && head -30 backend/app/processing/tiles/router.py backend/app/processing/export/router.py backend/app/processing/ingest/service.py | grep -c "^from app.modules.catalog"</automated>
  </verify>
  <acceptance_criteria>
    - Top-of-file imports for `tiles/router.py` clean: `head -30 backend/app/processing/tiles/router.py | grep -c "from app.modules.catalog"` returns 0.
    - Top-of-file imports for `export/router.py` clean: `head -30 backend/app/processing/export/router.py | grep -c "from app.modules.catalog"` returns 0.
    - Top-of-file imports for `ingest/service.py` clean: `head -30 backend/app/processing/ingest/service.py | grep -c "from app.modules.catalog"` returns 0.
    - `Depends(get_processing_port)` present in tiles/router.py: `grep -c "Depends(get_processing_port)" backend/app/processing/tiles/router.py` returns ≥ 1.
    - `Depends(get_processing_port)` present in export/router.py: `grep -c "Depends(get_processing_port)" backend/app/processing/export/router.py` returns ≥ 1.
    - `port = get_processing_port()` present in ingest/service.py at least once: `grep -c "port = get_processing_port()" backend/app/processing/ingest/service.py` returns ≥ 1.
    - `port.check_dataset_access` calls present in tiles/router.py: `grep -c "port.check_dataset_access" backend/app/processing/tiles/router.py` returns ≥ 1.
    - `port.check_dataset_access`, `port.get_dataset` calls present in export/router.py: `grep -c "port\." backend/app/processing/export/router.py` returns ≥ 2.
    - `port.create_dataset`, `port.get_user_roles` calls present in ingest/service.py: `grep -c "port\." backend/app/processing/ingest/service.py` returns ≥ 2.
    - ruff clean for all three files.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
  </acceptance_criteria>
  <done>
    Top-level catalog imports removed from `tiles/router.py`, `export/router.py`, and `ingest/service.py` (lines 20-23 only — deferred imports at 320/368/405 deferred to Plan 03). HTTP routes use `Depends(get_processing_port)`; worker entry-point functions call `get_processing_port()` directly. All call sites route through Port. Full suite green.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Refactor-only — imports relocate; behavior unchanged via DefaultProcessingPort delegation |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-225-02 | (n/a) | Phase 225 surface | accept | Refactor-only — no new attack surface introduced. Imports relocate; calls go through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. No endpoint surface change, no auth/authz semantics change, no data flow change. Threats inherited from existing catalog services; Phase 225 does not change their authorization, validation, or trust boundaries. |

**Block:** false. Refactor only.
</threat_model>

<verification>
- `head -30 backend/app/processing/ai/service.py backend/app/processing/ai/router.py backend/app/processing/ai/chat_service.py backend/app/processing/ai/metadata_service.py backend/app/processing/tiles/router.py backend/app/processing/export/router.py backend/app/processing/embeddings/backfill.py backend/app/processing/ingest/service.py | grep -c "^from app.modules.catalog"` returns 0 (zero top-level catalog imports across the 8 files)
- `cd backend && uv run pytest -q` returns `2036 passed`
- `cd backend && uv run ruff check app/processing/` clean
- `cd backend && uv run alembic check` no new operations
- (Plan 03 sweeps deferred imports next; the architecture-guard test lands in Plan 04.)
</verification>

<success_criteria>
- 8 module-level top-of-file `from app.modules.catalog` imports removed from the 8 files listed above
- Service-layer functions in `processing/ai/{service,chat_service,metadata_service}.py` have `port: ProcessingPort` keyword-only parameter (D-15 / SC#5 enabling FakeProcessingPort seam test in Plan 04)
- HTTP routes use `Depends(get_processing_port)` (D-14 HTTP shape)
- Worker entry-point functions call `get_processing_port()` directly (D-14 worker shape)
- InstrumentedAttribute SQL replacements complete: `port.get_datasets_meta_by_ids`, `port.get_catalog_vocabulary`, `port.get_attribute_metadata`, `port.get_records_without_embeddings`, `port.get_record_keyword_count`, `port.get_related_keywords` (Pitfall 3 / Pitfall 12)
- Full backend test suite green at 2036/2036 baseline
- ruff clean
- AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data ONLY via Port (PROCESS-03)
</success_criteria>

<output>
After completion, create `.planning/phases/225-processing-port-protocol-cycle-inversion/225-02-SUMMARY.md` with:
- 8 files migrated, line-count delta per file
- Total `from app.modules.catalog` lines removed (target: 20+ lines from these 8 files)
- Confirmation that 2036/2036 baseline holds
- Two helper Port methods added in Task 0 (`get_record_orm_class`, `get_grant_orm_class`, `get_dataset_with_attributes`)
- Notes on any non-obvious migration choices (e.g., if `metadata_service._get_related_keywords_from_embeddings` retained custom embedding logic and only routed catalog SQL through Port)
- Status of `tasks_raster.py:143` `# noqa: F401` — defer to Plan 03 (deferred-import sweep) for resolution
- Reminder for Plan 03: 12 deferred-import sites still need migration; `head -30 ...` of these 8 files shows clean top-of-file but `grep` over the whole files still has matches (deferred imports)
</output>
</content>
</invoke>