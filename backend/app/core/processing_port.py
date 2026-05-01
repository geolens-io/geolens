"""Cross-domain catalog access contract.

Defines structural Protocols that processing/* uses to read and write
catalog data without importing the concrete SQLAlchemy ORM from
app.modules.catalog.*. Concrete ORM classes (Dataset, Record, Map,
DatasetGrant, DatasetVersion, RecordKeyword, AttributeMetadata) satisfy
the Protocols structurally (PEP 544); no inheritance is required.

Uses only stdlib types (plus SQLAlchemy's AsyncSession for async method
signatures) to avoid the core -> modules.catalog import edge that Phase 225
(PROCESS-01..05) is closing. AsyncSession is an infrastructure type that
does NOT live under app.modules.*. SearchFilters and IngestionResult are
referenced as unresolved forward-reference strings only; their concrete
types live in app.modules.* and are NOT imported here (Phase 214 IDENT-01:
core/ is the lowest layer — modules depend on core, not the reverse).

An enterprise overlay (e.g., geolens-enterprise) may replace the default
implementation by registering a tier-aware or quota-enforcing port under
the 'processing_port' key via the geolens.extensions entry-point group;
get_processing_port() returns it on subsequent requests. Phase 226
(AIProviderExtension) is the next consumer of this boundary.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Protocol, Sequence, runtime_checkable

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity


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

    InstrumentedAttribute SQL uses pass the concrete ORM class as
    ``grant_cls: Any``.
    """

    id: uuid.UUID
    dataset_id: uuid.UUID
    role_id: uuid.UUID


@runtime_checkable
class DatasetVersionProtocol(Protocol):
    """Catalog DatasetVersion surface — only ``id`` is read by reupload finalize path (OQ-2)."""

    id: uuid.UUID


# Shorter aliases for caller annotations (Phase 225 D-04, mirrors Phase 214 D-05).
# Both names are exported; ``Dataset`` reads cleaner in parameter annotations
# and ``DatasetProtocol`` is preferred in conformance assertions.
Dataset = DatasetProtocol
Record = RecordProtocol
Map = MapProtocol
DatasetGrant = DatasetGrantProtocol
DatasetVersion = DatasetVersionProtocol
Keyword = KeywordProtocol
Attribute = AttributeProtocol


@runtime_checkable
class ProcessingPort(Protocol):
    """Comprehensive catalog accessor contract used by backend/app/processing/*.

    Mirrors Phase 214 IdentityProtocol's "single comprehensive Protocol"
    shape (D-01). Every cross-domain catalog accessor processing/* needs
    today is on this surface. Companion structural Protocols (DatasetProtocol,
    etc.) above type the ORM-shaped return values without leaking SQLAlchemy
    ORM into core/.

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

    NOTE: SearchFilters and IngestionResult are typed as Any / unresolved
    forward-reference strings — they live in app.modules.* and cannot be
    imported here (Phase 214 IDENT-01 layering rule). DefaultProcessingPort
    in platform/extensions/defaults.py has full typed access.
    """

    # -------------------------------------------------------------------------
    # Read-side (D-06)
    # -------------------------------------------------------------------------

    async def get_dataset(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetProtocol | None: ...

    async def get_record(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> RecordProtocol | None: ...

    async def search_datasets(
        self,
        session: AsyncSession,
        user: Identity | None,
        user_roles: set[str],
        filters: Any,  # SearchFilters — typed Any; concrete type in app.modules.*
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

    async def get_user_roles(
        self, session: AsyncSession, user: Identity
    ) -> set[str]: ...

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

    # -------------------------------------------------------------------------
    # OQ-3 InstrumentedAttribute encapsulators (Pitfall 3 / Pitfall 12 resolution)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Write-side (D-07)
    # -------------------------------------------------------------------------

    async def create_dataset(
        self,
        session: AsyncSession,
        table_name: str,
        title: str,
        created_by: uuid.UUID,
        *,
        summary: str | None = None,
        visibility: str = "private",
        ingestion: Any = None,  # IngestionResult | None — typed Any; concrete type in app.modules.*
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

    def create_ingestion_result(self, **kwargs: Any) -> Any: ...  # -> IngestionResult

    # -------------------------------------------------------------------------
    # Source preview helper (D-08)
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # ORM class helpers (Plans 02 + 03a — enable processing/* call sites
    # to pass concrete ORM classes to select() / session.add() without
    # importing from app.modules.catalog.* directly; Phase 214 IDENT-01
    # guard compliant because the Protocol only declares `type` return,
    # no modules.* import)
    # -------------------------------------------------------------------------

    def get_record_orm_class(self) -> type: ...

    def get_grant_orm_class(self) -> type: ...

    def get_dataset_orm_class(self) -> type: ...

    def get_dataset_version_orm_class(self) -> type: ...

    def get_record_distribution_orm_class(self) -> type: ...

    def get_attribute_metadata_orm_class(self) -> type: ...

    # -------------------------------------------------------------------------
    # Dataset-with-attributes loader (Plan 02 — preserves joinedload semantics
    # for metadata_service._build_dataset_context; Pitfall 2 mitigation)
    # -------------------------------------------------------------------------

    async def get_dataset_with_attributes(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetProtocol | None: ...
