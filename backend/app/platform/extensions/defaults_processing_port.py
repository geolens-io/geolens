"""Community-edition ProcessingPort default (Phase 225 D-09 / D-11 / PROCESS-01).

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns ``DefaultProcessingPort``, the processing->catalog delegation seam.
Import it via the ``app.platform.extensions.defaults`` facade, never from
this sub-module.
"""

from __future__ import annotations


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
        from sqlalchemy.orm import joinedload, selectinload

        from app.modules.catalog.datasets.domain.models import Record

        stmt = (
            select(Record)
            .where(Record.id == record_id)
            .options(
                joinedload(Record.keywords),
                selectinload(Record.translations),
            )
        )
        result = await session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def search_datasets(self, session, user, user_roles, filters):  # type: ignore[no-untyped-def]
        from app.modules.catalog.search.service import search_datasets

        return await search_datasets(session, user, user_roles, filters)

    def apply_visibility_filter(
        self, stmt, user, user_roles, record_cls, grant_cls=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import apply_visibility_filter

        return apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls)

    async def check_dataset_access(
        self, session, dataset, dataset_id, user, *, user_roles=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import check_dataset_access

        return await check_dataset_access(
            session, dataset, dataset_id, user, user_roles=user_roles
        )

    async def check_dataset_write_access(
        self, session, dataset, dataset_id, user, *, user_roles=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import check_dataset_write_access

        return await check_dataset_write_access(
            session, dataset, dataset_id, user, user_roles=user_roles
        )

    async def get_user_roles(self, session, user):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import get_user_roles

        return await get_user_roles(session, user)

    async def run_analysis_preview(  # type: ignore[no-untyped-def]
        self,
        session,
        dataset,
        operation,
        *,
        user_id,
        distance_meters=None,
        mask=None,
        mask_dataset=None,
    ):
        """Run a parameterized analysis preview (M4) for the AI chat surface.

        Params are re-validated by ``AnalysisPreviewRequest`` here, so the
        LLM-supplied values pass through exactly the same bounds/requiredness
        checks as the HTTP endpoint (a ValueError surfaces as a tool error the
        model can retry from). Callers own the dataset VISIBILITY check, for
        the mask dataset as much as the source — this port never checks it.

        feat(#683): the mask's SHAPE and SIZE are checked here, so every port
        caller gets the rails the REST route applies in ``_load_mask_dataset``.
        Unioning points or lines masks nothing meaningful, and without the
        shape check the failure is an empty result the model reports as a real
        answer. The size ceiling is a resource rail, not a correctness one:
        ``_mask_pieces`` materializes and subdivides every mask row before the
        preview's own row cap can bite, so the work scales with the whole mask
        however small the source is.

        ``release_session`` is deliberately never passed: see the reasoning at
        the chat call site in ``chat_analysis._run_analysis``.
        """
        from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
        from app.modules.catalog.datasets.domain.service import (
            resolve_source_feature_count,
            run_analysis_preview,
        )
        from app.platform.analysis_sql import MAX_MASK_LAYER_FEATURES

        # Ignored unless the operation owns it, mirroring what
        # _drop_params_for_other_operations does to mask_dataset_id (#682).
        mask_for_op = mask_dataset if operation == "clip" else None
        if mask_for_op is not None:
            shape = (getattr(mask_for_op, "geometry_type", None) or "").upper()
            if not shape or not getattr(mask_for_op, "table_name", None):
                raise ValueError("The mask layer has no geometry to clip with.")
            if shape not in {"POLYGON", "MULTIPOLYGON"}:
                raise ValueError(
                    f"Clipping needs a polygon layer as the mask; that one is "
                    f"{shape}. Pick a polygon layer instead."
                )
            # Counted the same way the REST route counts it: the cached
            # snapshot when present, a LIMIT-bounded live count when it is
            # NULL, because NULL-as-zero would admit exactly the unknown-size
            # layers the gate exists for (fix(#701 review)).
            mask_count = await resolve_source_feature_count(
                session, mask_for_op, cap=MAX_MASK_LAYER_FEATURES
            )
            if mask_count > MAX_MASK_LAYER_FEATURES:
                raise ValueError(
                    f"That mask layer has too many features to clip with "
                    f"(limit {MAX_MASK_LAYER_FEATURES:,}). Pick a smaller "
                    "mask layer."
                )

        request = AnalysisPreviewRequest(
            operation=operation,
            distance_meters=distance_meters,
            mask=mask,
            # The validator requires exactly one mask source for clip and never
            # sees the object, so stand the id in for it.
            mask_dataset_id=getattr(mask_for_op, "id", None),
        )
        return await run_analysis_preview(
            session, dataset, request, user_id, mask_dataset=mask_for_op
        )

    async def get_column_stats(
        self, session, table_name, column_name, *, class_count=5, allowed_tables=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_column_stats

        return await get_column_stats(
            session,
            table_name,
            column_name,
            class_count=class_count,
            allowed_tables=allowed_tables,
        )

    async def get_distinct_values(
        self, session, table_name, column_name, limit=100, *, allowed_tables=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_distinct_values

        return await get_distinct_values(
            session,
            table_name,
            column_name,
            limit=limit,
            allowed_tables=allowed_tables,
        )

    async def get_column_null_cardinality(
        self,
        session,
        table_name,
        columns,
        *,
        allowed_tables=None,
        max_columns=20,
        sample_size=10000,
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import (
            get_column_null_cardinality,
        )

        return await get_column_null_cardinality(
            session,
            table_name,
            columns,
            allowed_tables=allowed_tables,
            max_columns=max_columns,
            sample_size=sample_size,
        )

    def extract_bbox(self, dataset):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.utils import extract_bbox

        return extract_bbox(dataset)

    # -------------------------------------------------------------------------
    # OQ-3 InstrumentedAttribute encapsulators
    # -------------------------------------------------------------------------

    async def get_records_without_embeddings(self, session, *, force=False):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload, selectinload

        from app.modules.catalog.datasets.domain.models import Record
        from app.processing.embeddings.models import RecordEmbedding

        stmt = (
            select(Record)
            .outerjoin(RecordEmbedding, Record.id == RecordEmbedding.record_id)
            .options(
                joinedload(Record.keywords),
                selectinload(Record.translations),
            )
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

        from app.modules.catalog.datasets.domain.models import Record, RecordKeyword

        # RecordKeyword is not itself tenant-scoped. Join through Record so the
        # database's Record RLS policy constrains the vocabulary to the active
        # tenant in hosted mode; with RLS disabled this is byte-for-byte the
        # same result set as the historical single-tenant query.
        stmt = (
            select(RecordKeyword.keyword)
            .join(Record, RecordKeyword.record_id == Record.id)
            .distinct()
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_keywords_for_records(self, session, record_ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import Record, RecordKeyword

        if not record_ids:
            return []

        stmt = (
            select(RecordKeyword.keyword)
            .join(Record, RecordKeyword.record_id == Record.id)
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

        stmt = select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset_id
        )
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

    async def create_dataset(
        self,
        session,
        table_name,
        title,
        created_by,
        *,
        summary=None,
        visibility="private",
        ingestion=None,
    ):  # type: ignore[no-untyped-def]
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

    def build_gdal_source(
        self,
        service_type,
        base_url,
        layer_name,
        layer_id=None,
        token=None,
        order_field=None,
        result_limit=None,
        result_offset=None,
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.sources.preview import build_gdal_source

        return build_gdal_source(
            service_type,
            base_url,
            layer_name,
            layer_id=layer_id,
            token=token,
            order_field=order_field,
            result_limit=result_limit,
            result_offset=result_offset,
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

    def compute_schema_diff(self, old_columns, new_columns, old_count, new_count):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.service import compute_schema_diff

        return compute_schema_diff(old_columns, new_columns, old_count, new_count)

    def get_attribute_metadata_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        return AttributeMetadata

    async def resolve_stac_binding(  # type: ignore[no-untyped-def]
        self, *, item_href, item_id, collection_id, asset_href, asset_key
    ):
        from app.modules.catalog.sources.stac_resolve import resolve_stac_binding

        return await resolve_stac_binding(
            item_href=item_href,
            item_id=item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )

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
