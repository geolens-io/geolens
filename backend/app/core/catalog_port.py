"""Cross-domain processing access contract for catalog modules.

Defines the Protocol catalog/* uses when it needs processing-owned helpers,
schemas, task dispatchers, or ORM classes. The concrete implementation lives in
platform/extensions/defaults.py and imports app.processing.* lazily inside
method bodies so catalog modules do not carry module-level processing imports.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class CatalogPort(Protocol):
    """Processing-owned surface consumed by backend/app/modules/catalog/*."""

    @property
    def priority_queue_threshold_bytes(self) -> int: ...

    def ingestion_error_class(self) -> type[Exception]: ...

    def raster_asset_orm_class(self) -> Any: ...

    def dataset_asset_orm_class(self) -> Any: ...

    def vrt_generation_orm_class(self) -> Any: ...

    def record_embedding_orm_class(self) -> Any: ...

    def embedding_unavailable_error_class(self) -> type[Exception]: ...

    def vrt_mutation_response_model(self) -> Any: ...

    def presigned_complete_request_model(self) -> Any: ...

    def presigned_upload_request_model(self) -> Any: ...

    def presigned_upload_response_model(self) -> Any: ...

    def upload_response_model(self) -> Any: ...

    async def abort_presigned_multipart_upload(
        self,
        storage: Any,
        *,
        key: str,
        upload_id: Any,
        job_id: uuid.UUID,
    ) -> None: ...

    # Here and on `finalize_presigned_object`, `user_id` is the dataset OWNER
    # when the flow is a replacement and the uploader when it is a creation, so
    # it is nullable: an ownerless dataset has no owner to name (#1293 — the
    # policy is stated in app.modules.quota.service).
    async def verify_completed_presigned_upload(
        self,
        *,
        db: AsyncSession,
        storage: Any,
        key: str,
        expected_size: Any,
        user_id: uuid.UUID | None,
        request: Any,
        job_id: uuid.UUID,
    ) -> int: ...

    # fix(#1207): the presigned completion contract, shared by both doors.
    # `finalize_presigned_object` owns freeze/verify/validate and every
    # cleanup decision; see its docstring for the failure postconditions.
    async def lock_presigned_job(self, db: AsyncSession, job_id: uuid.UUID) -> Any: ...

    async def should_assemble_multipart(
        self, storage: Any, um: dict, physical_key: str
    ) -> bool: ...

    def require_completable_presigned_job(
        self, job: Any, *, restart_hint: str
    ) -> None: ...

    def require_signable_job_lifetime(self, created_at: Any) -> int: ...

    def sign_url_with_deadline(
        self, storage_method: Any, created_at: Any, *args: Any
    ) -> str: ...

    async def finalize_presigned_object(
        self,
        *,
        db: AsyncSession,
        storage: Any,
        job_id: uuid.UUID,
        logical_key: str,
        expected_size: Any,
        filename: str,
        user_id: uuid.UUID | None,
        request: Any,
    ) -> str: ...

    def visibility_default(self) -> str: ...

    async def compute_quality_score(
        self,
        session: AsyncSession,
        table_name: str,
        column_info: list[dict],
        dataset: Any,
        *,
        schema: str | None = None,
    ) -> dict[str, Any]: ...

    def quote_table(self, table_name: str, *, schema: str | None = None) -> str: ...

    async def generate_table_name(
        self, title: str, session: AsyncSession
    ) -> tuple[str, str | None]: ...

    def validate_file_content(self, file_path: str, filename: str) -> None: ...

    def validate_file_extension(
        self, filename: str | None, allowed: list[str]
    ) -> None: ...

    async def create_ingest_job(
        self,
        session: AsyncSession,
        filename: str | None,
        file_path: str,
        user_id: uuid.UUID,
    ) -> Any: ...

    async def save_upload_file(
        self,
        file: Any,
        job_id: str,
        *,
        max_size_bytes: int | None = None,
    ) -> Path | str: ...

    async def resolve_file_path(self, file_path: str, job_id: str) -> str: ...

    async def run_ogrinfo_preview(
        self, file_path: str, *, layer_name: str | None = None, sample_limit: int = 5
    ) -> dict[str, Any]: ...

    def reupload_file_task(self) -> Any: ...

    def reupload_service_task(self) -> Any: ...

    def reupload_raster_task(self) -> Any: ...

    def refresh_postgis_task(self) -> Any: ...

    def refresh_stac_task(self) -> Any: ...

    def regenerate_vrt_task(self) -> Any: ...

    def ingest_part_size(self) -> int: ...

    def safe_content_disposition(self, filename: str) -> str: ...

    def extract_srid_from_json(
        self, coordinate_system: dict[str, Any]
    ) -> int | None: ...

    def resolve_service_type(self, raw: str) -> tuple[str, str]: ...

    def humanize_column_name(self, column_name: str) -> str: ...

    def infer_units(self, column_name: str) -> str | None: ...

    def infer_semantic_role(self, field_name: str, data_type: str) -> str: ...

    def infer_domain_type(self, data_type: str) -> str | None: ...

    def validate_table_name(self, table_name: str) -> None: ...

    async def add_4326_column(
        self,
        session: AsyncSession,
        table_name: str,
        source_srid: int,
        *,
        schema: str | None = None,
    ) -> None: ...

    async def grant_reader_access(
        self,
        session: AsyncSession,
        table_name: str,
        *,
        schema: str | None = None,
        role: str | None = None,
    ) -> None: ...

    async def get_column_info(
        self,
        session: AsyncSession,
        table_name: str,
        *,
        schema: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def generate_attribute_metadata(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        column_info: list[dict[str, Any]],
        *,
        geometry_type: str | None = None,
        sample_values: dict[str, Any] | None = None,
    ) -> None: ...

    async def has_embeddings(self, session: AsyncSession) -> bool: ...

    async def resolve_embedding_config_fingerprint(
        self,
        session: AsyncSession,
        *,
        model_name: str | None = None,
    ) -> str: ...

    async def generate_embedding(
        self, text: str, session: AsyncSession
    ) -> list[float]: ...

    async def set_hnsw_recall(self, session: AsyncSession) -> None: ...

    async def get_record_embedding(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> list[float] | None: ...

    async def get_nearest_record_ids(
        self,
        session: AsyncSession,
        record_id: uuid.UUID,
        *,
        limit: int = 5,
        max_distance: float = 0.7,
    ) -> list[uuid.UUID]: ...

    async def get_embedding_distances(
        self,
        session: AsyncSession,
        embedding: list[float],
        record_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]: ...

    async def defer_embed_record(self, record_id: uuid.UUID) -> None: ...

    async def get_raster_asset(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> Any | None: ...

    async def list_raster_assets(
        self, session: AsyncSession, dataset_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Any]: ...

    async def get_dataset_assets(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> list[Any]: ...

    async def list_dataset_assets(
        self, session: AsyncSession, dataset_ids: list[uuid.UUID]
    ) -> list[Any]: ...

    async def fetch_raster_meta_one(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> dict[str, Any] | None: ...

    async def fetch_raster_meta_bulk(
        self, session: AsyncSession, dataset_ids: list[uuid.UUID]
    ) -> dict[str, dict[str, Any]]: ...

    # The same rows without the VRT assembly fields. `vrt_type` is forwarded to
    # a record's properties when present (search/service_records.py), and the
    # STAC item surface must not grow that property — so its reader asks for
    # the narrower answer rather than trimming the wider one.
    #
    # REQUIRED, which is why EXTENSION_API_VERSION went 5 -> 6: every STAC
    # item and item-page response calls it, so an overlay that replaces the
    # `catalog_port` slot without it serves AttributeError instead of a page.
    # A separate method rather than an `include_vrt` keyword on the call above
    # because widening an existing port method's signature is a bump under the
    # same rule (the 2 -> 3 entry), and this shape keeps the wider reading
    # working unchanged for the callers that need `vrt_type`.
    async def fetch_raster_meta_bulk_without_vrt(
        self, session: AsyncSession, dataset_ids: list[uuid.UUID]
    ) -> dict[str, dict[str, Any]]: ...

    # How many members ONE generation is assembling. fix(#1327): that is the
    # attempt's intended set, which for a source add/remove is not what the VRT
    # is serving until the attempt publishes — so this is a fact about the
    # generation and must not be projected as a dataset's `source_count`. Count
    # `catalog.vrt_source_links` for that, as every catalog surface now does.
    async def get_vrt_generation_source_count(
        self, session: AsyncSession, generation_id: uuid.UUID
    ) -> int | None: ...

    async def get_ingest_job_or_404(
        self, session: AsyncSession, job_id: uuid.UUID, user: Any
    ) -> Any: ...

    # Tile signing (Phase 252 LAYERING-01)
    def generate_tile_signature(self, scope: str, exp: int) -> str: ...

    def round_tile_expiry(self, ttl_seconds: int = 900) -> int: ...
