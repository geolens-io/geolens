---
phase: 225
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/core/processing_port.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/__init__.py
autonomous: true
requirements:
  - PROCESS-01
  - PROCESS-05
threat_model:
  block: false
  rationale: "Refactor-only — no new attack surface introduced. The new Protocol is a typing construct + thin deferred-import forwarder; default delegates to existing catalog functions through the Phase 224 façade. No new endpoints, no new auth/authz semantics, no new data flows. Threats inherited from existing catalog services; Phase 225 does not change their authorization, validation, or trust boundaries."

must_haves:
  truths:
    - "ProcessingPort Protocol importable from app.core.processing_port"
    - "DefaultProcessingPort instantiable and structurally satisfies ProcessingPort"
    - "get_processing_port() returns DefaultProcessingPort() when no overlay registered"
    - "Companion Protocols (DatasetProtocol, RecordProtocol, MapProtocol, DatasetGrantProtocol, KeywordProtocol, AttributeProtocol, DatasetVersionProtocol) importable"
    - "Existing concrete catalog ORM classes structurally satisfy the new Protocols (no inheritance, no isinstance checks fail)"
    - "Full backend test suite remains green (2036/2036 baseline) — pure additive change, no behavior delta"
    - "Implements CONTEXT.md decisions: D-01 (single comprehensive ProcessingPort mirroring IdentityProtocol), D-02 (companion structural Protocols Dataset/Record/Map/DatasetGrant + DatasetVersion/Keyword/Attribute), D-03 (@runtime_checkable on every Protocol), D-04 (type aliases Dataset=DatasetProtocol etc.), D-05 (no is_* derived properties), D-06 (read-side method surface), D-07 (write-side method surface), D-08 (build_gdal_source on Port), D-09 (DefaultProcessingPort delegates via deferred imports — no new domain logic), D-10 (Protocol surface in core/processing_port.py), D-11 (Default impl in platform/extensions/defaults.py), D-12 (single-slot get_processing_port accessor — not list-shaped), D-13 (no nested ProcessingPortExtension factory), D-29 (no Alembic migration — additive only), D-30 (acceptance gate = 2036/2036 + ruff + arch-guard + alembic), D-31 (no frontend involvement), D-32 (Phase 226 sequencing — does NOT touch llm_loop.py or service.py provider dispatch)"
  artifacts:
    - path: "backend/app/core/processing_port.py"
      provides: "ProcessingPort Protocol + companion structural Protocols + type aliases (Dataset, Record, Map, DatasetGrant) + IngestionResult re-export"
      min_lines: 200
      contains: "class ProcessingPort(Protocol)"
    - path: "backend/app/platform/extensions/defaults.py"
      provides: "DefaultProcessingPort class with deferred-import forwarders"
      contains: "class DefaultProcessingPort"
    - path: "backend/app/platform/extensions/__init__.py"
      provides: "get_processing_port() single-slot accessor"
      contains: "def get_processing_port"
  key_links:
    - from: "backend/app/platform/extensions/__init__.py"
      to: "DefaultProcessingPort"
      via: "from app.platform.extensions.defaults import DefaultProcessingPort"
      pattern: "DefaultProcessingPort"
    - from: "backend/app/platform/extensions/__init__.py"
      to: "ProcessingPort (TYPE_CHECKING)"
      via: "if TYPE_CHECKING: from app.core.processing_port import ProcessingPort"
      pattern: "from app.core.processing_port import ProcessingPort"
    - from: "backend/app/platform/extensions/defaults.py"
      to: "app.modules.catalog.datasets.domain.service (façade)"
      via: "deferred imports inside method bodies"
      pattern: "from app.modules.catalog.datasets.domain.service import"
---

<objective>
Introduce the `ProcessingPort` Protocol surface (`backend/app/core/processing_port.py`) plus its community-edition default implementation (`DefaultProcessingPort` in `backend/app/platform/extensions/defaults.py`) and the single-slot typed accessor (`get_processing_port()` in `backend/app/platform/extensions/__init__.py`).

This plan is **purely additive** — no caller migrates yet. Behavior is byte-for-byte identical to the pre-Phase-225 baseline because nothing wires in to the new symbols. The full backend test suite (2036/2036) must remain green at the end of this plan.

Purpose: Lay the inversion seam for Phase 225. Plans 02 and 03 migrate the 8 processing files against this scaffold. Plan 04 adds the architecture-guard test.

Output:
- `core/processing_port.py` (NEW) — Protocol + 7 companion structural Protocols + 4 type aliases + `IngestionResult` re-export (per OQ-1) + `DatasetVersionProtocol` (per OQ-2)
- `platform/extensions/defaults.py` (MODIFIED, append) — `DefaultProcessingPort` class with deferred-import forwarders
- `platform/extensions/__init__.py` (MODIFIED, append) — `get_processing_port()` accessor + import additions
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-CONTEXT.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md
@backend/app/core/identity.py
@backend/app/platform/extensions/defaults.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/protocols.py
@backend/app/modules/catalog/authorization.py
@backend/app/modules/catalog/datasets/domain/models.py
@backend/app/modules/catalog/datasets/domain/utils.py
@backend/app/modules/catalog/datasets/domain/column_stats.py
@backend/app/modules/catalog/datasets/domain/schemas.py
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/search/service.py
@backend/app/modules/catalog/sources/preview.py
@backend/app/modules/catalog/collections/models.py

<interfaces>
<!-- Existing patterns the executor mirrors verbatim -->

From backend/app/core/identity.py (the canonical pattern):
```python
"""Cross-domain identity contract.

Defines structural Protocols that downstream code uses to type a request's
authenticated user without importing the concrete SQLAlchemy ORM. ...
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class RoleProtocol(Protocol):
    """Slim role contract — ``name`` is the only attribute cross-domain code reads."""
    name: str


@runtime_checkable
class IdentityProtocol(Protocol):
    """Comprehensive identity surface read by ~42 cross-domain call sites."""
    id: uuid.UUID
    username: str
    email: str | None
    is_active: bool
    roles: Sequence[RoleProtocol]
    created_at: datetime


# Shorter alias for caller annotations (Phase 214 D-05).
Identity = IdentityProtocol


@runtime_checkable
class IdentityExtension(Protocol):
    """Enterprise overlay registration contract for alternate identity backends."""
    async def resolve_identity_from_token(
        self, token: str, request: Request, db: AsyncSession
    ) -> Identity | None: ...
```

From backend/app/platform/extensions/defaults.py (DefaultAuditSink — deferred-import forwarder pattern):
```python
class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action()."""

    async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
        # Deferred import: log_action lives in app.modules.audit.service.
        # extensions/ is platform-level and should not pull modules-level
        # imports at module load (Phase 214 deferred-import discipline).
        from app.modules.audit.service import log_action

        await log_action(
            session,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
        )
```

From backend/app/platform/extensions/__init__.py:115-129 (get_identity_extension — single-slot accessor):
```python
def get_identity_extension() -> "IdentityExtension":
    """Return the registered IdentityExtension or the community default."""
    ext = _extensions.get("identity")
    if ext is None:
        return DefaultIdentityExtension()
    return ext  # type: ignore[return-value]
```

From RESEARCH.md §Method Surface — concrete signatures DefaultProcessingPort must delegate to:

| Method | Source | Sync/Async |
|--------|--------|-----------|
| `get_dataset(session, dataset_id)` | `catalog/datasets/domain/service.py` (façade) → `service_query.py:39` | async |
| `get_record(session, record_id)` | NEW thin function in catalog OR direct select(Record) inside DefaultProcessingPort | async |
| `search_datasets(session, user, user_roles, filters)` | `catalog/search/service.py:829` | async |
| `apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls=None)` | `catalog/authorization.py:34` | **sync** |
| `check_dataset_access(session, dataset, dataset_id, user, *, user_roles=None)` | `catalog/authorization.py:134` | async |
| `get_user_roles(session, user)` | `catalog/authorization.py:99` | async |
| `get_column_stats(session, table_name, column_name, *, class_count=5, allowed_tables=None)` | `catalog/datasets/domain/column_stats.py:62` | async |
| `get_distinct_values(session, table_name, column_name, limit=100, *, allowed_tables=None)` | `catalog/datasets/domain/column_stats.py:31` | async |
| `extract_bbox(dataset)` | `catalog/datasets/domain/utils.py:8` | **sync** |
| `create_dataset(session, table_name, title, created_by, *, summary, visibility, ingestion)` | `catalog/datasets/domain/service.py` (façade) → `service_create.py:128` | async |
| `create_map(session, name, description, created_by, notes=None)` | `catalog/maps/service.py:150` | async |
| `update_map(session, map_id, **kwargs)` | `catalog/maps/service.py:405` | async |
| `build_gdal_source(service_type, base_url, layer_name, ...)` | `catalog/sources/preview.py:14` | **sync** |
| `get_dataset_version(session, dataset_id)` | NEW thin function (per OQ-2) — fetches latest `DatasetVersion` for a dataset | async |
| `get_records_without_embeddings(session, *, force=False)` | NEW Port method (per OQ-3) — encapsulates `select(Record).outerjoin(RecordEmbedding)` query from `embeddings/backfill.py` | async |
| `get_datasets_meta_by_ids(session, ids)` | NEW Port method (per OQ-3 / Pitfall 12) — encapsulates `select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(Dataset.id.in_(...))` from `ai/router.py:139` | async |
| `get_catalog_vocabulary(session)` | NEW Port method (per OQ-3) — encapsulates `select(RecordKeyword.keyword).distinct()` from `metadata_service.py` | async |
| `get_related_keywords(session, dataset_id, limit)` | NEW Port method (per OQ-3) — encapsulates `select(RecordKeyword)` related-keywords query from `metadata_service.py` | async |
| `get_record_keyword_count(session, record_id)` | NEW Port method (per OQ-3) — encapsulates `select(func.count()).where(RecordKeyword.record_id == record_id)` from `ingest/metadata.py:466+` | async |
| `get_attribute_metadata(session, dataset_id)` | NEW Port method (per OQ-3) — encapsulates `select(AttributeMetadata).where(AttributeMetadata.dataset_id == ...)` from `ingest/metadata.py:1076+` | async |

Companion Protocol field shape (from RESEARCH.md §Companion Protocols Field Inventory):

DatasetProtocol fields:
- `id: uuid.UUID`
- `record_id: uuid.UUID`
- `table_name: str`
- `geometry_type: str | None`
- `feature_count: int | None`
- `srid: int | None`
- `original_srid: int | None`
- `source_format: str | None`
- `source_filename: str | None`
- `source_url: str | None`
- `column_info: list | None`
- `sample_values: dict | None`
- `quality_detail: dict | None`
- `quality_statement: str | None`
- `current_version: int`
- `is_3d: bool | None`
- `record: RecordProtocol`
- `attributes: Sequence[AttributeProtocol]`

RecordProtocol fields:
- `id: uuid.UUID`
- `title: str`
- `summary: str | None`
- `keywords: Sequence[KeywordProtocol]`
- `spatial_extent: Any` (geoalchemy2 type — typed Any to avoid import in core/)
- `lineage_summary: str | None`
- `source_organization: str | None`
- `access_constraints: str | None`
- `temporal_start: date | None`
- `temporal_end: date | None`
- `record_type: str`
- `created_at: datetime`

KeywordProtocol fields:
- `keyword: str`

AttributeProtocol fields:
- `is_current: bool`
- `field_name: str`
- `description: str | None`
- `data_type: str | None`

MapProtocol fields:
- `id: uuid.UUID`
- `created_by: uuid.UUID | None`
- `basemap_style: str`
- `name: str`

DatasetGrantProtocol fields:
- `id: uuid.UUID`
- `dataset_id: uuid.UUID`
- `role_id: uuid.UUID`

DatasetVersionProtocol fields (per OQ-2):
- `id: uuid.UUID`

OQ-1 verification: `backend/app/modules/catalog/datasets/domain/schemas.py` imports only `uuid`, `datetime` (stdlib), `pydantic`, `app.core.text` — NO `app.modules.*` edges. Safe to re-export `IngestionResult` directly from `core/processing_port.py` (not just TYPE_CHECKING).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create core/processing_port.py with full Protocol surface, companion Protocols, type aliases, and IngestionResult re-export</name>
  <files>backend/app/core/processing_port.py</files>
  <read_first>
    - backend/app/core/identity.py (the canonical pattern — module docstring, Protocol decoration, alias style; mirror verbatim)
    - backend/app/platform/extensions/protocols.py (TYPE_CHECKING forward-ref pattern at lines 18-19)
    - backend/app/modules/catalog/datasets/domain/models.py (read attribute set for DatasetProtocol/RecordProtocol — match field names + types from RESEARCH.md §Companion Protocols Field Inventory)
    - backend/app/modules/catalog/datasets/domain/schemas.py (line 1-7 imports — confirm zero app.modules.* edges before re-exporting IngestionResult per OQ-1)
    - backend/app/modules/catalog/maps/models.py (Map ORM attribute inventory)
    - backend/app/modules/catalog/datasets/domain/column_stats.py (get_column_stats / get_distinct_values signatures)
    - backend/app/modules/catalog/authorization.py (apply_visibility_filter sync signature)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§ProcessingPort Method Surface — full signature table, §Companion Protocols Field Inventory)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md (§1 — verbatim docstring template + Protocol shape examples)
  </read_first>
  <action>
Create `backend/app/core/processing_port.py` with the following exact structure (mirror `backend/app/core/identity.py` verbatim):

1. **Module docstring** (lines 1-22 style — credit Phases 214/222/225, point to Phase 226):
```
"""Cross-domain catalog access contract.

Defines structural Protocols that processing/* uses to read and write
catalog data without importing the concrete SQLAlchemy ORM from
app.modules.catalog.*. Concrete ORM classes (Dataset, Record, Map,
DatasetGrant, DatasetVersion, RecordKeyword, AttributeMetadata) satisfy
the Protocols structurally (PEP 544); no inheritance is required.

Uses only stdlib types (plus SQLAlchemy's AsyncSession for async method
signatures and the Pydantic IngestionResult schema which has zero
app.modules.* edges) to avoid the core -> modules.catalog import edge
that Phase 225 (PROCESS-01..05) is closing. AsyncSession and Pydantic
are infrastructure types that do NOT live under app.modules.*.

An enterprise overlay (e.g., geolens-enterprise) may replace the default
implementation by registering a tier-aware or quota-enforcing port under
the 'processing_port' key via the geolens.extensions entry-point group;
get_processing_port() returns it on subsequent requests. Phase 226
(AIProviderExtension) is the next consumer of this boundary.
"""
```

2. **Imports** (line 23+):
```python
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, Sequence, runtime_checkable

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

# Direct re-export of IngestionResult (OQ-1 — schemas.py has zero app.modules.* edges,
# so this import is safe under Phase 214 IDENT-01).
from app.modules.catalog.datasets.domain.schemas import IngestionResult

if TYPE_CHECKING:
    from app.modules.catalog.search.service import SearchFilters

from app.core.identity import Identity
```

Wait — re-importing IngestionResult violates Phase 214 IDENT-01 because `schemas.py` lives under `app.modules.catalog.*`. Even though `schemas.py` has no `app.modules.*` edges itself, the path `app.modules.catalog.datasets.domain.schemas` is still under `app.modules.*`. **Re-evaluate:** keep `IngestionResult` ONLY in the TYPE_CHECKING block. Callers that construct `IngestionResult(...)` import it from `app.core.processing_port` via the TYPE_CHECKING block at the top of their files (which works for type hints) AND keep their own deferred runtime import OR — simpler — re-export `IngestionResult` from `core/processing_port.py` via a deferred import inside a helper function. **Cleanest resolution:** add `IngestionResult` to TYPE_CHECKING only. Callers that need to construct it use `from app.core.processing_port import IngestionResult` under their own `if TYPE_CHECKING:` block. For runtime construction, callers do a deferred import: `from app.core.processing_port import IngestionResult` runtime-imports it because the IngestionResult symbol is bound at TYPE_CHECKING block evaluation only.

Actually, the cleanest pattern that mirrors how `Identity = IdentityProtocol` is exported as a runtime-resolvable alias is: do NOT use TYPE_CHECKING for IngestionResult re-export. Instead, since `schemas.py` is pure pydantic + stdlib + `app.core.text`, the import edge `app.core.processing_port → app.modules.catalog.datasets.domain.schemas` is a one-way "core reads catalog schema for re-export" edge. **This edge is forbidden by Phase 214 IDENT-01 architecture-guard.**

Resolution: Do NOT re-export IngestionResult from `core/processing_port.py`. Instead:
- Add `IngestionResult` to the `TYPE_CHECKING` block (forward-reference only)
- The `create_dataset` Port method signature uses `ingestion: "IngestionResult | None"` as a forward-referenced string annotation
- Callers that construct `IngestionResult(...)` keep a direct import `from app.modules.catalog.datasets.domain.schemas import IngestionResult` — but this trips the Phase 225 architecture guard
- **Plan 03 will resolve this by**: keeping a deferred local import of `IngestionResult` inside the function body in `tasks_common.py:697` and `ingest/service.py:368`. The architecture guard is regex `^\s*(from|import)\s+app\.modules\.catalog` and DOES catch deferred imports too.
- **Final resolution (per RESEARCH.md OQ-1 recommendation, re-evaluated):** The `from app.modules.catalog...` edge in `core/processing_port.py` IS a violation of Phase 214 IDENT-01. So `IngestionResult` MUST stay TYPE_CHECKING-only. Plans 02/03 must NOT use `from app.core.processing_port import IngestionResult` for runtime construction.
- **What Plans 02/03 MUST do for IngestionResult**: Add `get_ingestion_result_type()` lazy factory method on the Port that returns the class? No — that's overengineered. **Cleanest resolution**: Add a runtime indirection on the Port: `port.create_ingestion_result(**kwargs) -> IngestionResult` that constructs the object inside `DefaultProcessingPort` (where `app.modules.catalog` imports are allowed). This way callers never need to import `IngestionResult` directly; they call `port.create_ingestion_result(success=..., ...)` and pass the returned object to `port.create_dataset(..., ingestion=...)`.

**Final design decision for this task:**
- `IngestionResult` stays in `TYPE_CHECKING` block ONLY (no runtime re-export from `core/`)
- Add `create_ingestion_result(**kwargs) -> "IngestionResult"` method to `ProcessingPort` Protocol
- `DefaultProcessingPort.create_ingestion_result` does a deferred import and constructs the object
- Callers in Plans 02/03 construct IngestionResult via `port.create_ingestion_result(...)` instead of direct construction

3. **Companion structural Protocols** (mirror `IdentityProtocol`'s `RoleProtocol` shape — slim, only fields the cross-domain code reads):

```python
@runtime_checkable
class KeywordProtocol(Protocol):
    """Slim keyword contract — only ``keyword`` is read cross-domain."""
    keyword: str


@runtime_checkable
class AttributeProtocol(Protocol):
    """Slim attribute metadata contract — fields read by metadata_service."""
    is_current: bool
    field_name: str
    description: str | None
    data_type: str | None


@runtime_checkable
class RecordProtocol(Protocol):
    """Catalog Record surface read by processing/*."""
    id: uuid.UUID
    title: str
    summary: str | None
    keywords: Sequence[KeywordProtocol]
    spatial_extent: Any  # geoalchemy2 type — Any keeps core/ free of geoalchemy2 import
    lineage_summary: str | None
    source_organization: str | None
    access_constraints: str | None
    temporal_start: date | None
    temporal_end: date | None
    record_type: str
    created_at: datetime


@runtime_checkable
class DatasetProtocol(Protocol):
    """Catalog Dataset surface read by processing/*."""
    id: uuid.UUID
    record_id: uuid.UUID
    table_name: str
    geometry_type: str | None
    feature_count: int | None
    srid: int | None
    original_srid: int | None
    source_format: str | None
    source_filename: str | None
    source_url: str | None
    column_info: list | None
    sample_values: dict | None
    quality_detail: dict | None
    quality_statement: str | None
    current_version: int
    is_3d: bool | None
    record: RecordProtocol
    attributes: Sequence[AttributeProtocol]


@runtime_checkable
class MapProtocol(Protocol):
    """Catalog Map surface read by processing/ai."""
    id: uuid.UUID
    created_by: uuid.UUID | None
    basemap_style: str
    name: str


@runtime_checkable
class DatasetGrantProtocol(Protocol):
    """Catalog DatasetGrant surface — used for type annotations only.
    InstrumentedAttribute SQL uses pass the concrete ORM class as `grant_cls: Any`.
    """
    id: uuid.UUID
    dataset_id: uuid.UUID
    role_id: uuid.UUID


@runtime_checkable
class DatasetVersionProtocol(Protocol):
    """Catalog DatasetVersion surface — only ``id`` is read by reupload finalize path (OQ-2)."""
    id: uuid.UUID
```

4. **Type aliases** (mirror `Identity = IdentityProtocol`):
```python
# Shorter aliases for caller annotations (Phase 225 D-04, mirrors Phase 214 D-05).
Dataset = DatasetProtocol
Record = RecordProtocol
Map = MapProtocol
DatasetGrant = DatasetGrantProtocol
DatasetVersion = DatasetVersionProtocol
Keyword = KeywordProtocol
Attribute = AttributeProtocol
```

5. **Comprehensive `ProcessingPort` Protocol** with all 20 methods from the interfaces table above. Use exact signatures. Methods that are sync use plain `def`; methods that are async use `async def ... -> ...: ...`. Examples:
```python
@runtime_checkable
class ProcessingPort(Protocol):
    """Comprehensive catalog accessor contract used by backend/app/processing/*.

    Mirrors Phase 214 IdentityProtocol's "single comprehensive Protocol" shape (D-01).
    Every cross-domain catalog accessor processing/* needs today is on this surface.
    Companion structural Protocols (DatasetProtocol, etc.) above type the ORM-shaped
    return values without leaking SQLAlchemy ORM into core/.

    Read methods (D-06 + OQ-3 additions):
    - get_dataset, get_record, search_datasets, apply_visibility_filter,
      check_dataset_access, get_user_roles, get_column_stats, get_distinct_values,
      extract_bbox, get_records_without_embeddings, get_datasets_meta_by_ids,
      get_catalog_vocabulary, get_related_keywords, get_record_keyword_count,
      get_attribute_metadata, get_dataset_version

    Write methods (D-07):
    - create_dataset, create_map, update_map, create_ingestion_result

    Source preview helper (D-08):
    - build_gdal_source
    """

    # Read-side
    async def get_dataset(self, session: AsyncSession, dataset_id: uuid.UUID) -> DatasetProtocol | None: ...
    async def get_record(self, session: AsyncSession, record_id: uuid.UUID) -> RecordProtocol | None: ...
    async def search_datasets(
        self,
        session: AsyncSession,
        user: Identity | None,
        user_roles: set[str],
        filters: "SearchFilters",
    ) -> tuple[list[DatasetProtocol], int]: ...
    def apply_visibility_filter(
        self,
        stmt: Select,
        user: Identity | None,
        user_roles: set[str],
        record_cls: Any,
        grant_cls: Any | None = None,
    ) -> Select: ...
    async def check_dataset_access(
        self,
        session: AsyncSession,
        dataset: Any,
        dataset_id: uuid.UUID,
        user: Identity,
        *,
        user_roles: set[str] | None = None,
    ) -> set[str]: ...
    async def get_user_roles(self, session: AsyncSession, user: Identity) -> set[str]: ...
    async def get_column_stats(
        self,
        session: AsyncSession,
        table_name: str,
        column_name: str,
        *,
        class_count: int = 5,
        allowed_tables: set[str] | None = None,
    ) -> dict: ...
    async def get_distinct_values(
        self,
        session: AsyncSession,
        table_name: str,
        column_name: str,
        limit: int = 100,
        *,
        allowed_tables: set[str] | None = None,
    ) -> list: ...
    def extract_bbox(self, dataset: DatasetProtocol) -> list[float] | None: ...

    # OQ-3 InstrumentedAttribute encapsulators (Pitfall 3 / Pitfall 12 resolution)
    async def get_records_without_embeddings(
        self, session: AsyncSession, *, force: bool = False
    ) -> list[RecordProtocol]: ...
    async def get_datasets_meta_by_ids(
        self, session: AsyncSession, ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, str, str | None]]: ...
    async def get_catalog_vocabulary(self, session: AsyncSession) -> list[str]: ...
    async def get_related_keywords(
        self, session: AsyncSession, dataset_id: uuid.UUID, limit: int = 10
    ) -> list[str]: ...
    async def get_record_keyword_count(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> int: ...
    async def get_attribute_metadata(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> list[AttributeProtocol]: ...
    async def get_dataset_version(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetVersionProtocol | None: ...

    # Write-side
    async def create_dataset(
        self,
        session: AsyncSession,
        table_name: str,
        title: str,
        created_by: uuid.UUID,
        *,
        summary: str | None = None,
        visibility: str = "private",
        ingestion: "IngestionResult | None" = None,
    ) -> DatasetProtocol: ...
    async def create_map(
        self,
        session: AsyncSession,
        name: str,
        description: str | None,
        created_by: uuid.UUID,
        notes: str | None = None,
    ) -> MapProtocol: ...
    async def update_map(
        self,
        session: AsyncSession,
        map_id: uuid.UUID,
        **kwargs: Any,
    ) -> tuple[MapProtocol, list[Any], str | None, str | None]: ...
    def create_ingestion_result(self, **kwargs: Any) -> "IngestionResult": ...

    # Source preview
    def build_gdal_source(
        self,
        service_type: str,
        base_url: str,
        layer_name: str,
        layer_id: int | str | None = None,
        token: str | None = None,
        order_field: str | None = None,
        result_limit: int | None = None,
    ) -> tuple[str, str]: ...
```

Save the file. Total length should be ~250-300 lines.

**Important constraints (from CONTEXT.md / RESEARCH.md):**
- DO NOT add a `ProcessingPortExtension` nested Protocol (D-13 — overlays register the Port directly).
- DO NOT use `import-linter` or any architecture-DSL dependency (D-18).
- Companion Protocols are slim — only fields actually read cross-domain (per D-02 / RESEARCH.md inventory).
- `apply_visibility_filter` and `extract_bbox` and `build_gdal_source` and `create_ingestion_result` are SYNC (plain `def`).
- All other methods are ASYNC.
- Use `@runtime_checkable` on every Protocol (D-03).
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.core.processing_port import ProcessingPort, DatasetProtocol, RecordProtocol, MapProtocol, DatasetGrantProtocol, DatasetVersionProtocol, KeywordProtocol, AttributeProtocol, Dataset, Record, Map, DatasetGrant, DatasetVersion; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/app/core/processing_port.py` exists.
    - File contains line `class ProcessingPort(Protocol):` (verifiable: `grep -c "class ProcessingPort(Protocol):" backend/app/core/processing_port.py` returns 1).
    - File contains all 7 companion Protocols: `DatasetProtocol`, `RecordProtocol`, `MapProtocol`, `DatasetGrantProtocol`, `DatasetVersionProtocol`, `KeywordProtocol`, `AttributeProtocol` (verifiable: `grep -c "^class .*Protocol(Protocol):" backend/app/core/processing_port.py` returns 8).
    - File contains all 20 ProcessingPort methods including: `get_dataset`, `get_record`, `search_datasets`, `apply_visibility_filter`, `check_dataset_access`, `get_user_roles`, `get_column_stats`, `get_distinct_values`, `extract_bbox`, `get_records_without_embeddings`, `get_datasets_meta_by_ids`, `get_catalog_vocabulary`, `get_related_keywords`, `get_record_keyword_count`, `get_attribute_metadata`, `get_dataset_version`, `create_dataset`, `create_map`, `update_map`, `create_ingestion_result`, `build_gdal_source` (verifiable by 21 grep matches for `^    (async )?def `).
    - File contains type aliases `Dataset = DatasetProtocol`, `Record = RecordProtocol`, `Map = MapProtocol`, `DatasetGrant = DatasetGrantProtocol`, `DatasetVersion = DatasetVersionProtocol` (verifiable: `grep -E "^(Dataset|Record|Map|DatasetGrant|DatasetVersion) = " backend/app/core/processing_port.py | grep -c "= "` returns 5).
    - File uses `@runtime_checkable` on all Protocols (verifiable: `grep -c "^@runtime_checkable" backend/app/core/processing_port.py` returns 8).
    - File starts with `from __future__ import annotations` (verifiable: `grep -n "from __future__ import annotations" backend/app/core/processing_port.py` returns line ≤ 30).
    - File has TYPE_CHECKING block importing `SearchFilters` and `IngestionResult` (verifiable: `grep -A2 "if TYPE_CHECKING" backend/app/core/processing_port.py | grep -c "SearchFilters\|IngestionResult"` returns ≥ 1).
    - File does NOT contain any line `from app.modules.` outside the TYPE_CHECKING block (verifiable: `grep -n "^from app.modules" backend/app/core/processing_port.py` returns no output / exit code 1).
    - File does NOT contain a `ProcessingPortExtension` Protocol class (verifiable: `grep -c "class ProcessingPortExtension" backend/app/core/processing_port.py` returns 0).
    - Smoke import succeeds: `cd backend && uv run python -c "from app.core.processing_port import ProcessingPort, DatasetProtocol, Dataset"` exits 0 with no error.
    - `apply_visibility_filter`, `extract_bbox`, `build_gdal_source`, `create_ingestion_result` are sync (verifiable: `grep -c "^    def \(apply_visibility_filter\|extract_bbox\|build_gdal_source\|create_ingestion_result\)" backend/app/core/processing_port.py` returns 4).
    - Phase 214 architecture-guard test still passes: `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -x` exits 0.
  </acceptance_criteria>
  <done>
    `core/processing_port.py` exists with the full Protocol surface. Type aliases exported. All Protocols decorated with `@runtime_checkable`. Phase 214 IDENT-01 guard still passes (no `from app.modules.*` runtime import in core). Smoke import succeeds.
  </done>
</task>

<task type="auto">
  <name>Task 2: Append DefaultProcessingPort to platform/extensions/defaults.py with deferred-import forwarders</name>
  <files>backend/app/platform/extensions/defaults.py</files>
  <read_first>
    - backend/app/platform/extensions/defaults.py (current state — read entire file; append at end)
    - backend/app/platform/extensions/defaults.py:46-76 (DefaultAuditSink — the canonical deferred-import forwarder pattern; mirror exactly)
    - backend/app/platform/extensions/defaults.py:27-43 (DefaultIdentityExtension — secondary pattern reference)
    - backend/app/core/processing_port.py (read after Task 1 — confirm Port method signatures match)
    - backend/app/modules/catalog/datasets/domain/service.py (the Phase 224 façade — DefaultProcessingPort delegates here, NEVER to sub-modules)
    - backend/app/modules/catalog/authorization.py (apply_visibility_filter, check_dataset_access, get_user_roles — concrete signatures)
    - backend/app/modules/catalog/datasets/domain/column_stats.py (get_column_stats, get_distinct_values)
    - backend/app/modules/catalog/datasets/domain/utils.py (extract_bbox)
    - backend/app/modules/catalog/maps/service.py (create_map, update_map)
    - backend/app/modules/catalog/search/service.py (search_datasets)
    - backend/app/modules/catalog/sources/preview.py (build_gdal_source)
    - backend/app/modules/catalog/datasets/domain/schemas.py (IngestionResult constructor)
    - backend/app/modules/catalog/collections/models.py (DatasetVersion ORM)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md (§2 — DefaultProcessingPort template)
  </read_first>
  <action>
Append `DefaultProcessingPort` class to `backend/app/platform/extensions/defaults.py` at end of file. Mirror `DefaultAuditSink.emit()` deferred-import pattern verbatim.

```python
class DefaultProcessingPort:
    """Community-edition default: delegates every call to app.modules.catalog.*
    via deferred imports (Phase 225 D-09 / D-11 / PROCESS-01).

    Each method does a deferred import into app.modules.catalog.* inside the
    function body, keeping platform/extensions/ free of module-load-time
    modules.* edges (Phase 214 deferred-import discipline). Behavior is
    identical to the pre-Phase-225 baseline — the Port is the seam, not a
    re-implementation.

    create_dataset, get_dataset etc. delegate via the
    app.modules.catalog.datasets.domain.service FACADE (never the sub-modules
    directly — Phase 224 DECOUPLE-04).
    """

    # Read-side methods (D-06)

    async def get_dataset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.service import get_dataset
        return await get_dataset(session, dataset_id)

    async def get_record(self, session, record_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.modules.catalog.datasets.domain.models import Record

        stmt = select(Record).where(Record.id == record_id).options(joinedload(Record.keywords))
        result = await session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def search_datasets(self, session, user, user_roles, filters):  # type: ignore[no-untyped-def]
        from app.modules.catalog.search.service import search_datasets
        return await search_datasets(session, user, user_roles, filters)

    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import apply_visibility_filter
        return apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls)

    async def check_dataset_access(self, session, dataset, dataset_id, user, *, user_roles=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import check_dataset_access
        return await check_dataset_access(session, dataset, dataset_id, user, user_roles=user_roles)

    async def get_user_roles(self, session, user):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import get_user_roles
        return await get_user_roles(session, user)

    async def get_column_stats(self, session, table_name, column_name, *, class_count=5, allowed_tables=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_column_stats
        return await get_column_stats(
            session, table_name, column_name,
            class_count=class_count, allowed_tables=allowed_tables,
        )

    async def get_distinct_values(self, session, table_name, column_name, limit=100, *, allowed_tables=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_distinct_values
        return await get_distinct_values(
            session, table_name, column_name, limit, allowed_tables=allowed_tables,
        )

    def extract_bbox(self, dataset):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.utils import extract_bbox
        return extract_bbox(dataset)

    # OQ-3 InstrumentedAttribute encapsulators

    async def get_records_without_embeddings(self, session, *, force=False):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.modules.catalog.datasets.domain.models import Record
        from app.modules.catalog.datasets.domain.embeddings_models import RecordEmbedding

        stmt = (
            select(Record)
            .outerjoin(RecordEmbedding, Record.id == RecordEmbedding.record_id)
            .options(joinedload(Record.keywords))
            .order_by(Record.created_at)
        )
        if not force:
            stmt = stmt.where(RecordEmbedding.record_id.is_(None))
        result = await session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_datasets_meta_by_ids(self, session, ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from app.modules.catalog.datasets.domain.models import Dataset

        stmt = select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(
            Dataset.id.in_(ids)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def get_catalog_vocabulary(self, session):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from app.modules.catalog.datasets.domain.models import RecordKeyword

        stmt = select(RecordKeyword.keyword).distinct()
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_related_keywords(self, session, dataset_id, limit=10):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword

        # Get the record_id for this dataset, then keywords for related records.
        # If a more sophisticated related-keywords query exists in metadata_service.py,
        # mirror it verbatim during the Plan 02 migration; this default is the simple
        # fallback (keywords on the same record).
        stmt = (
            select(RecordKeyword.keyword)
            .join(Record, Record.id == RecordKeyword.record_id)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset_id)
            .distinct()
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_record_keyword_count(self, session, record_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import func, select
        from app.modules.catalog.datasets.domain.models import RecordKeyword

        stmt = select(func.count()).where(RecordKeyword.record_id == record_id)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_attribute_metadata(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        stmt = select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_dataset_version(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from app.modules.catalog.collections.models import DatasetVersion

        stmt = (
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # Write-side methods (D-07)

    async def create_dataset(self, session, table_name, title, created_by, *, summary=None, visibility="private", ingestion=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.service import create_dataset
        return await create_dataset(
            session,
            table_name=table_name,
            title=title,
            created_by=created_by,
            summary=summary,
            visibility=visibility,
            ingestion=ingestion,
        )

    async def create_map(self, session, name, description, created_by, notes=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.maps.service import create_map
        return await create_map(session, name, description, created_by, notes)

    async def update_map(self, session, map_id, **kwargs):  # type: ignore[no-untyped-def]
        from app.modules.catalog.maps.service import update_map
        return await update_map(session, map_id, **kwargs)

    def create_ingestion_result(self, **kwargs):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.schemas import IngestionResult
        return IngestionResult(**kwargs)

    # Source preview helper (D-08)

    def build_gdal_source(self, service_type, base_url, layer_name, layer_id=None, token=None, order_field=None, result_limit=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.sources.preview import build_gdal_source
        return build_gdal_source(
            service_type, base_url, layer_name,
            layer_id=layer_id, token=token,
            order_field=order_field, result_limit=result_limit,
        )
```

**IMPORTANT — Phase 224 façade discipline (Pitfall 1):**
- `create_dataset` delegates via `app.modules.catalog.datasets.domain.service` (the FACADE), NEVER `service_create.py`.
- `get_dataset` delegates via `app.modules.catalog.datasets.domain.service` (the FACADE), NEVER `service_query.py`.

**IMPORTANT — concrete signature verification:**
- Read each catalog service function before writing the delegate to confirm the parameter names + order match. If any signature differs from this template, adjust the delegate to match the live source — the Port method must accept exactly what the Port Protocol declares (Task 1) AND forward exactly what the catalog function expects.
- For `update_map`: pass through `**kwargs`. Verify the catalog `update_map` signature accepts the same kwargs the AI service uses (center_lng, center_lat, zoom, basemap_style, layers, etc.).
- For `get_records_without_embeddings`: re-grep `embeddings/backfill.py` to confirm the actual query shape (joinedload paths, RecordEmbedding model location). The Phase 03 migration MUST produce identical SQL.
- For `get_related_keywords`: this is the simplest mirror. The actual semantics in `metadata_service.py` may use embedding-based similarity. If so, Plan 02 needs to keep that logic in the caller (use port for catalog access only) OR the Port method needs to be richer. **For now, in this Default impl, ship the simple "keywords-on-same-record" fallback** — Plan 02 will refine if needed. Document as TODO if more complex query exists.

If during reading any catalog function signature doesn't match what's listed above, fix the DefaultProcessingPort method body BUT do NOT change `core/processing_port.py` Protocol signature unless the Port method declaration in Task 1 was wrong.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.platform.extensions.defaults import DefaultProcessingPort; from app.core.processing_port import ProcessingPort; assert isinstance(DefaultProcessingPort(), ProcessingPort), 'DefaultProcessingPort does not satisfy ProcessingPort Protocol'; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/app/platform/extensions/defaults.py` contains line `class DefaultProcessingPort:` (verifiable: `grep -c "^class DefaultProcessingPort:" backend/app/platform/extensions/defaults.py` returns 1).
    - DefaultProcessingPort defines all 20 methods (verifiable: `awk '/^class DefaultProcessingPort/,/^class [^D]/' backend/app/platform/extensions/defaults.py | grep -cE "^    (async )?def "` returns 21 — methods plus optional dunder).
    - All methods use deferred imports (no `app.modules.catalog` import at file top): `head -20 backend/app/platform/extensions/defaults.py | grep -c "from app.modules.catalog"` returns 0.
    - `create_dataset` delegate goes through the facade (verifiable: `grep -A2 "async def create_dataset" backend/app/platform/extensions/defaults.py | grep -c "from app.modules.catalog.datasets.domain.service import create_dataset"` returns 1; NOT `service_create.py`).
    - `get_dataset` delegate goes through the facade (verifiable: `grep -A2 "async def get_dataset" backend/app/platform/extensions/defaults.py | grep -c "from app.modules.catalog.datasets.domain.service import get_dataset"` returns 1; NOT `service_query.py`).
    - Phase 224 architecture guard still passes: `cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -x` exits 0.
    - Smoke check passes: `cd backend && uv run python -c "from app.platform.extensions.defaults import DefaultProcessingPort; from app.core.processing_port import ProcessingPort; assert isinstance(DefaultProcessingPort(), ProcessingPort), 'fail'; print('OK')"` exits 0.
    - Sync methods (no `async def`): `apply_visibility_filter`, `extract_bbox`, `build_gdal_source`, `create_ingestion_result`. Verify: `grep -E "^    def (apply_visibility_filter|extract_bbox|build_gdal_source|create_ingestion_result)\(" backend/app/platform/extensions/defaults.py | wc -l` returns 4.
  </acceptance_criteria>
  <done>
    `DefaultProcessingPort` appended to `defaults.py`. All 20 methods present, each using deferred imports inside method body. Phase 224 façade discipline observed. Phase 214 architecture-guard tests still pass.
  </done>
</task>

<task type="auto">
  <name>Task 3: Append get_processing_port() accessor to platform/extensions/__init__.py</name>
  <files>backend/app/platform/extensions/__init__.py</files>
  <read_first>
    - backend/app/platform/extensions/__init__.py (entire file — read first 200 lines for structure, full file if needed for placement)
    - backend/app/platform/extensions/__init__.py:115-129 (get_identity_extension — exact mirror)
    - backend/app/platform/extensions/__init__.py:15-32 (existing import block — append DefaultProcessingPort here)
    - backend/app/platform/extensions/defaults.py (after Task 2 — confirm DefaultProcessingPort exists)
    - backend/app/core/processing_port.py (after Task 1 — confirm ProcessingPort exists)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md (§3 — get_processing_port template)
  </read_first>
  <action>
Modify `backend/app/platform/extensions/__init__.py` to add three things:

**1. Add `DefaultProcessingPort` to the import block** (around lines 15-32, the existing `from app.platform.extensions.defaults import (...)` block). Insert in alphabetical order:

```python
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuditSink,
    DefaultAuthExtension,
    DefaultBillingExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
    DefaultProcessingPort,    # NEW (Phase 225)
)
```

Read the existing block first to confirm the exact placement and surrounding context (other Default* classes order). Insert `DefaultProcessingPort` in alphabetical order.

**2. Add `ProcessingPort` to the existing TYPE_CHECKING block** (find the existing `if TYPE_CHECKING:` block in this file — it currently imports `IdentityExtension` from `app.core.identity`):

```python
if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort  # NEW (Phase 225)
```

If the file currently has multiple TYPE_CHECKING blocks, find the one that imports from `app.core.identity` and add the new import line there. If no such block exists yet, create one at the appropriate location (mirror Phase 214's placement).

**3. Append the `get_processing_port()` function** AFTER the existing `get_identity_extension()` function (around line 130, after line 129). Mirror the single-slot accessor pattern verbatim:

```python
def get_processing_port() -> "ProcessingPort":
    """Return the registered ProcessingPort or the community default.

    Phase 225 / PROCESS-01 — single-slot shape (D-12), NOT list-shape
    like get_audit_sinks() / get_billing_extensions(). ProcessingPort is
    a singleton consumer surface; overlays REPLACE rather than append.

    Enterprise overlays register a tier-aware / quota-enforcing wrapper
    under the ``"processing_port"`` key via the ``geolens.extensions``
    entry-point group::

        registry["processing_port"] = TierAwareProcessingPort(quota_config)

    Community edition gets DefaultProcessingPort which forwards every
    call to the existing app.modules.catalog.* functions via deferred
    imports (D-09 / D-11 — behavior is byte-for-byte identical to
    pre-Phase-225).
    """
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]
```

**Important constraints:**
- Use registry key `"processing_port"` (with underscore, not hyphen).
- Mirror the `if ext is None: return DefaultProcessingPort()` shape exactly — do NOT use `_extensions.get("processing_port") or DefaultProcessingPort()` (mirrors `get_identity_extension` shape).
- Add `# type: ignore[return-value]` on the return — same as `get_identity_extension` line 129.
- Do NOT add `get_processing_port` to any `__all__` export list unless the existing function `get_identity_extension` is in `__all__` — match the existing pattern.

Verify after the edit that the file is syntactically valid and the function is reachable.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.platform.extensions import get_processing_port; from app.core.processing_port import ProcessingPort; port = get_processing_port(); assert isinstance(port, ProcessingPort), 'returned object does not satisfy ProcessingPort'; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - File contains line `def get_processing_port() -> "ProcessingPort":` (verifiable: `grep -c 'def get_processing_port() -> "ProcessingPort":' backend/app/platform/extensions/__init__.py` returns 1).
    - File contains import `DefaultProcessingPort` (verifiable: `grep -c "DefaultProcessingPort" backend/app/platform/extensions/__init__.py` returns ≥ 2 — once in import, once in `return DefaultProcessingPort()`).
    - File contains `from app.core.processing_port import ProcessingPort` inside TYPE_CHECKING block (verifiable: `grep -B1 "from app.core.processing_port import ProcessingPort" backend/app/platform/extensions/__init__.py` shows context within an `if TYPE_CHECKING:` block — confirm no runtime import of ProcessingPort).
    - File uses registry key `"processing_port"` (verifiable: `grep -c '_extensions.get("processing_port")' backend/app/platform/extensions/__init__.py` returns 1).
    - Smoke check passes: `cd backend && uv run python -c "from app.platform.extensions import get_processing_port; from app.core.processing_port import ProcessingPort; port = get_processing_port(); assert isinstance(port, ProcessingPort), 'fail'; print('OK')"` exits 0.
    - Phase 214 IDENT-01 architecture guard still passes: `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -x` exits 0.
    - Phase 224 façade architecture guard still passes: `cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -x` exits 0.
    - Full backend test suite remains green at baseline: `cd backend && uv run pytest -q` exits 0 with `2036 passed` (or the project's current baseline ≥ 2036).
  </acceptance_criteria>
  <done>
    `get_processing_port()` accessor reachable from `app.platform.extensions`. Default returns `DefaultProcessingPort()`. Type alias `ProcessingPort` imported under TYPE_CHECKING. Full backend test suite green (2036/2036).
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Refactor-only — no new boundaries introduced |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-225-01 | (n/a) | Phase 225 surface | accept | Refactor-only — no new attack surface introduced. The new Protocol is a typing construct + thin deferred-import forwarder; default delegates to existing catalog functions through the Phase 224 façade. No new endpoints, no new auth/authz semantics, no new data flows. Threats inherited from existing catalog services; Phase 225 does not change their authorization, validation, or trust boundaries. |

**Block:** false. Refactor only.
</threat_model>

<verification>
- `cd backend && uv run python -c "from app.core.processing_port import ProcessingPort; from app.platform.extensions.defaults import DefaultProcessingPort; from app.platform.extensions import get_processing_port; assert isinstance(get_processing_port(), ProcessingPort)"` — exits 0
- `cd backend && uv run pytest tests/test_layering.py -m architecture -x` — all existing arch-guard tests pass (no new test added in Plan 01)
- `cd backend && uv run pytest -q` — `2036 passed` (or current baseline)
- `cd backend && uv run ruff check .` — clean
- `cd backend && uv run alembic check` — no new operations (refactor doesn't touch ORM models)
</verification>

<success_criteria>
- ProcessingPort Protocol importable from `app.core.processing_port` with all 20 methods declared
- DefaultProcessingPort instantiable and structurally satisfies ProcessingPort (`isinstance(DefaultProcessingPort(), ProcessingPort) is True`)
- `get_processing_port()` returns `DefaultProcessingPort()` when registry slot empty
- Phase 214 IDENT-01 guard (`test_core_does_not_import_from_any_module`) still passes — no `from app.modules.*` runtime import in `core/processing_port.py`
- Phase 224 DECOUPLE-04 guard (`test_no_external_imports_of_dataset_domain_submodules`) still passes — `DefaultProcessingPort` delegates through facade
- Full backend test suite green at baseline (2036/2036)
- ruff clean
</success_criteria>

<output>
After completion, create `.planning/phases/225-processing-port-protocol-cycle-inversion/225-01-SUMMARY.md` with:
- What was added (3 files: 1 NEW, 2 MODIFIED)
- ProcessingPort method count (20 methods)
- Companion Protocol count (7 Protocols)
- Confirmation that 2036/2036 baseline holds
- Confirmation that Phase 214 + Phase 224 architecture guards still pass
- Notes on any signature drift discovered while reading catalog source (e.g., if `update_map` accepts more kwargs than expected)
- Any TODO flags for Plan 02 (e.g., if `get_related_keywords` in `metadata_service.py` uses embedding similarity that the simple Default impl doesn't capture)
</output>
</content>
</invoke>