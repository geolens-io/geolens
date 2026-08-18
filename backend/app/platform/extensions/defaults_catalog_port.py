"""Community-edition CatalogPort default.

Split from the former single-module ``defaults.py`` (#836): this sub-module
owns ``DefaultCatalogPort``, the catalog->processing delegation seam (every
``app.processing`` import stays deferred inside method bodies per the Phase
214 discipline). Import it via the ``app.platform.extensions.defaults``
facade, never from this sub-module.
"""

from __future__ import annotations

from app.core.db.tenant_session import defer_async_with_tenant


class DefaultCatalogPort:
    """Community default: delegates catalog calls into app.processing.* lazily."""

    @property
    def priority_queue_threshold_bytes(self) -> int:
        from app.processing.ingest.constants import PRIORITY_QUEUE_THRESHOLD_BYTES

        return PRIORITY_QUEUE_THRESHOLD_BYTES

    def ingestion_error_class(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.ogr import IngestionError

        return IngestionError

    def raster_asset_orm_class(self):  # type: ignore[no-untyped-def]
        from app.processing.raster.models import RasterAsset

        return RasterAsset

    def dataset_asset_orm_class(self):  # type: ignore[no-untyped-def]
        from app.processing.raster.models import DatasetAsset

        return DatasetAsset

    def vrt_generation_orm_class(self):  # type: ignore[no-untyped-def]
        from app.processing.raster.models import VrtGeneration

        return VrtGeneration

    def record_embedding_orm_class(self):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.models import RecordEmbedding

        return RecordEmbedding

    def embedding_unavailable_error_class(self):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.service import EmbeddingUnavailableError

        return EmbeddingUnavailableError

    def vrt_mutation_response_model(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.schemas import VrtMutationResponse

        return VrtMutationResponse

    def presigned_complete_request_model(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.schemas import PresignedCompleteRequest

        return PresignedCompleteRequest

    def presigned_upload_request_model(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.schemas import PresignedUploadRequest

        return PresignedUploadRequest

    def presigned_upload_response_model(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.schemas import PresignedUploadResponse

        return PresignedUploadResponse

    def upload_response_model(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.schemas import UploadResponse

        return UploadResponse

    async def abort_presigned_multipart_upload(  # type: ignore[no-untyped-def]
        self, storage, *, key, upload_id, job_id
    ):
        from app.processing.ingest.presigned import abort_presigned_multipart_upload

        return await abort_presigned_multipart_upload(
            storage, key=key, upload_id=upload_id, job_id=job_id
        )

    # fix(#1590): explicit keyword-only signature instead of a bare
    # **kwargs shim, so a missing or misspelled keyword surfaces here
    # instead of deep inside the service call. `replacing_dataset_id` is a
    # structural superset over CatalogPort's declared params — see the
    # comment on CatalogPort.verify_completed_presigned_upload for why it
    # is not on the Protocol yet, and test_port_signature_parity_1590.py's
    # EXPECTED_SUPERSET_PARAMS for how the structural test tracks it.
    async def verify_completed_presigned_upload(  # type: ignore[no-untyped-def]
        self,
        *,
        db,
        storage,
        key,
        expected_size,
        user_id,
        request,
        job_id,
        replacing_dataset_id=None,
    ):
        from app.processing.ingest.presigned import verify_completed_presigned_upload

        return await verify_completed_presigned_upload(
            db=db,
            storage=storage,
            key=key,
            expected_size=expected_size,
            user_id=user_id,
            request=request,
            job_id=job_id,
            replacing_dataset_id=replacing_dataset_id,
        )

    async def lock_presigned_job(self, db, job_id):  # type: ignore[no-untyped-def]
        from app.processing.ingest.presigned import lock_presigned_job

        return await lock_presigned_job(db, job_id)

    async def should_assemble_multipart(self, storage, um, physical_key):  # type: ignore[no-untyped-def]
        from app.processing.ingest.presigned import should_assemble_multipart

        return await should_assemble_multipart(storage, um, physical_key)

    def require_completable_presigned_job(self, job, *, restart_hint):  # type: ignore[no-untyped-def]
        from app.processing.ingest.presigned import (
            require_completable_presigned_job,
        )

        return require_completable_presigned_job(job, restart_hint=restart_hint)

    def require_signable_job_lifetime(self, created_at):  # type: ignore[no-untyped-def]
        from app.processing.ingest.presigned import require_signable_job_lifetime

        return require_signable_job_lifetime(created_at)

    def sign_url_with_deadline(self, storage_method, created_at, *args):  # type: ignore[no-untyped-def]
        from app.processing.ingest.presigned import sign_url_with_deadline

        return sign_url_with_deadline(storage_method, created_at, *args)

    # fix(#1590): explicit keyword-only signature instead of a bare
    # **kwargs shim, so a missing or misspelled keyword surfaces here
    # instead of deep inside the service call. `replacing_dataset_id` is a
    # structural superset over CatalogPort's declared params — see the
    # comment on CatalogPort.finalize_presigned_object for why it is not on
    # the Protocol yet, and test_port_signature_parity_1590.py's
    # EXPECTED_SUPERSET_PARAMS for how the structural test tracks it.
    async def finalize_presigned_object(  # type: ignore[no-untyped-def]
        self,
        *,
        db,
        storage,
        job_id,
        logical_key,
        expected_size,
        filename,
        user_id,
        request,
        replacing_dataset_id=None,
    ):
        from app.processing.ingest.presigned import finalize_presigned_object

        return await finalize_presigned_object(
            db=db,
            storage=storage,
            job_id=job_id,
            logical_key=logical_key,
            expected_size=expected_size,
            filename=filename,
            user_id=user_id,
            request=request,
            replacing_dataset_id=replacing_dataset_id,
        )

    def visibility_default(self) -> str:
        return "private"

    @staticmethod
    def _data_plane_target(schema=None, role=None):  # type: ignore[no-untyped-def]
        """Resolve omitted identifiers from the active request/job tenant."""
        from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
        from app.core.db.tenant_session import current_tenant_var

        tenant_id = current_tenant_var.get()
        return (
            schema if schema is not None else tenant_data_schema(tenant_id),
            role if role is not None else tenant_reader_role(tenant_id),
        )

    async def compute_quality_score(
        self, session, table_name, column_info, dataset, *, schema=None
    ):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import compute_quality_score

        schema, _role = self._data_plane_target(schema)
        return await compute_quality_score(
            session, table_name, column_info, dataset, schema=schema
        )

    def quote_table(self, table_name, *, schema=None):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _qtable

        schema, _role = self._data_plane_target(schema)
        return _qtable(table_name, schema=schema)

    async def generate_table_name(self, title, session):  # type: ignore[no-untyped-def]
        from app.processing.ingest.service import generate_table_name

        return await generate_table_name(title, session)

    def validate_file_content(self, file_path, filename):  # type: ignore[no-untyped-def]
        from app.processing.ingest.validation import validate_file_content

        return validate_file_content(file_path, filename)

    def validate_file_extension(self, filename, allowed):  # type: ignore[no-untyped-def]
        from app.processing.ingest.service import validate_file_extension

        return validate_file_extension(filename, allowed)

    async def create_ingest_job(self, session, filename, file_path, user_id):  # type: ignore[no-untyped-def]
        from app.processing.ingest.service import create_ingest_job

        return await create_ingest_job(session, filename, file_path, user_id)

    async def save_upload_file(  # type: ignore[no-untyped-def]
        self, file, job_id, *, max_size_bytes=None
    ):
        from app.processing.ingest.service import save_upload_file

        return await save_upload_file(file, job_id, max_size_bytes=max_size_bytes)

    async def resolve_file_path(self, file_path, job_id):  # type: ignore[no-untyped-def]
        from app.processing.ingest.service import resolve_file_path

        return await resolve_file_path(file_path, job_id)

    async def run_ogrinfo_preview(self, file_path, *, layer_name=None, sample_limit=5):  # type: ignore[no-untyped-def]
        from app.processing.ingest.ogr import run_ogrinfo_preview

        return await run_ogrinfo_preview(
            file_path, layer_name=layer_name, sample_limit=sample_limit
        )

    def reupload_file_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import reupload_file

        return reupload_file

    def reupload_service_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import reupload_service

        return reupload_service

    def reupload_raster_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import reupload_raster

        return reupload_raster

    def refresh_postgis_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import refresh_postgis

        return refresh_postgis

    def refresh_stac_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import refresh_stac

        return refresh_stac

    def materialize_analysis_task(self):  # type: ignore[no-untyped-def]
        from app.processing.analysis.tasks import materialize_analysis

        return materialize_analysis

    def regenerate_vrt_task(self):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import regenerate_vrt

        return regenerate_vrt

    def ingest_part_size(self) -> int:
        # fix(#836): PART_SIZE moved off the router — platform code must never
        # import an API-edge module (route registration runs at import time).
        from app.processing.ingest.service import PART_SIZE

        return PART_SIZE

    def safe_content_disposition(self, filename):  # type: ignore[no-untyped-def]
        from app.processing.export.service import safe_content_disposition

        return safe_content_disposition(filename)

    def extract_srid_from_json(self, coordinate_system):  # type: ignore[no-untyped-def]
        from app.processing.ingest.ogr import extract_srid_from_json

        return extract_srid_from_json(coordinate_system)

    def resolve_service_type(self, raw):  # type: ignore[no-untyped-def]
        from app.processing.ingest.tasks import resolve_service_type

        return resolve_service_type(raw)

    def humanize_column_name(self, column_name):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _humanize_column_name

        return _humanize_column_name(column_name)

    def infer_units(self, column_name):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _infer_units

        return _infer_units(column_name)

    def infer_semantic_role(self, field_name, data_type):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _infer_semantic_role

        return _infer_semantic_role(field_name, data_type)

    def infer_domain_type(self, data_type):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _infer_domain_type

        return _infer_domain_type(data_type)

    def validate_table_name(self, table_name):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import _validate_table_name

        return _validate_table_name(table_name)

    async def add_4326_column(self, session, table_name, source_srid, *, schema=None):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import add_4326_column

        schema, _role = self._data_plane_target(schema)
        return await add_4326_column(session, table_name, source_srid, schema=schema)

    async def grant_reader_access(self, session, table_name, *, schema=None, role=None):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import grant_reader_access

        schema, role = self._data_plane_target(schema, role)
        return await grant_reader_access(session, table_name, schema=schema, role=role)

    async def get_column_info(self, session, table_name, *, schema=None):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import get_column_info

        schema, _role = self._data_plane_target(schema)
        return await get_column_info(session, table_name, schema=schema)

    async def generate_attribute_metadata(
        self,
        session,
        dataset_id,
        column_info,
        *,
        geometry_type=None,
        sample_values=None,
    ):  # type: ignore[no-untyped-def]
        from app.processing.ingest.metadata import generate_attribute_metadata

        return await generate_attribute_metadata(
            session,
            dataset_id,
            column_info,
            geometry_type=geometry_type,
            sample_values=sample_values,
        )

    async def has_embeddings(self, session):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.helpers import has_embeddings

        return await has_embeddings(session)

    async def resolve_embedding_config(self, session):  # type: ignore[no-untyped-def]
        # fix(#1546): semantic search filters stored rows on the fingerprint,
        # and `modules/catalog/` may not import `app.processing.*`. It gets the
        # whole (model, dimensions, endpoint, fingerprint) rather than the
        # fingerprint alone because it also has to PIN the provider call to the
        # same configuration it filters on (#1546 review r1).
        from app.processing.embeddings.helpers import resolve_live_embedding_config

        return await resolve_live_embedding_config(session)

    async def generate_embedding(self, text, session, *, pinned=None):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.service import generate_embeddings_batch

        # fix(#1546 review r1, codex P1): `pinned` is (model, dimensions,
        # endpoint) as ONE optional argument rather than three keyword ones.
        # `None` is a legitimate resolved endpoint — the provider interface
        # lets an extension answer `{"base_url": None}` meaning "use the client
        # default", which is why `generate_embeddings_batch` distinguishes it
        # from an omission with a sentinel (`_Unset`, #1525). Three defaults of
        # `None` could not tell "not pinned" from "pinned to the client
        # default", and would have re-resolved the endpoint for exactly the
        # providers the pin most needs to protect. One argument, absent or
        # complete, cannot express that mistake.
        if pinned is None:
            from app.processing.embeddings.service import generate_embedding

            return await generate_embedding(text, session)
        model, dimensions, base_url = pinned
        vectors = await generate_embeddings_batch(
            [text], session, model=model, dimensions=dimensions, base_url=base_url
        )
        return vectors[0]

    async def set_hnsw_recall(self, session):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.helpers import set_hnsw_recall

        return await set_hnsw_recall(session)

    async def get_record_embedding(self, session, record_id):  # type: ignore[no-untyped-def]
        # fix(#1580): returns the anchor row's identity with its vector. This
        # used to be a second, independent `LIMIT 1` off an unordered query: on
        # a catalog holding more than one model's rows the ranking and the
        # scoring could anchor on different vectors, and the caller had no way
        # to ask which space it was handed because a list of floats does not
        # say. fix(#1580 review r2): it is now the ONLY anchor read on this
        # path — the caller passes what this returns into
        # `get_nearest_record_ids`, so the ranking and the scoring share one
        # row rather than two statements that happen to order the same way.
        from app.processing.embeddings.helpers import get_anchor_embedding_row

        return await get_anchor_embedding_row(session, record_id)

    async def get_nearest_record_ids(  # type: ignore[no-untyped-def]
        self,
        session,
        record_id,
        *,
        anchor,
        limit=5,
        max_distance=0.7,
    ):
        # fix(#1580 review r2): the anchor travels in rather than being read
        # again here. The caller has already read it to score the results, and
        # two reads under READ COMMITTED can straddle a commit — leaving the
        # ranking anchored on one row and the scoring on another. Required
        # rather than optional on the PORT: the only core caller holds one, and
        # an overlay that re-read would reintroduce exactly the disagreement
        # this closes.
        from app.processing.embeddings.helpers import get_nearest_record_ids

        return await get_nearest_record_ids(
            session,
            record_id,
            anchor=anchor,
            limit=limit,
            max_distance=max_distance,
        )

    async def get_embedding_distances(  # type: ignore[no-untyped-def]
        self, session, embedding, record_ids, *, model_name, config_fingerprint
    ):
        # fix(#1580): scoped to the anchor's own vector space, like the
        # selection ahead of it. Fixing only `get_nearest_record_ids` would have
        # moved this defect one layer out rather than closing it: the neighbours
        # would be chosen correctly and then SCORED off whichever of their rows
        # the planner returned last, because a record may hold one row per model
        # and this dict comprehension keeps the last of them. The similarity
        # percentage the UI prints is this number.
        from sqlalchemy import select

        await self.set_hnsw_recall(session)
        RecordEmbedding = self.record_embedding_orm_class()
        result = await session.execute(
            select(
                RecordEmbedding.record_id,
                RecordEmbedding.embedding.cosine_distance(embedding).label("distance"),
            )
            .where(RecordEmbedding.record_id.in_(record_ids))
            .where(
                # fix(#1580 review r2): the stored-vs-stored predicate, the same
                # one the selection uses. `usable_by_config` grandfathers an
                # unstamped row against a stamped anchor, which is right for
                # search (a fresh query vector, and on upgrade day the unstamped
                # rows are all there is) and wrong here — a stamped anchor is
                # evidence of a partly regenerated catalog, and the rows still
                # carrying NULL are most likely the old space.
                RecordEmbedding.usable_by_stored_anchor(model_name, config_fingerprint)
            )
        )
        return {row.record_id: row.distance for row in result.all()}

    async def defer_embed_record(self, record_id):  # type: ignore[no-untyped-def]
        from app.processing.embeddings.tasks import embed_record

        await defer_async_with_tenant(embed_record, record_id=str(record_id))

    async def get_raster_asset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        RasterAsset = self.raster_asset_orm_class()
        result = await session.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset_id)
        )
        return result.scalar_one_or_none()

    async def list_raster_assets(self, session, dataset_ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        if not dataset_ids:
            return {}
        RasterAsset = self.raster_asset_orm_class()
        result = await session.execute(
            select(RasterAsset).where(RasterAsset.dataset_id.in_(dataset_ids))
        )
        return {asset.dataset_id: asset for asset in result.scalars().all()}

    async def get_dataset_assets(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        DatasetAsset = self.dataset_asset_orm_class()
        result = await session.execute(
            select(DatasetAsset).where(DatasetAsset.dataset_id == dataset_id)
        )
        return list(result.scalars().all())

    async def list_dataset_assets(self, session, dataset_ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        if not dataset_ids:
            return []
        DatasetAsset = self.dataset_asset_orm_class()
        result = await session.execute(
            select(DatasetAsset).where(DatasetAsset.dataset_id.in_(dataset_ids))
        )
        return list(result.scalars().all())

    async def fetch_raster_meta_one(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from app.processing.raster.queries import fetch_raster_meta_one

        return await fetch_raster_meta_one(session, dataset_id)

    async def fetch_raster_meta_bulk(self, session, dataset_ids):  # type: ignore[no-untyped-def]
        from app.processing.raster.queries import fetch_raster_meta_bulk

        return await fetch_raster_meta_bulk(session, dataset_ids)

    async def fetch_raster_meta_bulk_without_vrt(self, session, dataset_ids):  # type: ignore[no-untyped-def]
        from app.processing.raster.queries import fetch_raster_meta_bulk

        return await fetch_raster_meta_bulk(session, dataset_ids, include_vrt=False)

    async def get_vrt_generation_source_count(self, session, generation_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        VrtGeneration = self.vrt_generation_orm_class()
        result = await session.execute(
            select(VrtGeneration.source_count).where(VrtGeneration.id == generation_id)
        )
        return result.scalar_one_or_none()

    async def get_ingest_job_or_404(self, session, job_id, user):  # type: ignore[no-untyped-def]
        from app.processing.ingest.service import get_job_or_404

        return await get_job_or_404(session, job_id, user)

    # Tile signing (Phase 252 LAYERING-01)
    def generate_tile_signature(self, scope, exp):  # type: ignore[no-untyped-def]
        from app.processing.tiles.signing import generate_tile_signature

        return generate_tile_signature(scope, exp)

    def round_tile_expiry(self, ttl_seconds=900):  # type: ignore[no-untyped-def]
        from app.processing.tiles.signing import round_expiry

        return round_expiry(ttl_seconds)
