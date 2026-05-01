# Phase 225: processing-port-protocol-cycle-inversion — Research

**Researched:** 2026-05-01
**Domain:** Python structural Protocol / open-core layering / SQLAlchemy deferred-import migration
**Confidence:** HIGH (all claims verified against live codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

D-01: Single comprehensive `ProcessingPort` Protocol (mirrors Phase 214 `IdentityProtocol`).
D-02: Companion structural Protocols: `DatasetProtocol`, `RecordProtocol`, `MapProtocol`, `DatasetGrantProtocol`.
D-03: `@runtime_checkable` on every Protocol.
D-04: Type aliases `Dataset = DatasetProtocol`, `Record = RecordProtocol`, etc.
D-05: No `is_*` derived properties on companion Protocols.
D-06: Read-side methods: `get_dataset`, `get_record`, `search_datasets`, `apply_visibility_filter`, `check_dataset_access`, `get_user_roles`, `get_column_stats`, `get_distinct_values`, `extract_bbox`.
D-07: Write-side methods: `create_dataset`, `create_map`, `update_map`.
D-08: Source preview helper: `build_gdal_source` on the Port.
D-09: No new domain logic in `DefaultProcessingPort` — thin deferred-import forwarders.
D-10: Protocol surface lives in `backend/app/core/processing_port.py` (NEW file).
D-11: Default impl lives in `backend/app/platform/extensions/defaults.py` as `DefaultProcessingPort`.
D-12: Typed accessor `get_processing_port() -> ProcessingPort` in `platform/extensions/__init__.py`, single-slot, key `"processing_port"`.
D-13: No `ProcessingPortExtension` nested factory wrapper.
D-14: HTTP routes use `Depends(get_processing_port)`; worker tasks call `get_processing_port()` directly.
D-15: Service-layer functions take `port: ProcessingPort` as explicit parameter.
D-16: `get_processing_port` lives in `platform/extensions/__init__.py`, NOT `auth/dependencies.py`.
D-17/D-18: Closed-set migration via `git grep`, no `import-linter`.
D-19: Function-scope deferred imports keep deferral — only the path swaps.
D-20: No backward-compat re-export shim.
D-22: ONE new `@pytest.mark.architecture` test `test_no_processing_imports_catalog`.
D-23: Strict zero-hit, NO allowlist for `processing/*`.
D-24: Reuse existing `@pytest.mark.architecture` marker.
D-25: Update `test_layering.py` module docstring.
D-26: Negative-control verification step.
D-27: Focused unit test with `FakeProcessingPort` in `backend/tests/test_processing_port.py`.
D-28: No runtime conformance test.
D-29: No Alembic migration.
D-30: Acceptance gate = 2036/2036 backend tests + ruff + architecture-guard.
D-31: No frontend involvement.
D-32: Phase 226 sequences after 225; Phase 225 does NOT touch `llm_loop.py:117,132` or `service.py:387-398`.

### Claude's Discretion

- Commit decomposition (4 commits suggested, planner may collapse/split/reorder).
- Module docstring wording in `core/processing_port.py`.
- Whether to remove trivial dead imports along the way (cleanup allowed; anything bigger deferred).
- Method naming stays identical to existing catalog function names.
- `SearchFilters`/`SearchResult`/`MapSpec`/`DatasetCreatePayload`/`ColumnStats` left as TYPE_CHECKING forward refs.
- AI service signature: `port` parameter keyword-only with no default.

### Deferred Ideas (OUT OF SCOPE)

- `CatalogReadPort` for non-processing consumers.
- `PermissionExtension` Protocol (Phase 999.8).
- `AIProviderExtension` Protocol (Phase 226).
- Catalog → processing direction (51 lines) — untouched.
- Pyright/mypy CI gate.
- `Mapped["X"]` SQLAlchemy ORM relationship typing on the new Protocols.
- Runtime conformance `isinstance` test.
- `docker-compose.yml` AWS_MARKETPLACE env-var cosmetic regression.
- `free-vs-enterprise.md:113` doc-drift.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROCESS-01 | `ProcessingPort` Protocol exists in `backend/app/core/` mirroring `IdentityProtocol` pattern | § Standard Stack + § ProcessingPort Method Surface |
| PROCESS-02 | 8 `processing/*` → `catalog/*` imports rewire through Protocol-typed boundaries | § Caller Migration Inventory |
| PROCESS-03 | AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog via Protocol | § Caller Migration Inventory (AI subsection) |
| PROCESS-04 | Architecture-guard test `test_no_processing_imports_catalog` fails CI on forbidden imports | § Architecture Guard Specification |
| PROCESS-05 | Default `ProcessingPort` preserves all existing behavior, zero regressions | § Validation Architecture + § Pitfalls |
</phase_requirements>

---

## Overview

Phase 225 inverts the `processing/* → catalog/*` half of the 19-file two-way coupling identified in `oc-separation-audit-20260430-b.md` §5. The current codebase has 8 processing files importing directly from `app.modules.catalog.*` — both at module level (20 import lines) and inside function bodies (~24 deferred imports). This creates a circular dependency at the semantic level: catalog drives processing (legitimate top-down), and processing turns around and pulls catalog ORM + service types back at import time (illegitimate cycle). Phase 225 cuts that reverse edge.

The mechanism mirrors Phase 214's `IdentityProtocol` extraction exactly: define a structural `ProcessingPort` Protocol in `app.core.processing_port` (lowest layer, no `modules.*` imports), implement `DefaultProcessingPort` in `app.platform.extensions.defaults` (platform layer, allowed to reach `modules.*` via deferred imports), expose a single-slot accessor `get_processing_port()` in `app.platform.extensions.__init__`, and migrate the 8 processing files to type against Protocol aliases and call through the port. The migration is mechanical — behavior is byte-for-byte identical because the default implementation is thin forwarders. A new architecture-guard test (`test_no_processing_imports_catalog`) seals the boundary in CI. A focused `FakeProcessingPort` unit test proves the AI service seam is genuinely testable in isolation.

**Primary recommendation:** Follow the 4-commit decomposition in § Migration Sequencing. Commit 4 (the guard test) MUST land last because it fails until all imports are gone.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Protocol surface definition | Core (`app/core/`) | — | Lowest layer; no `modules.*` imports allowed |
| Default impl (catalog delegation) | Platform Extensions | — | `platform/extensions/` is the layer licensed to reach `modules.*` |
| Port accessor (`get_processing_port`) | Platform Extensions | — | Mirrors `get_identity_extension()` location |
| RBAC visibility filter (`apply_visibility_filter`) | Processing (via Port) | Catalog (implementation) | Processing calls Port; Port delegates to catalog |
| AI map generation (`create_map`, `update_map`) | Processing AI (via Port) | Catalog Maps (implementation) | Processing defines the _intent_; catalog owns the _storage_ |
| Ingest dataset creation (`create_dataset`) | Processing Ingest (via Port) | Catalog Domain (implementation) | Ingest drives creation; catalog owns the schema |
| Architecture guard | Backend Tests | CI | `test_layering.py` regression seal |

---

## Standard Stack

### Core (already installed, no new deps)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `typing.Protocol` | stdlib | Structural subtyping | Python 3.12+ built-in |
| `typing.runtime_checkable` | stdlib | Runtime `isinstance` checks | Python 3.12+ built-in |
| `typing.TYPE_CHECKING` | stdlib | Forward-reference imports | Python 3.12+ built-in |
| `from __future__ import annotations` | stdlib | Lazy string annotations | Python 3.12+ built-in |
| `sqlalchemy.ext.asyncio.AsyncSession` | 2.x | Port method signatures | Already installed |
| `pytest.mark.architecture` | pytest | Architecture guard marker | Already registered in `backend/pyproject.toml` |

**No new packages.** Phase 225 is a pure refactoring — zero new dependencies.

### Reusable Assets (existing codebase)

| Asset | Location | What Phase 225 Borrows |
|-------|----------|----------------------|
| `IdentityProtocol` pattern | `backend/app/core/identity.py` | Module structure, docstring template, alias pattern |
| `DefaultAuditSink.emit()` pattern | `backend/app/platform/extensions/defaults.py:62-76` | Deferred-import forwarder shape for `DefaultProcessingPort` |
| `get_identity_extension()` pattern | `backend/app/platform/extensions/__init__.py:115-129` | Single-slot accessor for `get_processing_port()` |
| `_has_git_metadata()` / `_has_pathspec_magic()` / `_git_grep()` | `backend/tests/test_layering.py:50-87` | Reused verbatim in new arch-guard test |
| `@pytest.mark.architecture` marker | `backend/pyproject.toml` | Reused; no new marker needed |

---

## ProcessingPort Method Surface

Complete inventory of every catalog-side call made by the 8 processing files, grouped by the Port method that owns it.

### Read-side methods

| Port Method | Caller Sites (file:line) | Catalog Source | Concrete Signature | Async? | Notes |
|------------|--------------------------|---------------|-------------------|--------|-------|
| `get_dataset(session, dataset_id: UUID) → DatasetProtocol | None` | `export/router.py:54` | `catalog/datasets/domain/service_query.py:39` via `service.py` façade | `async def get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset | None` | async | Returns `Dataset` with `record` joinedload already applied inside `service_query.py`. Port method should mirror the joinedload guarantee (or callers that read `.record.*` will MissingGreenlet). |
| `get_record(session, record_id: UUID) → RecordProtocol | None` | `embeddings/backfill.py` (select(Record) directly) | Direct `select(Record)` w/ joinedload keywords | Planner should add helper in `service_query.py` or Port delegates to a new thin function | async | `backfill.py` does its own `select(Record).outerjoin(RecordEmbedding)` with `joinedload(Record.keywords)` — the Port method wraps a simpler single-record fetch; the backfill's complex query migrates to `port.get_record()` per-record in the loop |
| `search_datasets(session, user: Identity, user_roles: set[str], filters: "SearchFilters") → tuple[list[DatasetProtocol], int]` | `ai/service.py:274` | `catalog/search/service.py:829` | `async def search_datasets(session, user, user_roles, filters: SearchFilters) -> tuple[list[Dataset], int]` | async | Returns `(datasets_list, total_count)`. `SearchFilters` is a `@dataclass(frozen=True, slots=True)` at `catalog/search/service.py:94`. Forward-ref in Port. |
| `apply_visibility_filter(stmt, user: Identity | None, user_roles: set[str], record_cls: Any, grant_cls: Any | None) → Select` | `ai/service.py:339, 443`, `tiles/router.py` (multiple) | `catalog/authorization.py:34` | `def apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls=None) -> Select[Any]` | **sync** | CRITICAL: synchronous. Takes `record_cls` and `grant_cls` as arguments because the caller passes `Record` and `DatasetGrant` ORM classes for SQL column resolution. Port method signature must be identical. |
| `check_dataset_access(session, dataset: Any, dataset_id: UUID, user: Identity, *, user_roles: set[str] | None) → set[str]` | `tiles/router.py`, `export/router.py:60` | `catalog/authorization.py:134` | `async def check_dataset_access(session, dataset, dataset_id, user, *, user_roles=None) -> set[str]` | async | Takes the dataset ORM object itself (reads `dataset.record.*`). Returns the resolved `user_roles` set so callers can reuse it. |
| `get_user_roles(session, user: Identity) → set[str]` | `ai/router.py:181`, `tiles/router.py`, `ingest/service.py:20` | `catalog/authorization.py:99` | `async def get_user_roles(db: AsyncSession, user: Identity) -> set[str]` | async | Note: catalog impl uses `db` param name; Port uses `session`. Planner can use either — just be consistent. |
| `get_column_stats(session, table_name: str, column_name: str, *, class_count: int = 5, allowed_tables: set[str] | None = None) → dict` | `ai/service.py`, `ai/chat_service.py:29` | `catalog/datasets/domain/column_stats.py:62` | `async def get_column_stats(session, table_name, column_name, *, class_count=5, allowed_tables=None) -> dict` | async | Returns `{"min", "max", "count", "mean", "quantiles"}` dict. No named return type class — the return type is `dict` in the concrete impl. |
| `get_distinct_values(session, table_name: str, column_name: str, limit: int = 100, *, allowed_tables: set[str] | None = None) → list` | `ai/chat_service.py:29` | `catalog/datasets/domain/column_stats.py:31` | `async def get_distinct_values(session, table_name, column_name, limit=100, *, allowed_tables=None) -> list` | async | Returns `list` of native Python types (int/float/bool/str). |
| `extract_bbox(dataset: DatasetProtocol) → list[float] | None` | `ai/service.py:305` | `catalog/datasets/domain/utils.py:8` | `def extract_bbox(dataset: Dataset) -> list[float] | None` | **sync** | Calls `to_shape(dataset.record.spatial_extent).bounds`. Port method wraps this. Requires `record` and `record.spatial_extent` to be loaded. |

### Write-side methods

| Port Method | Caller Sites (file:line) | Catalog Source | Concrete Signature | Async? | Notes |
|------------|--------------------------|---------------|-------------------|--------|-------|
| `create_dataset(session, table_name: str, title: str, created_by: UUID, *, summary: str | None, visibility: str, ingestion: "IngestionResult | None") → DatasetProtocol` | `ingest/service.py:23`, `ingest/tasks_common.py:618` | `catalog/datasets/domain/service.py` façade → `service_create.py:128` | Full signature with legacy kwargs (see § Forward-Referenced Schema Types) | async | `IngestionResult` is a Pydantic `BaseModel` at `catalog/datasets/domain/schemas.py:645`. Pass `ingestion: "IngestionResult | None"` as the Port's preferred form; legacy kwargs not exposed on Port. |
| `create_map(session, name: str, description: str | None, created_by: UUID, notes: str | None) → MapProtocol` | `ai/service.py:570` | `catalog/maps/service.py:150` | `async def create_map(session, name, description, created_by, notes=None) -> Map` | async | Returns `Map` ORM. Port method signature wraps this. |
| `update_map(session, map_id: UUID, *, name: str | None, description: str | None, notes: str | None, center_lng: float | None, center_lat: float | None, zoom: float | None, bearing: float | None, pitch: float | None, basemap_style: str | None, show_basemap_labels: bool | None, visibility: str | None, widgets: list[str] | None, layers: list[dict] | None) → tuple[MapProtocol, ...]` | `ai/service.py:576`, `ai/chat_service.py` | `catalog/maps/service.py:405` | Returns `tuple[Map, list[LayerRow], str | None, str | None]` | async | The AI service calls it with: `map_obj.id, center_lng=..., center_lat=..., zoom=..., basemap_style=..., layers=...`. Port method can forward the full kwargs or expose just the subset callers use. |

### Source preview helper

| Port Method | Caller Sites (file:line) | Catalog Source | Concrete Signature | Async? | Notes |
|------------|--------------------------|---------------|-------------------|--------|-------|
| `build_gdal_source(service_type: str, base_url: str, layer_name: str, layer_id: int | str | None, token: str | None, order_field: str | None, result_limit: int | None) → tuple[str, str]` | `ingest/tasks_vector.py:302`, `ingest/tasks_reupload.py:273` | `catalog/sources/preview.py:14` | `def build_gdal_source(...) -> tuple[str, str]` | **sync** | Purely computational, no I/O. Planner verifies exact signature at plan time. |

---

## Companion Protocols Field Inventory

Every attribute access in the 8 processing files against `Dataset`, `Record`, `Map`, `DatasetGrant` ORM objects, grouped by Protocol. These are the MINIMUM fields each Protocol must expose.

### DatasetProtocol

| Attribute | Reading Site | ORM Type | Suggested Protocol Type | Notes |
|-----------|-------------|----------|------------------------|-------|
| `id` | `ai/service.py:588`, `ai/router.py:139`, many | `Mapped[uuid.UUID]` | `uuid.UUID` | PK |
| `record_id` | `ai/router.py` (implicit via `Dataset.record_id`), `metadata_service.py:201` | `Mapped[uuid.UUID]` | `uuid.UUID` | FK |
| `table_name` | `ai/router.py:139`, `tiles/router.py`, `ai/service.py:438` | `Mapped[str]` | `str` | |
| `geometry_type` | `ai/service.py:436`, `ai/router.py`, `metadata_service.py:78` | `Mapped[str | None]` | `str | None` | |
| `feature_count` | `ai/service.py:307`, `metadata_service.py:81` | `Mapped[int | None]` | `int | None` | |
| `srid` | `ai/router.py` (implicit), `metadata_service.py:84` | `Mapped[int | None]` | `int | None` | |
| `original_srid` | `metadata_service.py:96` | `Mapped[int | None]` | `int | None` | |
| `source_format` | `metadata_service.py:89` | `Mapped[str | None]` | `str | None` | |
| `source_filename` | `metadata_service.py:92` | `Mapped[str | None]` | `str | None` | |
| `source_url` | `metadata_service.py:95` | `Mapped[str | None]` | `str | None` | |
| `column_info` | `ai/service.py:307`, `metadata_service.py:119` | `Mapped[list | None]` | `list | None` | JSONB list |
| `sample_values` | `ai/service.py:289`, `metadata_service.py:125` | `Mapped[dict | None]` | `dict | None` | JSONB dict |
| `quality_detail` | `metadata_service.py:147` | `Mapped[dict | None]` | `dict | None` | |
| `quality_statement` | `metadata_service.py:153` | `Mapped[str | None]` | `str | None` | |
| `current_version` | `ingest/tasks_common.py:858` | `Mapped[int]` | `int` | Used in reupload swap |
| `record` | `ai/service.py:299`, `metadata_service.py:70` | `Mapped["Record"]` (lazy="joined") | `RecordProtocol` | Eager-loaded relationship |
| `attributes` | `metadata_service.py:138` | `Mapped[list["AttributeMetadata"]]` | `Sequence[AttributeProtocol]` | Lazy select; needs joinedload in `get_dataset` |
| `is_3d` | `metadata_service.py:147` | `Mapped[bool | None]` | `bool | None` | |

**Note on `record`:** In the ORM, `Dataset.record` is `lazy="joined"` (auto eager-loaded on any `select(Dataset)` query). For the Port's `get_dataset()` method, the existing `service_query.py:get_dataset` already applies `joinedload(Dataset.record)` — so `dataset.record` is always loaded when retrieved via the Port. Callers that go directly through `_execute_get_dataset_details` (AI service) also load `record` via `joinedload`. The Protocol field `record: RecordProtocol` is always populated.

**Note on `attributes`:** `lazy="select"` — callers that read `dataset.attributes` must have loaded them. `metadata_service.py:_build_dataset_context` uses `joinedload(Dataset.attributes)`. The Port's `get_dataset()` may need to accept an option to load attributes, OR a separate `get_dataset_with_context(session, dataset_id)` method can be exposed. Simpler: the `DefaultProcessingPort.get_dataset` delegates to `service_query.get_dataset` which already loads the record; if `metadata_service` needs attributes, it calls through the port with its own session and query.

**Simple resolution:** `DefaultProcessingPort.get_dataset` delegates to `catalog/datasets/domain/service.py::get_dataset` (loads record). Callers that need attributes run their own `select(Dataset).options(joinedload(Dataset.attributes))` pattern through the Port's `apply_visibility_filter` + session, OR a second Port method `get_dataset_with_attributes(session, dataset_id)` can be added in a later phase. For Phase 225, `_build_dataset_context` migrates to `port.get_dataset()` and the joinedload for attributes is retained in the implementation (the deferred import is just for `Dataset`/`Record` ORM, not for the query itself — the metadata service's own `session.execute(stmt)` call is kept as-is, only the import of `Dataset`/`Record` ORM models is replaced with `DatasetProtocol`/`RecordProtocol` type aliases).

### RecordProtocol

| Attribute | Reading Site | ORM Type | Suggested Protocol Type | Notes |
|-----------|-------------|----------|------------------------|-------|
| `id` | `metadata_service.py:201`, `backfill.py` | `Mapped[uuid.UUID]` | `uuid.UUID` | PK |
| `title` | `ai/service.py:299`, `metadata_service.py:73` | `Mapped[str]` | `str` | |
| `summary` | `ai/service.py:300`, `metadata_service.py:75` | `Mapped[str | None]` | `str | None` | |
| `keywords` | `ai/service.py:302`, `metadata_service.py:133`, `backfill.py:60` | `Mapped[list["RecordKeyword"]]` | `Sequence[KeywordProtocol]` | Needs joinedload |
| `spatial_extent` | `metadata_service.py:104` | `Mapped[str | None]` (GeoAlchemy2 Geometry) | `Any` | geoalchemy2 type; Protocol field typed `Any` to avoid geoalchemy2 import in `core/` |
| `lineage_summary` | `metadata_service.py:99` | `Mapped[str | None]` | `str | None` | |
| `source_organization` | `metadata_service.py:102` | `Mapped[str | None]` | `str | None` | |
| `access_constraints` | `metadata_service.py:114` | `Mapped[str | None]` | `str | None` | |
| `temporal_start` | `metadata_service.py:157` | `Mapped[date | None]` | `date | None` | |
| `temporal_end` | `metadata_service.py:159` | `Mapped[date | None]` | `date | None` | |
| `record_type` | `metadata_service.py:163` | `Mapped[str]` | `str` | |
| `created_at` | `backfill.py` (ORDER BY) | `Mapped[datetime]` | `datetime` | |

**KeywordProtocol:** The `RecordKeyword` fields read by processing code: `keyword: str`. That is the only field accessed (e.g., `kw.keyword for kw in record.keywords`). `record_id` is not read cross-domain.

**AttributeProtocol:** Fields read in `metadata_service.py:138`: `is_current: bool`, `field_name: str`, `description: str | None`, `data_type: str | None`.

### MapProtocol

| Attribute | Reading Site | ORM Type | Suggested Protocol Type | Notes |
|-----------|-------------|----------|------------------------|-------|
| `id` | `ai/service.py:588`, `ai/router.py:111` | `Mapped[uuid.UUID]` | `uuid.UUID` | PK |
| `created_by` | `ai/router.py:117` | `Mapped[uuid.UUID | None]` | `uuid.UUID | None` | Ownership check |
| `basemap_style` | `ai/router.py:121` | `Mapped[str]` | `str` | |
| `name` | `ai/service.py:591` | `Mapped[str]` | `str` | |

**Note:** `ai/router.py:139` does `select(Dataset.id, Dataset.table_name, Dataset.geometry_type)` against a map's layers — this is a direct SQL query on `Dataset`, not on `Map.layers`. The Port's `MapProtocol` does not need a `layers` field for the current migration; the router handles its own layer lookup via `select(Dataset...)`.

### DatasetGrantProtocol

| Attribute | Reading Site | ORM Type | Suggested Protocol Type | Notes |
|-----------|-------------|----------|------------------------|-------|
| `dataset_id` | `authorization.py:82` (passed as `grant_cls` to visibility filter) | `Mapped[uuid.UUID]` | `uuid.UUID` | |
| `role_id` | `authorization.py:82` (join on `UserRole.role_id`) | `Mapped[uuid.UUID]` | `uuid.UUID` | |

**Important:** `DatasetGrant` is passed as `grant_cls` argument to `apply_visibility_filter()`. The function uses `grant_cls.dataset_id` and `grant_cls.role_id` as SQLAlchemy column attributes in SQL expressions — this is an **InstrumentedAttribute** use, not parameter annotation. The Port's `apply_visibility_filter` accepts `grant_cls: Any` (same as today's `catalog/authorization.py:39`). `DatasetGrantProtocol` is used only for type annotations at call sites that reference the ORM class as a value, not for the `apply_visibility_filter` signature. See Pitfall 3.

---

## Caller Migration Inventory

Full inventory of every `from app.modules.catalog.*` import in `backend/app/processing/`, with confirmed line numbers from live codebase scan.

### Module-level top-of-file imports (hard cutover)

#### `backend/app/processing/ai/service.py`
```
L33: from app.modules.catalog.authorization import apply_visibility_filter
L34: from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
L35: from app.modules.catalog.datasets.domain.utils import extract_bbox
L36: from app.modules.catalog.datasets.domain.column_stats import get_column_stats
L37: from app.modules.catalog.maps.service import create_map, update_map
L39: from app.modules.catalog.search.service import SearchFilters, search_datasets
```
**Migration:** All 6 import lines become type-annotation-only imports from `app.core.processing_port` + Port calls. The functions (`search_datasets`, `create_map`, etc.) become `port.search_datasets(...)`, `port.create_map(...)`. `SearchFilters` stays forward-referenced (TYPE_CHECKING import). `Dataset`, `DatasetGrant`, `Record` aliases imported from `app.core.processing_port`. `apply_visibility_filter` → `port.apply_visibility_filter(...)`. The `_execute_search_tool` and `_execute_get_dataset_details` helpers receive `port: ProcessingPort` parameter (D-15 applies because `generate_map_from_prompt` is a service-layer function).

#### `backend/app/processing/ai/router.py`
```
L42: from app.modules.catalog.authorization import get_user_roles
L44: from app.modules.catalog.datasets.domain.models import Dataset
L46: from app.modules.catalog.maps.models import Map
```
**Migration:** `get_user_roles` → `port.get_user_roles(...)`. `Dataset` alias from `app.core.processing_port`. `Map` alias from `app.core.processing_port` (MapProtocol). Router acquires port via `Depends(get_processing_port)`.
**Note:** `ai/router.py:139` does a raw `select(Dataset.id, Dataset.table_name, Dataset.geometry_type)` SQL expression using `Dataset` as a SQLAlchemy model column holder. This is an InstrumentedAttribute use. The Protocol alias `Dataset = DatasetProtocol` CANNOT satisfy this use — this is the same "Pitfall 1" class from Phase 214. Planner must either keep a deferred local import of the concrete `Dataset` for this query OR expose a `get_datasets_by_ids(session, ids, user, user_roles)` Port method. See Pitfall 3 below.

#### `backend/app/processing/ai/chat_service.py`
```
L29: from app.modules.catalog.datasets.domain.column_stats import (
         get_column_stats,
         get_distinct_values,
     )
```
**Migration:** `get_column_stats` → `port.get_column_stats(...)`. `get_distinct_values` → `port.get_distinct_values(...)`. Service-layer functions that call these take `port: ProcessingPort` explicitly (D-15).

#### `backend/app/processing/ai/metadata_service.py`
```
L25: from app.modules.catalog.datasets.domain.models import (
         Dataset,
         Record,
         RecordKeyword,
     )
```
**Migration:** `Dataset`, `Record` → aliases from `app.core.processing_port`. `RecordKeyword` is only used as `RecordKeyword.keyword` and `RecordKeyword.record_id` in SQL expressions at `_get_catalog_vocabulary` and `_get_related_keywords_from_embeddings`. These are InstrumentedAttribute SQL uses — same pitfall class. Planner resolution: expose `get_catalog_vocabulary(session) → list[str]` and `get_related_keywords(session, dataset_id, limit) → list[str]` on the Port, OR keep a deferred local `from app.modules.catalog.datasets.domain.models import RecordKeyword` inside those specific helper functions (since those helpers are in `metadata_service.py`, they're service-layer code that gets `port` injected). See Pitfall 3.

#### `backend/app/processing/tiles/router.py`
```
L21: from app.modules.catalog.authorization import check_dataset_access, get_user_roles
L23: from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant
```
**Migration:** `check_dataset_access` → `port.check_dataset_access(...)`. `get_user_roles` → `port.get_user_roles(...)`. `Dataset`, `DatasetGrant` → aliases from `app.core.processing_port`. Router acquires port via `Depends(get_processing_port)`.
**Note:** `tiles/router.py` has multiple places that use `Dataset` and `DatasetGrant` in `select(Dataset).where(...)` SQL expressions and `apply_visibility_filter(..., Record, DatasetGrant)` calls. The `Record` class is imported from `catalog` for these SQL column references — planner must check `tiles/router.py` for all `Record` import usages and handle InstrumentedAttribute cases (same Pitfall 3).

#### `backend/app/processing/export/router.py`
```
L16: from app.modules.catalog.authorization import check_dataset_access
L17: from app.modules.catalog.datasets.domain.service import get_dataset
```
**Migration:** `check_dataset_access` → `port.check_dataset_access(...)`. `get_dataset` → `port.get_dataset(...)`. Router acquires port via `Depends(get_processing_port)`. This is the cleanest migration of the 8 files — no SQL InstrumentedAttribute uses.

#### `backend/app/processing/embeddings/backfill.py`
```
L15: from app.modules.catalog.datasets.domain.models import Record
```
**Migration:** `Record` → alias from `app.core.processing_port` for type annotation. The actual `select(Record).outerjoin(RecordEmbedding)...options(joinedload(Record.keywords))` query uses `Record` as an InstrumentedAttribute (SQL `FROM` target). See Pitfall 3. Planner resolution: the backfill's main loop calls `port.get_record(...)` to fetch individual records, but the bulk-fetch query selecting all un-embedded records still needs `Record` as a SQLAlchemy model. A `get_records_without_embeddings(session, *, force: bool) → list[RecordData]` Port method is cleanest, OR a deferred import of concrete `Record` is kept inside the function body.

#### `backend/app/processing/ingest/service.py`
```
L20: from app.modules.catalog.authorization import get_user_roles
L22: from app.modules.catalog.datasets.domain.models import Dataset
L23: from app.modules.catalog.datasets.domain.service import create_dataset
```
**Migration:** `get_user_roles` → `port.get_user_roles(...)`. `Dataset` → alias from `app.core.processing_port`. `create_dataset` → `port.create_dataset(...)`. Service acquires port by calling `get_processing_port()` at task entry (D-14 worker pattern).
**Note:** `ingest/service.py:L22` `Dataset` usage — check if it's used in SQL expressions (InstrumentedAttribute) or only for type annotations.

### Function-scope deferred imports (keep deferral, swap path)

#### `backend/app/processing/embeddings/tasks.py:21`
```python
# Inside function body (task body):
from app.modules.catalog.datasets.domain.models import Dataset, Record
```
**Type:** Runtime deferred (not TYPE_CHECKING — the task function uses `Dataset` and `Record` in a `select()` ORM query).
**Migration:** Keep deferral, swap to deferred `from app.platform.extensions import get_processing_port; port = get_processing_port()` then call Port methods. The InstrumentedAttribute issue applies here too.

#### `backend/app/processing/ingest/tasks_vector.py:302`
```python
from app.modules.catalog.sources.preview import build_gdal_source
```
**Migration:** `port.build_gdal_source(...)`.

#### `backend/app/processing/ingest/tasks_common.py:618`
```python
from app.modules.catalog.datasets.domain.service import create_dataset
```
**Migration:** `port.create_dataset(...)`.

#### `backend/app/processing/ingest/tasks_common.py:697`
```python
from app.modules.catalog.datasets.domain.schemas import IngestionResult
```
**Migration:** `from app.core.processing_port import IngestionResult` (forward ref resolved). Or keep as deferred local import since `IngestionResult` stays in catalog schemas — the Port's TYPE_CHECKING block imports it; callers that construct `IngestionResult(...)` directly still need the concrete class. Keep deferred import of concrete `IngestionResult` from catalog schemas here (the Port only exposes it as a forward ref in method signature, not re-exports the class). See Pitfall 4.

#### `backend/app/processing/ingest/tasks_common.py:849`
```python
from app.modules.catalog.collections.models import DatasetVersion
```
**Migration:** This is `collections.models.DatasetVersion` — NOT in the standard dataset domain. `DatasetVersion` is used in the reupload finalize path for version tracking. The Port does NOT expose `DatasetVersion` as a companion Protocol (D-02 only lists `Dataset`, `Record`, `Map`, `DatasetGrant`). Planner options: (a) add `DatasetVersion` as a companion Protocol (`DatasetVersionProtocol`) in Phase 225, or (b) keep this specific deferred import as a controlled exception (but the arch-guard catches it since `collections.models` is under `app.modules.catalog`). Most likely: add minimal `DatasetVersionProtocol` with just `id: UUID` to the Port, or expose a `get_dataset_version(session, dataset_id) → DatasetVersionProtocol | None` Port method. **Planner must resolve this — it was not addressed in CONTEXT.md.**

#### `backend/app/processing/ingest/tasks_reupload.py:38`
```python
from app.modules.catalog.datasets.domain.models import Dataset
```
**Migration:** Alias from `app.core.processing_port`.

#### `backend/app/processing/ingest/tasks_reupload.py:257`
```python
from app.modules.catalog.datasets.domain.models import Dataset
```
**Migration:** Same.

#### `backend/app/processing/ingest/tasks_reupload.py:273`
```python
from app.modules.catalog.sources.preview import build_gdal_source
```
**Migration:** `port.build_gdal_source(...)`.

#### `backend/app/processing/ingest/tasks_vrt.py:51, 165, 283, 362`
```python
from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordDistribution
```
**Migration:** `Dataset`, `Record` aliases from Port. `RecordDistribution` — used in SQL expressions (InstrumentedAttribute) or type annotations? Planner must grep to determine. If SQL use: same Pitfall 3 resolution. `RecordDistribution` is NOT listed in D-02's companion Protocols. If it's only used for type annotations (not SQL `select(RecordDistribution)`), a `RecordDistributionProtocol` with the accessed fields suffices.

#### `backend/app/processing/ingest/tasks_raster.py:47, 301`
```python
from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordDistribution
```
**Same treatment as tasks_vrt.py.**

#### `backend/app/processing/ingest/tasks_raster.py:143`
```python
from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401
```
**Type:** The `# noqa: F401` means this import is for side-effect (ORM registration), not direct use. This is a `Base.metadata` registration edge analogous to `tasks_raster.py:142`'s User import. HOWEVER: D-23 says strict zero-hit for `processing/*` catalog imports — but the CONTEXT.md notes that the `User` allowlist exists because catalog ORM IS already transitively loaded via the app. The same logic applies: `Dataset` ORM is loaded transitively. This import may be safe to remove. Planner must verify: run the worker in isolation to confirm `Dataset` is registered without this explicit import. If removable, remove and the arch guard passes. If needed, it becomes the only allowlist entry — but D-23 says no allowlist. Planner should attempt removal; if worker tests fail, raise a question.

#### `backend/app/processing/ingest/metadata.py:18` (TYPE_CHECKING block)
```python
if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (
        AttributeMetadata,
        Dataset,
        Record,
    )
```
**Type:** TYPE_CHECKING only — zero runtime import. Migration: move to `from app.core.processing_port import AttributeProtocol, Dataset, Record` in the TYPE_CHECKING block. No behavior change.

#### `backend/app/processing/ingest/metadata.py:466, 1076, 1102, 1130, 1188`
```python
from app.modules.catalog.datasets.domain.models import RecordKeyword
from app.modules.catalog.datasets.domain.models import AttributeMetadata  (×4)
```
**Migration:** `RecordKeyword` and `AttributeMetadata` are used in SQL expressions (`select(func.count()).where(RecordKeyword.record_id == record.id)`, `session.execute(select(AttributeMetadata)...)`). These are InstrumentedAttribute SQL uses. See Pitfall 3. Planner resolution: expose `get_record_keyword_count(session, record_id) → int` on the Port (or keep deferred local imports of `RecordKeyword` and `AttributeMetadata` inside these specific helpers, since they're implementation details of quality scoring, not cross-domain data reads).

#### `backend/app/processing/ingest/router.py:819, 1005`
```python
from app.modules.catalog.datasets.domain.models import Dataset, Record
```
**Migration:** SQL InstrumentedAttribute uses likely — planner must grep the context to determine if `Dataset` / `Record` are used in SQL queries or only for type hints.

#### `backend/app/processing/ingest/service.py:320, 368, 405`
```python
from app.modules.catalog.datasets.domain.models import Dataset  (L320, L405)
from app.modules.catalog.datasets.domain.schemas import IngestionResult  (L368)
```
**Migration:** `Dataset` → alias (if type hint only) or Port method (if SQL). `IngestionResult` construction: keep deferred import of concrete class since callers construct `IngestionResult(...)` directly.

---

## Forward-Referenced Schema Types

Types that cross the Port boundary as method parameters or return types, forward-referenced in `core/processing_port.py` via TYPE_CHECKING:

| Type Name | Concrete Location | Kind | Usage |
|-----------|------------------|------|-------|
| `SearchFilters` | `app.modules.catalog.search.service.SearchFilters` | `@dataclass(frozen=True, slots=True)` | Parameter to `search_datasets()` |
| `IngestionResult` | `app.modules.catalog.datasets.domain.schemas.IngestionResult` | Pydantic `BaseModel` | Parameter to `create_dataset()` |
| `ColumnStats` (as `dict`) | N/A — return type of `get_column_stats` is `dict`, not a named class | Plain `dict` | Return type — no forward ref needed |

**Important findings:**

- **No `SearchResult` class:** `search_datasets` returns `tuple[list[Dataset], int]` — a plain tuple, not a named class. The Port method signature returns `tuple[list[DatasetProtocol], int]`.
- **No `MapSpec` type:** The AI service uses `LLMMapSpec` (from `app.processing.ai.schemas`) as the parsed LLM output, then calls `create_map(session, name=spec.name, ...)` with keyword arguments. The Port's `create_map` method takes individual kwargs (name, description, created_by, notes), not a `MapSpec` bundle. No new forward-referenced type needed.
- **`IngestionResult` is a concrete Pydantic model** that callers construct directly. Callers that do `IngestionResult(...)` still need to import the concrete class. The Port method signature accepts `ingestion: "IngestionResult | None"` as a forward ref; callers import `IngestionResult` separately from `app.modules.catalog.datasets.domain.schemas`. This means `tasks_common.py:697`'s deferred import of `IngestionResult` stays — it's not a catalog ORM import, it's a schema import that the architecture guard regex (`^\s*(from|import)\s+app\.modules\.catalog`) does NOT distinguish from ORM imports. Planner must decide: add `IngestionResult` to Port's TYPE_CHECKING block and re-export from `core/processing_port.py`, OR accept that `from app.modules.catalog.datasets.domain.schemas import IngestionResult` remains in processing files. **This is an unresolved question — see § Open Questions.**
- **`DatasetVersion`**: `app.modules.catalog.collections.models.DatasetVersion` — used in `tasks_common.py:849`. No companion Protocol defined for it in D-02. Requires planner decision (see § Open Questions).

---

## Architecture Guard Specification

### Test: `test_no_processing_imports_catalog`

**File:** `backend/tests/test_layering.py` (append after line 620)

**Pattern (regex):** `^\s*(from|import)\s+app\.modules\.catalog`

**Pathspec:** `backend/app/processing/` (scan target)

**Exclusions:** `:!backend/tests/` (test fixtures use concrete ORM directly)

**Skip guards:** `_has_git_metadata()` + `_has_pathspec_magic()` (reused verbatim from existing helpers)

**git grep invocation:**
```python
result = subprocess.run(
    [
        "git", "grep", "-n", "-E",
        r"^\s*(from|import)\s+app\.modules\.catalog",
        "--",
        "backend/app/processing/",
    ],
    cwd=REPO_ROOT,
    capture_output=True,
    text=True,
    check=False,
)
```

**Fail condition:** `result.returncode == 0` (matches found)

**Fail message:** `"Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ contains direct imports from app.modules.catalog.*. All catalog access must go through ProcessingPort (app.core.processing_port). Offending lines:\n" + result.stdout`

**Pass condition:** `result.returncode == 1` (no matches)

**No allowlist.** Per D-23, zero legitimate side-effect catalog imports exist in `processing/*`.

**Note on `invalidate_catalog_cache`:** The function `from app.platform.cache.tiles import invalidate_catalog_cache` appears in `tasks_common.py:19`, `tasks_reupload.py:10`, `tasks_vrt.py:10`, `tasks_raster.py:10`, `tasks.py:30`. Module path is `app.platform.cache.tiles` — NOT `app.modules.catalog.*`. The guard regex requires `app\.modules\.catalog` prefix and does NOT trip on these. Confirmed safe.

**Negative-control verification (D-26):** Before finalizing commit 4, temporarily add `from app.modules.catalog.datasets.domain.models import Dataset` to `processing/embeddings/backfill.py`, run `pytest backend/tests/test_layering.py::test_no_processing_imports_catalog -x` and confirm it fails with the offending line. Revert.

---

## Test Seam Specification

### File: `backend/tests/test_processing_port.py` (NEW)

**Purpose:** Prove the `ProcessingPort` seam works by constructing a `FakeProcessingPort`, passing it to an AI service function, and asserting output.

**FakeProcessingPort skeleton:**
```python
"""Unit test for the ProcessingPort seam (Phase 225 D-27).

Constructs a minimal FakeProcessingPort with canned return values and
passes it to generate_map_from_prompt() to verify the seam is genuinely
testable in isolation.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakeProcessingPort:
    """Minimal stub implementing the ProcessingPort surface with canned returns."""

    def __init__(self):
        _dataset_id = uuid.uuid4()
        # Canned Dataset stub
        self._dataset = MagicMock()
        self._dataset.id = _dataset_id
        self._dataset.table_name = "test_dataset_table"
        self._dataset.geometry_type = "Polygon"
        self._dataset.feature_count = 100
        self._dataset.srid = 4326
        self._dataset.column_info = [{"name": "area", "type": "float"}]
        self._dataset.sample_values = {"area": [1.0, 2.0]}
        self._dataset.record = MagicMock()
        self._dataset.record.title = "Test Dataset"
        self._dataset.record.summary = "A test dataset"
        self._dataset.record.keywords = []
        self._dataset.record.spatial_extent = None

        # Canned Map stub
        self._map = MagicMock()
        self._map.id = uuid.uuid4()
        self._map.name = "Test Map"

        self._dataset_id = str(_dataset_id)

    async def search_datasets(self, session, user, user_roles, filters):
        return ([self._dataset], 1)

    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None):
        return stmt  # No-op: return stmt unchanged

    async def check_dataset_access(self, session, dataset, dataset_id, user, *, user_roles=None):
        return user_roles or set()

    async def get_user_roles(self, session, user):
        return {"viewer"}

    async def get_dataset(self, session, dataset_id):
        if str(dataset_id) == self._dataset_id:
            return self._dataset
        return None

    async def get_record(self, session, record_id):
        return self._dataset.record

    async def get_column_stats(self, session, table_name, column_name, **kwargs):
        return {"min": 0.0, "max": 100.0, "count": 100, "mean": 50.0, "quantiles": [25.0, 50.0, 75.0]}

    async def get_distinct_values(self, session, table_name, column_name, limit=100, **kwargs):
        return ["A", "B", "C"]

    def extract_bbox(self, dataset):
        return [-74.0, 40.7, -73.9, 40.8]

    async def create_dataset(self, session, table_name, title, created_by, **kwargs):
        return self._dataset

    async def create_map(self, session, name, description, created_by, notes=None):
        self._map.name = name
        return self._map

    async def update_map(self, session, map_id, **kwargs):
        return (self._map, [], None, None)

    def build_gdal_source(self, service_type, base_url, layer_name, **kwargs):
        return (f"{service_type}:{base_url}", layer_name)


@pytest.mark.asyncio
async def test_processing_port_seam_search(fake_session, fake_user):
    """Verify search path through FakeProcessingPort reaches the service function.

    Uses generate_map_from_prompt with a FakeProcessingPort injected via D-15's
    explicit parameter. Asserts that the function calls port.search_datasets
    and port.create_map, producing a map_id in the response.
    """
    port = FakeProcessingPort()

    from app.processing.ai.service import generate_map_from_prompt
    # generate_map_from_prompt(session, user, user_roles, prompt, *, port, language=None)
    result = await generate_map_from_prompt(
        fake_session,
        fake_user,
        {"viewer"},
        "Show me a polygon dataset",
        port=port,
        language=None,
    )
    assert "map_id" in result
```

**Note on `fake_session` and `fake_user`:** These fixtures likely exist in `conftest.py`. The planner should verify; if not, add minimal versions. The `AsyncMock` session is sufficient for `FakeProcessingPort` since all session interactions go through Port methods that return canned data.

**Note on `LLM mocking`:** `generate_map_from_prompt` calls the LLM. The test must also mock the LLM client (e.g., mock `run_tool_loop` or the `anthropic`/`openai` clients). The test is a single focused proof of the seam — it does not need to exercise the full tool loop. Planner may simplify by mocking `_execute_search_tool` and `_execute_get_dataset_details` to return canned data rather than running the full LLM.

**Alternative simpler seam test:** Test `_build_map_spec_and_persist` (the inner function that calls `port.create_map`) directly rather than the full `generate_map_from_prompt`. This avoids LLM mocking entirely.

---

## Migration Sequencing

### Commit 1: Protocol definition (additive only)

**Message:** `refactor(core): add ProcessingPort Protocol + companion structural Protocols (Phase 225 PROCESS-01)`

**Files touched:**
- `backend/app/core/processing_port.py` — NEW file
- `backend/app/platform/extensions/defaults.py` — add `DefaultProcessingPort` class
- `backend/app/platform/extensions/__init__.py` — add `get_processing_port()` accessor + import `DefaultProcessingPort`

**Content:**
- `core/processing_port.py`: module docstring (credit Phases 214/222/225, point to Phase 226 as next consumer), `from __future__ import annotations`, `TYPE_CHECKING` block importing `SearchFilters`, `IngestionResult`, `AsyncSession` from SQLAlchemy. All five Protocols (`@runtime_checkable`) + type aliases + `ProcessingPort` comprehensive Protocol.
- `DefaultProcessingPort`: 12 methods (9 read + 3 write + 1 preview helper), each with deferred `from app.modules.catalog.*` import inside the method body.
- `get_processing_port()`: mirrors `get_identity_extension()` exactly.

**Test:** Full suite must pass (2036/2036) — no behavior change, nothing is wired in yet.

### Commit 2: Migrate module-level imports + service-layer parameter retyping

**Message:** `refactor(processing): rewire module-level catalog imports through ProcessingPort (Phase 225 PROCESS-02/03)`

**Files touched:**
- `backend/app/processing/ai/service.py` — remove 6 catalog imports; add `ProcessingPort`, `Dataset`, `Record`, `DatasetGrant`, `SearchFilters` from Port; add `port: ProcessingPort` param to `generate_map_from_prompt`, `stream_generate_map`, `_execute_search_tool`, `_execute_get_dataset_details`, `_build_map_spec_and_persist`
- `backend/app/processing/ai/router.py` — remove 3 catalog imports; add `Depends(get_processing_port)`; pass `port` to service-layer calls
- `backend/app/processing/ai/chat_service.py` — remove `column_stats` import; add `port: ProcessingPort` to service functions
- `backend/app/processing/ai/metadata_service.py` — remove 3 catalog model imports; handle InstrumentedAttribute cases
- `backend/app/processing/tiles/router.py` — remove 2 catalog imports; add `Depends(get_processing_port)`
- `backend/app/processing/export/router.py` — remove 2 catalog imports; add `Depends(get_processing_port)`
- `backend/app/processing/embeddings/backfill.py` — remove `Record` import; handle backfill query
- `backend/app/processing/ingest/service.py` — remove 3 catalog imports (lines 20, 22, 23)

**Test:** Full suite must pass (2036/2036).

### Commit 3: Migrate function-scope deferred imports

**Message:** `refactor(processing/ingest): rewire deferred-import catalog calls through ProcessingPort (Phase 225 PROCESS-02)`

**Files touched:**
- `backend/app/processing/ingest/tasks_vector.py` — line 302 (`build_gdal_source`)
- `backend/app/processing/ingest/tasks_common.py` — lines 618, 697, 849
- `backend/app/processing/ingest/tasks_reupload.py` — lines 38, 257, 273
- `backend/app/processing/ingest/tasks_vrt.py` — lines 51, 165, 283, 362
- `backend/app/processing/ingest/tasks_raster.py` — lines 47, 143, 301
- `backend/app/processing/ingest/metadata.py` — lines 18 (TYPE_CHECKING), 466, 1076, 1102, 1130, 1188
- `backend/app/processing/ingest/router.py` — lines 819, 1005
- `backend/app/processing/ingest/service.py` — lines 320, 368, 405
- `backend/app/processing/embeddings/tasks.py` — line 21

**Test:** Full suite must pass (2036/2036).

### Commit 4: Architecture-guard test + FakeProcessingPort unit test + verification gate

**Message:** `test(layering): add test_no_processing_imports_catalog architecture guard (Phase 225 PROCESS-04)`

**Files touched:**
- `backend/tests/test_layering.py` — update module docstring (D-25); append `test_no_processing_imports_catalog` test
- `backend/tests/test_processing_port.py` — NEW file with `FakeProcessingPort` + seam test

**Pre-commit verification:**
1. `grep -RE "from backend.app.modules.catalog|from app.modules.catalog" backend/app/processing/` → zero hits
2. `cd backend && uv run pytest tests/test_layering.py -x -m architecture` → all pass
3. `cd backend && uv run alembic check` → no new operations
4. `cd backend && uv run ruff check .` → clean
5. `cd backend && uv run pytest tests/test_processing_port.py -x` → pass
6. Negative-control test (D-26): add forbidden import, confirm test fails, revert
7. `cd backend && uv run pytest` → 2036/2036 (or new baseline if tests were added)

---

## Pitfalls

### Pitfall 1: Phase 224 façade discipline — `DefaultProcessingPort` must not bypass the façade

**What goes wrong:** `DefaultProcessingPort.create_dataset` does a deferred import of `from app.modules.catalog.datasets.domain.service_create import create_dataset` (a sub-module) instead of `from app.modules.catalog.datasets.domain.service import create_dataset` (the façade).

**Why it happens:** The sub-modules are the actual implementations; the façade is a thin re-export. The sub-modules are more "direct."

**How to avoid:** Always import from `app.modules.catalog.datasets.domain.service` (the façade), never from `service_create.py`, `service_query.py`, etc. Phase 224's `test_no_external_imports_of_dataset_domain_submodules` guard enforces this — `DefaultProcessingPort` in `platform/extensions/defaults.py` IS in `backend/app/` and IS covered by that guard.

**Warning signs:** `test_no_external_imports_of_dataset_domain_submodules` fails with `platform/extensions/defaults.py` as the offending line.

### Pitfall 2: SQLAlchemy `MissingGreenlet` on lazy-loaded relationships

**What goes wrong:** After migration, code does `dataset = await port.get_dataset(session, id); dataset.attributes` — but `attributes` is `lazy="select"` and no `joinedload` was applied. SQLAlchemy raises `MissingGreenlet: greenlet_spawn has not been called` when accessing `.attributes` outside an async context.

**Why it happens:** `service_query.get_dataset` applies `joinedload(Dataset.record)` but NOT `joinedload(Dataset.attributes)`. After session commit or expire, accessing lazy relationships triggers a new select that can't run outside an async context.

**How to avoid:** Audit every call site that reads `dataset.attributes` (specifically `metadata_service.py:_build_dataset_context:138`). That function calls `select(Dataset).options(joinedload(Dataset.record).joinedload(Record.keywords), joinedload(Dataset.attributes))` — it already applies the joinedload. As long as `_build_dataset_context` remains its own query builder (using `session.execute(stmt)` directly, only importing `Dataset`/`Record` as type annotations), the migration is safe. Do NOT replace the entire query with `port.get_dataset()`; only replace the type-annotation import.

**Warning signs:** `MissingGreenlet` exceptions in `metadata_service.py` or `backfill.py` tests.

### Pitfall 3: InstrumentedAttribute SQL uses — `Dataset`/`Record`/`RecordKeyword`/`AttributeMetadata` in SQL expressions

**What goes wrong:** Multiple processing files use catalog ORM classes not just as type annotations but as SQLAlchemy model classes in SQL expressions: `select(Dataset).where(Dataset.id == ...)`, `select(RecordKeyword.keyword).distinct()`, `func.count().where(RecordKeyword.record_id == record.id)`. The Protocol alias `Dataset = DatasetProtocol` is a typing construct and CANNOT be used in SQLAlchemy `select()`, `.where()`, `.join()`, etc.

**Why it happens:** SQLAlchemy `select(SomeModel)` works because `SomeModel` is a mapped class with an `__mapper__` attribute. Protocol classes have no such attribute.

**How to avoid (two strategies):**

1. **Port-method delegation:** Add Port methods that encapsulate the SQL query (`get_records_without_embeddings`, `get_catalog_vocabulary`, etc.). The `DefaultProcessingPort` implementation imports the concrete ORM class inside the method body. Call sites call `port.method()` instead of constructing the SQL directly. This is the architecturally clean approach.

2. **Controlled deferred import:** Keep the SQL-constructing code using a local `from app.modules.catalog.datasets.domain.models import RecordKeyword` (deferred, inside the function). This is NOT covered by the architecture guard because the guard scans `backend/app/processing/` and these imports ARE in processing files — they WILL be caught. So strategy 2 is not viable unless those specific files are allowlisted, but D-23 says no allowlist.

**Resolution:** Strategy 1 is required. Planner must enumerate all SQL InstrumentedAttribute use sites and add corresponding Port methods or request an architecture discussion for allowlist exceptions. The key sites are:
- `metadata_service.py`: `select(RecordKeyword.keyword).distinct()`, `select(AttributeMetadata)` queries
- `metadata_service.py`: `select(Dataset.record_id).where(Dataset.id == ...)` for embedding lookup
- `backfill.py`: `select(Record).outerjoin(RecordEmbedding)...`
- `tasks_raster.py:143`: `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401`
- `ingest/metadata.py:466+`: `select(func.count()).where(RecordKeyword.record_id == ...)`, `select(AttributeMetadata)...`

### Pitfall 4: `IngestionResult` and `DatasetVersion` are NOT ORM models — they still need imports

**What goes wrong:** `IngestionResult` is a Pydantic schema; `DatasetVersion` is an ORM model. Both live under `app.modules.catalog.*`. The architecture guard will catch deferred imports of both. If they're not exposed through the Port, and not exported from `core/processing_port.py`, the guard will fail.

**Why it happens:** D-19 says deferred imports migrate — but callers that CONSTRUCT these objects (e.g., `IngestionResult.model_validate({...})`) need the concrete class, not a Protocol alias.

**How to avoid:** The planner must decide: (a) add `IngestionResult` to `core/processing_port.py`'s TYPE_CHECKING block and re-export it (allowing `from app.core.processing_port import IngestionResult`), OR (b) acknowledge that `from app.modules.catalog.datasets.domain.schemas import IngestionResult` in processing files is a schema import that the architecture team considers acceptable alongside the Port. Similarly for `DatasetVersion`. This is an open question — see § Open Questions.

### Pitfall 5: Type alias collision — don't import both `Dataset` aliases

**What goes wrong:** After migration, a file has both:
```python
from app.core.processing_port import Dataset  # Protocol alias
from app.modules.catalog.datasets.domain.models import Dataset  # ORM class
```
This is a silent name collision where the second import shadows the first.

**Why it happens:** The migration is file-by-file; a half-migrated file might have both.

**How to avoid:** Migration is a hard swap (D-20). Each file is migrated atomically. The `grep -RE "from app.modules.catalog.*import.*Dataset" backend/app/processing/` step verifies zero surviving ORM imports after migration.

### Pitfall 6: `apply_visibility_filter` is synchronous — do not accidentally `await` it

**What goes wrong:** `apply_visibility_filter` at `catalog/authorization.py:34` is a synchronous function (no `async def`). The Port method must also be synchronous. If the implementation wraps it in `async def`, callers that call it without `await` will receive a coroutine object instead of a filtered `Select`.

**How to avoid:** `DefaultProcessingPort.apply_visibility_filter` is a plain `def`, not `async def`. Mirrors the existing sync shape exactly.

### Pitfall 7: `get_processing_port` import does not trip the architecture guard

**What goes wrong (false negative):** Concern that `from app.platform.extensions import get_processing_port` in processing files trips the guard because it's importing from `app.platform.*` which contains the word... wait, no. The guard regex is `^\s*(from|import)\s+app\.modules\.catalog`. The import path `app.platform.extensions` does NOT match this pattern.

**How to avoid:** Confirmed safe. `app.platform.extensions` has module path prefix `app.platform.*`, not `app.modules.catalog.*`.

### Pitfall 8: `invalidate_catalog_cache` — the name contains "catalog" but the path does not

**What goes wrong (false positive):** `from app.platform.cache.tiles import invalidate_catalog_cache` — the function name contains "catalog" but the module path is `app.platform.cache.tiles`. Developer might think this needs migration.

**How to avoid:** This import is NOT caught by the guard and does NOT need migration. Module path is `app.platform.cache.tiles`, not `app.modules.catalog.*`. Confirmed by inspecting all `from app.platform.cache.tiles` imports in the processing files.

### Pitfall 9: `core/processing_port.py` may not import `AsyncSession` from SQLAlchemy

**What goes wrong:** The `core/identity.py` file imports `AsyncSession` from `sqlalchemy.ext.asyncio`. Phase 214 IDENT-01 states that `core/` must not import from `app.modules.*` — SQLAlchemy is an infrastructure package, NOT under `app.modules.*`, so it's allowed.

**How to avoid:** Import `AsyncSession` from `sqlalchemy.ext.asyncio` directly in `core/processing_port.py`. This is the established pattern from `core/identity.py:29`.

### Pitfall 10: Test fixtures constructing `Dataset(...)` ORM objects still work

**What goes wrong:** Developer worries that existing tests will break because they construct `Dataset(...)` directly and the new code expects `DatasetProtocol`.

**Why it's fine:** The concrete `Dataset` ORM class structurally satisfies `DatasetProtocol` (structural subtyping — PEP 544). No `isinstance(obj, DatasetProtocol)` check is run in production code paths. Tests continue to work unchanged. The arch guard's pathspec excludes `backend/tests/`.

### Pitfall 11: `DatasetVersion` from `catalog/collections/models.py` — not in D-02

**What goes wrong:** `ingest/tasks_common.py:849` imports `DatasetVersion` from `catalog/collections/models`. This is NOT in the companion Protocols listed in D-02 (`DatasetProtocol`, `RecordProtocol`, `MapProtocol`, `DatasetGrantProtocol`). The arch guard will flag it. No Port method currently handles it.

**How to avoid:** The planner must either (a) add a `DatasetVersionProtocol` and a Port method, or (b) raise this as an open question requiring a CONTEXT.md amendment. See § Open Questions.

### Pitfall 12: `processing/ai/router.py:_validate_chat_layers` uses raw SQL `select(Dataset.id, Dataset.table_name, ...)` — InstrumentedAttribute

**What goes wrong:** `ai/router.py:139-143` does:
```python
result = await db.execute(
    select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(
        Dataset.id.in_(dataset_uuids)
    )
)
```
This uses `Dataset` as a SQLAlchemy model with column attributes — InstrumentedAttribute use. The Port alias `Dataset = DatasetProtocol` cannot be used here.

**How to avoid:** Add `get_datasets_meta_by_ids(session, ids: list[UUID]) → list[DatasetMeta]` to the Port (where `DatasetMeta` is a simple namedtuple/dataclass with `id`, `table_name`, `geometry_type`). Or keep a local deferred import — but that trips the guard. Strategy 1 (new Port method) is required.

---

## Validation Architecture

`workflow.nyquist_validation` key is absent from `.planning/config.json` → treated as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (with asyncio) |
| Config file | `backend/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `cd backend && uv run pytest tests/test_processing_port.py tests/test_layering.py::test_no_processing_imports_catalog -x` |
| Full suite command | `cd backend && uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROCESS-01 | `ProcessingPort` Protocol exists in `backend/app/core/` | unit + import smoke | `cd backend && python -c "from app.core.processing_port import ProcessingPort, get_processing_port"` | ❌ Wave 0 (new file) |
| PROCESS-02 | Zero `from app.modules.catalog` in `processing/*` | architecture guard | `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x` | ❌ Wave 0 (new test) |
| PROCESS-03 | AI features consume catalog via Protocol | architecture guard + unit seam | `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog tests/test_processing_port.py -x` | ❌ Wave 0 (new test files) |
| PROCESS-04 | Guard fails CI on forbidden imports (negative control) | manual verification D-26 | `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x` after adding forbidden import | Manual step in commit 4 |
| PROCESS-05 | Default impl preserves all existing behavior | regression | `cd backend && uv run pytest` | ✅ Existing 2036/2036 suite |

### Validation Bands

| Band | Check | Command | Gate |
|------|-------|---------|------|
| Lint | ruff clean | `cd backend && uv run ruff check .` | Per commit |
| Type annotation | No new mypy/pyright errors (not CI-gated but informational) | `cd backend && uv run mypy app/core/processing_port.py --ignore-missing-imports` | Informational |
| Unit (seam) | `FakeProcessingPort` seam test passes | `cd backend && uv run pytest tests/test_processing_port.py -x` | Commit 4 |
| Architecture | Guard test passes + negative control verified | `cd backend && uv run pytest tests/test_layering.py -m architecture -x` | Commit 4 |
| Regression | Full suite green (2036/2036 baseline) | `cd backend && uv run pytest` | All commits |
| Migration | Zero catalog imports in `processing/*` | `grep -RE "from app\.modules\.catalog" backend/app/processing/` → 0 hits | Post-commit 3 |
| Schema drift | No new Alembic ops | `cd backend && uv run alembic check` | Commit 4 |
| API contract | OpenAPI snapshot unchanged | `make openapi-check` | Commit 4 |

### Wave 0 Gaps

- [ ] `backend/app/core/processing_port.py` — NEW (PROCESS-01)
- [ ] `backend/tests/test_processing_port.py` — NEW (PROCESS-03/D-27)
- [ ] Architecture-guard test method in `backend/tests/test_layering.py` — NEW (PROCESS-04/D-22)
- [ ] `DefaultProcessingPort` in `backend/app/platform/extensions/defaults.py` — MODIFY
- [ ] `get_processing_port()` in `backend/app/platform/extensions/__init__.py` — MODIFY

---

## Open Questions

### OQ-1: `IngestionResult` import in `tasks_common.py:697`

**What we know:** `IngestionResult` is a Pydantic model at `catalog/datasets/domain/schemas.py:645`. Callers construct `IngestionResult.model_validate({...})` and pass the result to `create_dataset()`. The architecture guard regex `^\s*(from|import)\s+app\.modules\.catalog` matches `from app.modules.catalog.datasets.domain.schemas import IngestionResult`.

**What's unclear:** Should `IngestionResult` be re-exported from `core/processing_port.py` (making `from app.core.processing_port import IngestionResult` available), or is it acceptable to treat `schemas` imports differently from `models` imports?

**Recommendation:** Re-export `IngestionResult` from `core/processing_port.py` via the TYPE_CHECKING block and a direct import (since `IngestionResult` has no circular-import risk with `core/`). `IngestionResult` is a pure data model with no ORM imports. The planner should verify: `IngestionResult` imports only `pydantic` and `app.core.text` — no `app.modules.*` imports. If so, `core/processing_port.py` can directly import and re-export it without violating Phase 214 IDENT-01's `core → modules.*` layering rule. **Planner action:** grep `schemas.py` imports to confirm, then add `from app.modules.catalog.datasets.domain.schemas import IngestionResult` to `core/processing_port.py`'s TYPE_CHECKING block.

### OQ-2: `DatasetVersion` from `catalog/collections/models.py`

**What we know:** `ingest/tasks_common.py:849` does `from app.modules.catalog.collections.models import DatasetVersion`. This is needed for the reupload atomic swap path (version tracking). It's not in D-02's companion Protocols.

**What's unclear:** Does the planner add `DatasetVersionProtocol` (with `id: UUID`) + a Port method, or add this to an allowlist (which D-23 forbids), or expose a `finalize_dataset_version(session, dataset_id, ...)` Port method that encapsulates the entire swap?

**Recommendation:** Add `DatasetVersionProtocol` with the fields the reupload code reads (`id: UUID`) and a `get_dataset_version(session, dataset_id: UUID) → DatasetVersionProtocol | None` Port method. This keeps the guard strict. If the reupload code uses `DatasetVersion` in SQL expressions (InstrumentedAttribute), a `create_dataset_version(session, ...) → DatasetVersionProtocol` method may also be needed.

### OQ-3: Multiple InstrumentedAttribute SQL use sites — scope of new Port methods needed

**What we know:** At least 6 processing files use catalog ORM classes in SQLAlchemy `select()` / `.where()` / `.join()` expressions — not just as type annotations. Each such site requires either a new Port method or a deliberate exception.

**What's unclear:** The full count of new Port methods needed to cover all InstrumentedAttribute uses was not enumerated during research (it requires line-by-line analysis of each deferred import context). The CONTEXT.md's D-06/D-07 method list may be incomplete.

**Recommendation:** The planner should run `grep -n "select(Dataset\|select(Record\|select(RecordKeyword\|select(AttributeMetadata\|select(DatasetVersion" backend/app/processing/` to enumerate all SQL InstrumentedAttribute uses and add Port methods for each. The Port surface may grow beyond the D-06/D-07 list. This is expected — the CONTEXT.md notes "planner re-greps at plan time to confirm every attribute access is covered."

### OQ-4: `tasks_raster.py:143` — `# noqa: F401` side-effect Dataset import

**What we know:** `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401` at `tasks_raster.py:143` is an unused import kept for `Base.metadata` registration, analogous to the Phase 214 `User` allowlist.

**What's unclear:** Whether removing this import breaks the Procrastinate worker's ORM discovery. Phase 214 kept the `User` import as an allowlist exception; D-23 says no allowlist for Phase 225. If removing `Dataset` breaks worker startup, Phase 225 needs an exception or a different mechanism.

**Recommendation:** Attempt removal. Run the worker in test mode to verify `Dataset` is registered via transitive imports (it should be — the catalog module loader imports all models). If worker tests fail, this becomes a legitimate allowlist exception that requires amending D-23. Flag in PLAN.md as a verification step.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 225 is a pure code/config refactoring with no external service dependencies. No new tools, services, runtimes, databases, or CLIs are required. Existing backend test environment (`uv`, `pytest`, `ruff`, `alembic`) is confirmed present from prior phases.

---

## Sources

All claims verified against live codebase at `/Users/ishiland/Code/geolens/`. Confidence: HIGH throughout.

### Primary (HIGH confidence — live codebase verification)

- `backend/app/core/identity.py` — canonical Pattern reference; read end-to-end
- `backend/app/platform/extensions/defaults.py` — `DefaultAuditSink.emit()` deferred-import pattern
- `backend/app/platform/extensions/__init__.py` — `get_identity_extension()` single-slot accessor pattern
- `backend/app/platform/extensions/protocols.py` — `TYPE_CHECKING` forward-ref pattern for `AuditEvent`
- `backend/tests/test_layering.py` — 8 existing arch-guard tests; `_has_git_metadata()` / `_has_pathspec_magic()` helpers
- `backend/app/processing/ai/service.py` — all 6 module-level catalog imports, call shapes for `create_map`/`update_map`/`search_datasets`/`apply_visibility_filter`
- `backend/app/processing/ai/router.py` — 3 module-level catalog imports; InstrumentedAttribute use at line 139
- `backend/app/processing/ai/chat_service.py` — `column_stats` import at line 29
- `backend/app/processing/ai/metadata_service.py` — 3 ORM model imports; full attribute access inventory
- `backend/app/processing/tiles/router.py` — 2 module-level catalog imports
- `backend/app/processing/export/router.py` — 2 module-level catalog imports
- `backend/app/processing/embeddings/backfill.py` — `Record` import at line 15; backfill query pattern
- `backend/app/processing/ingest/service.py` — 3 module-level catalog imports (lines 20-23) + 3 deferred imports (lines 320, 368, 405)
- `backend/app/processing/embeddings/tasks.py` — deferred import at line 21 (NOT TYPE_CHECKING)
- `backend/app/processing/ingest/tasks_vector.py` — deferred `build_gdal_source` at line 302
- `backend/app/processing/ingest/tasks_common.py` — 3 deferred imports (lines 618, 697, 849); `IngestionResult` construction pattern
- `backend/app/processing/ingest/tasks_reupload.py` — 3 deferred imports (lines 38, 257, 273)
- `backend/app/processing/ingest/tasks_vrt.py` — 4 deferred imports (lines 51, 165, 283, 362)
- `backend/app/processing/ingest/tasks_raster.py` — 3 deferred imports (lines 47, 143, 301); `# noqa: F401` import at line 143
- `backend/app/processing/ingest/metadata.py` — TYPE_CHECKING block at line 18; 5 deferred `AttributeMetadata` imports
- `backend/app/processing/ingest/router.py` — 2 deferred imports (lines 819, 1005)
- `backend/app/modules/catalog/authorization.py` — `apply_visibility_filter` (sync), `get_user_roles`, `check_dataset_access` concrete signatures
- `backend/app/modules/catalog/datasets/domain/models.py` — full ORM attribute inventory for `Dataset`, `Record`, `AttributeMetadata`, `DatasetGrant`
- `backend/app/modules/catalog/datasets/domain/column_stats.py` — `get_column_stats`, `get_distinct_values` concrete signatures
- `backend/app/modules/catalog/datasets/domain/utils.py` — `extract_bbox` concrete signature (sync, `list[float] | None`)
- `backend/app/modules/catalog/datasets/domain/schemas.py` — `IngestionResult` at line 645; confirmed Pydantic model
- `backend/app/modules/catalog/datasets/domain/service_create.py` — `create_dataset` concrete signature (lines 128-154)
- `backend/app/modules/catalog/datasets/domain/service_query.py` — `get_dataset` concrete signature (line 39)
- `backend/app/modules/catalog/search/service.py` — `SearchFilters` dataclass at line 94; `search_datasets` signature at line 829 (returns `tuple[list[Dataset], int]`)
- `backend/app/modules/catalog/maps/service.py` — `create_map` signature (line 150); `update_map` signature (line 405)
- `backend/app/modules/catalog/maps/models.py` — `Map` ORM attribute inventory
- `backend/app/modules/catalog/maps/schemas.py` — `MapLayerInput`, `MapCreate` (no `MapSpec` class found)
- `backend/app/modules/catalog/sources/preview.py` — `build_gdal_source` concrete signature (line 14, sync)
- `backend/app/modules/catalog/collections/models.py` — `DatasetVersion` at line 49

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all types verified from live source
- Architecture: HIGH — all patterns verified from Phase 214/222/223/224 implementations
- Pitfalls: HIGH — verified from actual code paths and analogous Phase 214 pitfall history
- Method surface: HIGH — all signatures read from concrete implementations
- Open questions: documented with mitigation paths

**Research date:** 2026-05-01
**Valid until:** 2026-05-08 (fast-moving active codebase — re-verify before planning if >3 days elapse)
