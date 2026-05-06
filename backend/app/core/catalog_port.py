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

    def visibility_default(self) -> str: ...

    async def compute_quality_score(
        self,
        session: AsyncSession,
        table_name: str,
        column_info: list[dict],
        dataset: Any,
    ) -> dict[str, Any]: ...

    def quote_table(self, table_name: str) -> str: ...

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

    async def save_upload_file(self, file: Any, job_id: str) -> Path | str: ...

    async def resolve_file_path(self, file_path: str, job_id: str) -> str: ...

    async def run_ogrinfo_preview(
        self, file_path: str, *, layer_name: str | None = None, sample_limit: int = 5
    ) -> dict[str, Any]: ...

    def reupload_file_task(self) -> Any: ...

    def reupload_service_task(self) -> Any: ...

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
        self, session: AsyncSession, table_name: str, source_srid: int
    ) -> None: ...

    async def grant_reader_access(
        self, session: AsyncSession, table_name: str
    ) -> None: ...

    async def get_column_info(
        self, session: AsyncSession, table_name: str
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

    async def get_vrt_generation_source_count(
        self, session: AsyncSession, generation_id: uuid.UUID
    ) -> int | None: ...

    async def get_ingest_job_or_404(
        self, session: AsyncSession, job_id: uuid.UUID, user: Any
    ) -> Any: ...

    # Tile signing (Phase 252 LAYERING-01)
    def generate_tile_signature(self, scope: str, exp: int) -> str: ...

    def round_tile_expiry(self, ttl_seconds: int = 900) -> int: ...
