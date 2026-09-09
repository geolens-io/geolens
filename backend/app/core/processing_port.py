"""Cross-domain catalog access contract.

Defines structural Protocols that processing/* uses to read/write catalog
data without importing the concrete SQLAlchemy ORM from
app.modules.catalog.* — ORM classes satisfy them structurally (PEP 544).

Uses only stdlib types (plus AsyncSession) to avoid a core -> modules.catalog
import edge (Phase 225 PROCESS-01..05); core/ is the lowest layer and never
imports from modules/ (Phase 214 IDENT-01). SearchFilters and
IngestionResult are typed as unresolved forward-reference strings for the
same reason.

An enterprise overlay may replace the default implementation by
registering a port under the 'processing_port' key via the
geolens.extensions entry-point group; get_processing_port() returns it on
subsequent requests.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity


@runtime_checkable
class KeywordProtocol(Protocol):
    """Slim keyword contract — only ``keyword`` is read cross-domain."""

    keyword: str


@runtime_checkable
class TranslationProtocol(Protocol):
    """Localized record text included in embedding content."""

    language: str
    title: str
    summary: str | None


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
    translations: Sequence[TranslationProtocol]
    spatial_extent: Any  # geoalchemy2 type — Any keeps core/ free of geoalchemy2 import
    lineage_summary: str | None
    # feat(#765): analysis provenance, written by processing/analysis.
    derived_from: dict | None
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
    tenant_id: uuid.UUID | None
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
    tile_cache_version: int
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
Translation = TranslationProtocol
Attribute = AttributeProtocol


@runtime_checkable
class ProcessingPort(Protocol):
    """Comprehensive catalog accessor contract used by backend/app/processing/*.

    Mirrors Phase 214 IdentityProtocol's "single comprehensive Protocol"
    shape (D-01) — every cross-domain catalog accessor processing/* needs
    is on this surface. Companion structural Protocols (DatasetProtocol,
    etc.) above type the ORM-shaped return values without leaking
    SQLAlchemy ORM into core/.

    SearchFilters and IngestionResult are typed as Any / forward-reference
    strings — they live in app.modules.* and can't be imported here (Phase
    214 IDENT-01). DefaultProcessingPort in platform/extensions/defaults.py
    has full typed access.
    """

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

    async def check_dataset_write_access(
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

    async def run_analysis_preview(
        self,
        session: AsyncSession,
        dataset: Any,
        operation: str,
        *,
        user_id: uuid.UUID,
        distance_meters: float | None = None,
        mask: dict[str, Any] | None = None,
        # feat(#683): the clip mask can come from another dataset, not just a
        # drawn polygon. Passed as the loaded object, not an id, because the
        # caller owns its visibility check, as it owns the source dataset's.
        mask_dataset: Any | None = None,
    ) -> Any: ...  # -> AnalysisPreviewResponse

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

    async def get_column_null_cardinality(
        self,
        session: AsyncSession,
        table_name: str,
        columns: list[str],
        *,
        allowed_tables: set[str] | None = None,
        max_columns: int = 20,
        sample_size: int = 10000,
    ) -> dict[str, dict]: ...

    def extract_bbox(self, dataset: DatasetProtocol) -> list[float] | None: ...

    # Implementations must eagerly populate both ``keywords`` and
    # ``translations``: embedding backfills consume them after query
    # execution and the community ORM deliberately uses lazy="raise".
    #
    # fix(#1506): with ``force=False`` the contract is "records with no vector
    # under the ACTIVE embedding model", not "records with no vector at all" —
    # an implementation that can't resolve the active model must return an
    # empty list; returning everything hands the whole catalog to a run that
    # cannot store what it embeds.
    async def get_records_without_embeddings(
        self, session: AsyncSession, *, force: bool = False
    ) -> list[RecordProtocol]: ...

    async def get_datasets_meta_by_ids(
        self, session: AsyncSession, ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, str, str | None]]: ...

    async def get_catalog_vocabulary(self, session: AsyncSession) -> list[str]: ...

    async def get_keywords_for_records(
        self, session: AsyncSession, record_ids: list[uuid.UUID]
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

    # fix(#1314): the refresh/reupload paths can change a dataset's modality,
    # so the auto-generated `record_distributions` rows must be reconciled —
    # that logic belongs beside `generate_distributions` in the catalog
    # domain, which processing/ may not import. Returns the rows created and
    # the (distribution_type, format) pairs removed, typed Any for the same
    # reason.
    async def reconcile_distributions(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        record_id: uuid.UUID,
        table_name: str,
        geometry_type: str | None = None,
    ) -> tuple[list[Any], list[tuple[str, str]]]: ...

    def build_gdal_source(
        self,
        service_type: str,
        base_url: str,
        layer_name: str,
        layer_id: int | str | None = None,
        token: str | None = None,
        order_field: str | None = None,
        result_limit: int | None = None,
        result_offset: int | None = None,
    ) -> tuple[str, str]: ...

    # ORM class helpers: let processing/* call sites pass concrete ORM
    # classes to select()/session.add() without importing app.modules.catalog.*
    # directly — Phase 214 IDENT-01 compliant since the Protocol declares
    # only a `type` return, no modules.* import.
    def get_record_orm_class(self) -> type: ...

    def get_grant_orm_class(self) -> type: ...

    def get_dataset_orm_class(self) -> type: ...

    def get_retired_table_name_orm_class(self) -> type: ...

    def get_dataset_version_orm_class(self) -> type: ...

    def get_record_distribution_orm_class(self) -> type: ...

    # feat(#1223): the swap path recomputes schema drift against the staging
    # table rather than trusting the preview, which may be minutes stale for a
    # live service. The function is pure but lives in the catalog domain, and
    # processing/ may not import it directly.
    def compute_schema_diff(
        self,
        old_columns: list[dict],
        new_columns: list[dict],
        old_feature_count: int | None,
        new_feature_count: int | None,
    ) -> dict: ...

    def get_attribute_metadata_orm_class(self) -> type: ...

    # feat(#1266): the STAC refresh strategy re-reads the item document its
    # asset was published in, through Rule 2's safe client and the #1222
    # health classifier — both live in the catalog domain, so the strategy
    # asks for the answer through this port and holds no HTTP client of its
    # own. Returns a ``StacResolution``, typed Any since core/ may not
    # import modules.*.
    # feat(#1764): ``credential`` is the ``ServiceCredential`` a credentialed
    # refresh claimed for this one attempt; typed Any for the same reason the
    # return is, and None for a public catalog.
    async def resolve_stac_binding(
        self,
        *,
        item_href: str,
        item_id: str | None,
        collection_id: str | None,
        asset_href: str | None,
        asset_key: str | None,
        credential: Any = None,
    ) -> Any: ...

    # Preserves joinedload semantics for metadata_service._build_dataset_context.
    async def get_dataset_with_attributes(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetProtocol | None: ...
