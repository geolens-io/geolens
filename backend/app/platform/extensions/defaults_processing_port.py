"""Community-edition ProcessingPort default.

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns ``DefaultProcessingPort``, the processing->catalog delegation seam.
Import it via the ``app.platform.extensions.defaults`` facade, never from
this sub-module.
"""

from __future__ import annotations


class DefaultProcessingPort:
    """Community-edition default: delegates every call to app.modules.catalog.*
    via deferred imports.

    Each method does a deferred import into app.modules.catalog.* inside the
    function body, keeping platform/extensions/ free of module-load-time
    modules.* edges. Behavior is identical to the pre-split baseline — the
    Port is the seam, not a re-implementation.

    create_dataset, get_dataset etc. delegate via the
    app.modules.catalog.datasets.domain.service FACADE, never the
    sub-modules directly.
    """

    async def get_dataset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        # Explicit joinedload(Dataset.record) on the Port surface so callers
        # can rely on `dataset.record.<attr>` in async contexts without
        # depending on the facade's implicit loading — protects callers
        # from any future facade change that drops the joinedload.
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
        """Run a parameterized analysis preview for the AI chat surface.

        Params are re-validated by ``AnalysisPreviewRequest`` here, so
        LLM-supplied values pass through the same bounds/requiredness checks
        as the HTTP endpoint (a ValueError surfaces as a tool error the model
        can retry from). Callers own the dataset VISIBILITY check, for the
        mask dataset as much as the source — this port never checks it.

        feat(#683): the mask's SHAPE and SIZE are checked here, so every
        port caller gets the rails the REST route applies. Unioning points
        or lines masks nothing meaningful; without the shape check the
        failure is an empty result the model reports as real. The size
        ceiling is a resource rail: ``_mask_pieces`` materializes and
        subdivides every mask row before the preview's own row cap can bite.

        ``release_session`` is deliberately never passed — see
        ``chat_analysis._run_analysis``.
        """
        from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
        from app.modules.catalog.datasets.domain.service import (
            resolve_source_feature_count,
            run_analysis_preview,
        )
        from app.platform.analysis_sql import MAX_MASK_LAYER_FEATURES

        # Ignored unless the operation owns it, mirroring what
        # _drop_params_for_other_operations does to mask_dataset_id.
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
            # Counted like the REST route: cached snapshot when present, a
            # LIMIT-bounded live count when NULL — NULL-as-zero would admit
            # exactly the unknown-size layers this gate exists for.
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

    async def get_records_without_embeddings(self, session, *, force=False):  # type: ignore[no-untyped-def]
        import structlog
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload, selectinload

        from app.modules.catalog.datasets.domain.models import Record
        from app.processing.embeddings.helpers import (
            UNKNOWN_EMBEDDING_CONFIG,
            UNKNOWN_EMBEDDING_MODEL,
            resolve_embedding_config_fingerprint,
            resolve_embedding_model_name,
        )
        from app.processing.embeddings.models import RecordEmbedding

        stmt = (
            select(Record)
            .options(
                joinedload(Record.keywords),
                selectinload(Record.translations),
            )
            .order_by(Record.created_at)
        )
        if not force:
            # fix(#1506): "missing" means "has no vector THIS model can use",
            # not "has no vector at all" — `record_embeddings` is keyed
            # (record_id, model_name) and semantic search reads only
            # active-model rows, so the old `RecordEmbedding.id IS NULL`
            # predicate made Generate Missing a no-op after a model swap.
            # The outer join went with it: NOT EXISTS correlates on its own,
            # and the join only produced duplicate Records `.unique()`
            # collapsed again.
            model_name = await resolve_embedding_model_name(session)
            if model_name == UNKNOWN_EMBEDDING_MODEL:
                # Fail closed, the OPPOSITE of what the sentinel does for
                # #1503's read-only coverage stats: here it would select the
                # whole catalog as missing and feed a run that embeds every
                # record at provider-token cost, then fails to insert (rows
                # are stamped from EMBEDDING_MODEL.get(), NOT NULL). Selecting
                # nothing is the recoverable error.
                structlog.stdlib.get_logger(__name__).warning(
                    "backfill_skipped_unresolved_embedding_model"
                )
                return []
            # fix(#1546): "missing" narrows again, from "no vector THIS
            # MODEL can use" to "no vector this CONFIGURATION can use". A
            # model served from a different endpoint is a different vector
            # space, so a row stamped with another configuration is as
            # unusable as a superseded model's row. An unstamped row still
            # counts as covering the record, so an upgrade doesn't turn the
            # next Generate Missing into a catalog-wide re-embed.
            config_fingerprint = await resolve_embedding_config_fingerprint(
                session, model_name=model_name
            )
            if config_fingerprint == UNKNOWN_EMBEDDING_CONFIG:
                # Fail closed for the same reason as the unresolved model
                # above: an unresolvable configuration makes every stamped
                # row read as foreign.
                structlog.stdlib.get_logger(__name__).warning(
                    "backfill_skipped_unresolved_embedding_config"
                )
                return []
            stmt = stmt.where(
                ~select(RecordEmbedding.id)
                .where(
                    RecordEmbedding.record_id == Record.id,
                    RecordEmbedding.usable_by_config(model_name, config_fingerprint),
                )
                .exists()
            )
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

        # RecordKeyword is not itself tenant-scoped. Join through Record so
        # the database's Record RLS policy constrains the vocabulary to the
        # active tenant in hosted mode; with RLS disabled this is the same
        # result set as the historical single-tenant query.
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
        # Delegates via facade — never service_create.py directly.
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

    async def reconcile_distributions(  # type: ignore[no-untyped-def]
        self, session, dataset_id, record_id, table_name, geometry_type=None
    ):
        # fix(#1314): the preservation policy for user-authored rows lives
        # in the function's docstring, not here.
        from app.modules.catalog.records.service import reconcile_distributions

        return await reconcile_distributions(
            session, dataset_id, record_id, table_name, geometry_type=geometry_type
        )

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

    # ORM class helpers: returned by Port so processing/* callers can pass
    # the concrete class to apply_visibility_filter without importing from
    # app.modules.catalog.* at top-of-file (deferred-import discipline).

    def get_record_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Record

        return Record

    def get_grant_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        return DatasetGrant

    def get_dataset_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Dataset

        return Dataset

    def get_retired_table_name_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import RetiredTableName

        return RetiredTableName

    def get_dataset_version_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.collections.models import DatasetVersion

        return DatasetVersion

    def get_record_distribution_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import RecordDistribution

        return RecordDistribution

    def compute_schema_diff(  # type: ignore[no-untyped-def]
        self, old_columns, new_columns, old_feature_count, new_feature_count
    ):
        from app.modules.catalog.datasets.domain.service import compute_schema_diff

        return compute_schema_diff(
            old_columns, new_columns, old_feature_count, new_feature_count
        )

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

    # Preserves the joinedload semantics metadata_service._build_dataset_context
    # requires.
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
