"""Community-edition default implementations of extension protocols."""

from __future__ import annotations


class DefaultBrandingExtension:
    """Default branding: shows community badge."""

    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}


class DefaultAuditExtension:
    """Default audit: no additional export formats."""

    def get_export_formats(self) -> list[str]:
        return []


class DefaultAuthExtension:
    """Default auth: no additional auth methods."""

    def get_auth_methods(self) -> list[str]:
        return []


class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain (``get_optional_user`` / ``get_current_user``, retyped in
    Plan 02) to fall through to the existing JWT decode + DB lookup path.
    Community edition behavior is exactly today's behavior — one async
    method call returning None per request.

    The async signature is intentional (Pitfall 8). Enterprise auth
    overlays may perform DB lookups; the dep wire-in does
    ``await ext.resolve_identity_from_token(token, request, db)``, so
    all implementations — community and enterprise — MUST be async.
    """

    async def resolve_identity_from_token(self, token, request, db):  # type: ignore[no-untyped-def]
        return None


class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (Phase 222 D-04 / AUDIT-02
    option a). Application code does NOT call log_action() directly post-Phase-222;
    only this sink does.

    Does NOT swallow exceptions internally (D-07) — only the audit_emit() facade
    swallows. Internal swallowing would silently lose session.flush() constraint
    failures that today's tests expect to surface.

    The async signature is intentional: enterprise overlays may perform non-blocking
    I/O (S3 PutObject, SIEM HTTP POST). All sinks — community and enterprise — are
    awaited by ``audit_emit()``.
    """

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


class DefaultBillingExtension:
    """Community-edition default — no-op startup hook (Phase 223 D-07 / BILLING-01).

    Mirrors ``DefaultIdentityExtension``: an async no-op that lets the dispatch
    loop iterate over a non-empty ``[DefaultBillingExtension()]`` list when no
    overlay is registered. Empty-list-as-default would also work but breaks
    symmetry with the four existing single-slot Protocols (each has a
    ``Default*`` class).

    The async signature is intentional (D-08): enterprise overlays may perform
    non-blocking I/O (HTTP calls to billing APIs, async DB writes for audit).
    All extensions — community and enterprise — are awaited by the lifespan
    dispatch loop (Plan 02).
    """

    async def on_startup(self, app) -> None:  # type: ignore[no-untyped-def]
        return


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

    # -------------------------------------------------------------------------
    # Read-side methods (D-06)
    # -------------------------------------------------------------------------

    async def get_dataset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        # Explicit joinedload(Dataset.record) on the Port surface so callers can
        # rely on `dataset.record.<attr>` access in async contexts without
        # depending on the facade's implicit loading semantics. The facade today
        # also eager-loads, but pinning the contract here protects callers (e.g.
        # processing/export/router.py:95 reads dataset.record.title) from any
        # future facade-internal change that drops the joinedload.
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

    async def get_record(self, session, record_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Record

        stmt = (
            select(Record)
            .where(Record.id == record_id)
            .options(joinedload(Record.keywords))
        )
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

        return await check_dataset_access(
            session, dataset, dataset_id, user, user_roles=user_roles
        )

    async def get_user_roles(self, session, user):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import get_user_roles

        return await get_user_roles(session, user)

    async def get_column_stats(self, session, table_name, column_name, *, class_count=5, allowed_tables=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_column_stats

        return await get_column_stats(
            session,
            table_name,
            column_name,
            class_count=class_count,
            allowed_tables=allowed_tables,
        )

    async def get_distinct_values(self, session, table_name, column_name, limit=100, *, allowed_tables=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_distinct_values

        return await get_distinct_values(
            session,
            table_name,
            column_name,
            limit,
            allowed_tables=allowed_tables,
        )

    def extract_bbox(self, dataset):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.utils import extract_bbox

        return extract_bbox(dataset)

    # -------------------------------------------------------------------------
    # OQ-3 InstrumentedAttribute encapsulators
    # -------------------------------------------------------------------------

    async def get_records_without_embeddings(self, session, *, force=False):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Record
        from app.processing.embeddings.models import RecordEmbedding

        stmt = (
            select(Record)
            .outerjoin(RecordEmbedding, Record.id == RecordEmbedding.record_id)
            .options(joinedload(Record.keywords))
            .order_by(Record.created_at)
        )
        if not force:
            stmt = stmt.where(RecordEmbedding.id.is_(None))
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

    async def get_keywords_for_records(self, session, record_ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import RecordKeyword

        if not record_ids:
            return []

        stmt = (
            select(RecordKeyword.keyword)
            .where(RecordKeyword.record_id.in_(record_ids))
            .distinct()
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

    # -------------------------------------------------------------------------
    # Write-side methods (D-07)
    # -------------------------------------------------------------------------

    async def create_dataset(self, session, table_name, title, created_by, *, summary=None, visibility="private", ingestion=None):  # type: ignore[no-untyped-def]
        # Delegates via facade — never service_create.py directly (DECOUPLE-04).
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

    # -------------------------------------------------------------------------
    # Source preview helper (D-08)
    # -------------------------------------------------------------------------

    def build_gdal_source(self, service_type, base_url, layer_name, layer_id=None, token=None, order_field=None, result_limit=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.sources.preview import build_gdal_source

        return build_gdal_source(
            service_type,
            base_url,
            layer_name,
            layer_id=layer_id,
            token=token,
            order_field=order_field,
            result_limit=result_limit,
        )

    # -------------------------------------------------------------------------
    # ORM class helpers (Plan 02 — returned by Port so processing/* callers
    # can pass the concrete class to apply_visibility_filter without importing
    # from app.modules.catalog.* at top-of-file; deferred-import discipline)
    # -------------------------------------------------------------------------

    def get_record_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Record
        return Record

    def get_grant_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import DatasetGrant
        return DatasetGrant

    def get_dataset_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Dataset
        return Dataset

    def get_dataset_version_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.collections.models import DatasetVersion
        return DatasetVersion

    def get_record_distribution_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import RecordDistribution
        return RecordDistribution

    def get_attribute_metadata_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import AttributeMetadata
        return AttributeMetadata

    # -------------------------------------------------------------------------
    # Dataset-with-attributes loader (Plan 02 — preserves joinedload semantics
    # that metadata_service._build_dataset_context requires; Pitfall 2)
    # -------------------------------------------------------------------------

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
