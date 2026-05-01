"""Dataset lifecycle operations: delete + version history (extracted from service.py — Phase 224)."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger(__name__)


__all__ = [
    "DependentVrtError",
    "delete_dataset",
    "get_dataset_versions",
]


_SAFE_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _safe_table_ref(table_name: str) -> str:
    """Return a safely quoted 'data.table_name' SQL identifier.

    Validates that the name contains only safe characters and quotes it
    to prevent SQL injection in DDL statements (CREATE/DROP/ALTER).
    """
    if not _SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    return f'"data"."{table_name}"'


class DependentVrtError(Exception):
    """Raised when attempting to delete a COG referenced by VRT datasets."""

    def __init__(self, dependents: list[dict]) -> None:
        self.dependents = dependents
        names = ", ".join(d["vrt_dataset_title"] for d in dependents)
        super().__init__(
            f"Cannot delete: this dataset is used as a source in "
            f"{len(dependents)} virtual raster(s): {names}"
        )


async def delete_dataset(
    session: AsyncSession, dataset_id: uuid.UUID, confirm_title: str
) -> str:
    """Delete a dataset: drop data table (vector) or clean storage artifacts (raster).

    Deleting the record cascades to the dataset via FK.
    Returns the table_name for logging. Does NOT commit.
    Raises ValueError if dataset not found, name mismatch, or invalid table name.
    For raster datasets, storage cleanup happens before DB deletion so that a
    storage failure prevents any DB changes (no orphaned records).
    """
    # Function-local import to avoid circular dependency: service.py re-exports
    # delete_dataset from this module, so we cannot import get_dataset at module
    # top. Same pattern as service_metadata.py (224-03) and service_relationships.py (224-02).
    from app.modules.catalog.datasets.domain.service import get_dataset

    dataset = await get_dataset(session, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")

    if dataset.record.title != confirm_title:
        raise ValueError("Dataset title does not match confirmation")

    table_name = dataset.table_name
    if not re.match(r"^[a-z0-9_]+$", table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    record_type = dataset.record.record_type

    if record_type in ("raster_dataset", "vrt_dataset"):
        from app.platform.storage.provider import get_storage

        if record_type == "raster_dataset":
            # Guard: prevent deletion if any VRT still references this COG
            refs_result = await session.execute(
                text(
                    """
                    SELECT d.id, r.title
                    FROM catalog.vrt_source_links vsl
                    JOIN catalog.datasets d ON d.id = vsl.vrt_dataset_id
                    JOIN catalog.records r ON r.id = d.record_id
                    WHERE vsl.source_dataset_id = :dataset_id
                    """
                ).bindparams(dataset_id=dataset_id)
            )
            refs = refs_result.all()
            if refs:
                raise DependentVrtError(
                    [
                        {"vrt_dataset_id": str(row.id), "vrt_dataset_title": row.title}
                        for row in refs
                    ]
                )
            # COG: clean both rasters/ and originals/ storage prefixes
            prefixes = [f"rasters/{dataset_id}/", f"originals/{dataset_id}/"]
        else:
            # VRT: only rasters/ prefix (no originals -- VRTs are generated, not uploaded)
            # vrt_source_links cascade-deleted via ON DELETE CASCADE on vrt_dataset_id FK
            prefixes = [f"rasters/{dataset_id}/"]

        # Clean up managed storage artifacts before touching the DB.
        # If any storage delete fails the exception propagates and the
        # caller's transaction rolls back, leaving the DB record intact.
        storage = get_storage()
        for prefix in prefixes:
            keys = await storage.list(prefix)
            if keys:
                await asyncio.gather(*(storage.delete(key) for key in keys))
    else:
        # Vector datasets: drop the PostGIS data table
        await session.execute(
            text(f"DROP TABLE IF EXISTS {_safe_table_ref(table_name)}")
        )

    # Delete the record (CASCADE handles dataset deletion)
    await session.delete(dataset.record)

    return table_name


async def get_dataset_versions(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """List version history for a dataset, ordered by version_number desc.

    Returns a tuple of (versions, total_count).
    """
    from app.modules.catalog.collections.models import DatasetVersion

    base_stmt = select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id)

    # Get total count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = await session.execute(count_stmt)
    total_count = total.scalar_one()

    # Get paginated results
    paginated_stmt = (
        base_stmt.order_by(DatasetVersion.version_number.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(paginated_stmt)
    versions = list(result.scalars().all())

    return versions, total_count
