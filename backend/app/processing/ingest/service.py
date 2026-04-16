"""Ingestion orchestration service.

Handles file saving, validation, table name generation, job creation,
and table registration for existing PostGIS tables.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.visibility import get_user_roles
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import create_dataset
from app.processing.ingest.metadata import (
    add_4326_column,
    extract_metadata,
    get_sample_values,
    get_table_srid,
    grant_reader_access,
)
from app.processing.ingest.schemas import DiscoveredTable, RegisterRequest, VrtCreateRequest
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob


async def discover_unregistered_tables(
    session: AsyncSession, limit: int = 1000
) -> list[DiscoveredTable]:
    """Find tables in the data schema not yet registered in catalog.datasets.

    Excludes staging tables, old tables, and spatial_ref_sys. Returns
    typed ``DiscoveredTable`` instances (TYPE-7). Bounded by ``limit`` to
    protect instances with thousands of unregistered tables (PERF-11).
    """
    result = await session.execute(
        text(
            """
            SELECT
                t.table_name,
                gc.type AS geometry_type,
                gc.srid,
                c.reltuples::bigint AS estimated_rows
            FROM information_schema.tables t
            LEFT JOIN catalog.datasets d ON d.table_name = t.table_name
            LEFT JOIN geometry_columns gc
                ON gc.f_table_schema = 'data'
                AND gc.f_table_name = t.table_name
                AND gc.f_geometry_column = 'geom'
            LEFT JOIN pg_catalog.pg_class c
                ON c.relname = t.table_name
                AND c.relnamespace = (
                    SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = 'data'
                )
            WHERE t.table_schema = 'data'
                AND t.table_type = 'BASE TABLE'
                AND d.table_name IS NULL
                AND t.table_name NOT LIKE '%\\_staging' ESCAPE '\\'
                AND t.table_name NOT LIKE '%\\_old' ESCAPE '\\'
                AND t.table_name != 'spatial_ref_sys'
            ORDER BY t.table_name
            LIMIT :limit
            """
        ).bindparams(limit=limit)
    )
    return [DiscoveredTable(**dict(row)) for row in result.mappings().all()]


async def get_job_or_404(db: AsyncSession, job_id: uuid.UUID, user: User) -> IngestJob:
    """Load an IngestJob, checking existence and ownership/admin role.

    Raises:
        HTTPException 404: Job not found.
        HTTPException 403: User is not the job creator and is not an admin.
    """
    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Authorization: only creator or admin
    if job.created_by != user.id:
        user_roles = await get_user_roles(db, user)
        if "admin" not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this job",
            )

    return job


async def save_upload_file(file: UploadFile, job_id: str) -> Path | str:
    """Save an uploaded file to staging (local) or S3.

    In S3 mode, uploads directly to S3 and returns the S3 key string.
    In local mode, uses chunked writes (8192 bytes) and returns a Path.

    Callers MUST validate `file.filename` is non-empty before calling —
    raising on a missing filename is the route handler's responsibility so
    the error surfaces as HTTP 400, not an internal TypeError (TYPE-6).
    """
    if not file.filename:
        raise ValueError("Upload missing filename")

    if settings.storage_provider == "s3":
        from app.platform.storage import get_storage

        storage = get_storage()
        safe_name = Path(file.filename).name  # strip path traversal
        s3_key = f"staging/{job_id}/{safe_name}"
        await storage.put(s3_key, file.file)
        return s3_key

    staging_dir = Path(settings.upload_staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name  # strip path traversal
    dest = staging_dir / f"{job_id}_{safe_name}"
    with open(dest, "wb") as f:
        while chunk := await file.read(8192):
            f.write(chunk)

    return dest


async def resolve_file_path(file_path: str, job_id: str | None = None) -> str:
    """Resolve a file path that may be an S3 key to a local file path.

    If the file exists locally, returns as-is. If not (presigned S3 upload),
    downloads from S3 to a local temp path and returns that path.
    """
    if Path(file_path).exists():
        return file_path

    # File was uploaded directly to S3 via presigned URL
    from app.platform.storage import get_storage

    storage = get_storage()
    local_name = f"{job_id}_{Path(file_path).name}" if job_id else Path(file_path).name
    local_path = Path(settings.upload_staging_dir) / local_name
    await storage.get_to_file(file_path, local_path)
    return str(local_path)


def validate_file_extension(
    filename: str, allowed_list: list[str] | None = None
) -> None:
    """Validate that the filename has an allowed extension.

    Raises ValueError if the extension is not in the allowed list.
    When allowed_list is provided, uses it; otherwise falls back to
    settings.allowed_extensions_list.
    """
    exts = (
        allowed_list if allowed_list is not None else settings.allowed_extensions_list
    )
    suffix = Path(filename).suffix.lower()
    if suffix not in exts:
        raise ValueError(f"File extension {suffix!r} not allowed. Allowed: {exts}")


async def generate_table_name(
    name: str, session: AsyncSession
) -> tuple[str, str | None]:
    """Generate a human-readable PostGIS table name from a dataset name.

    Returns:
        (table_name, collision_warning) — collision_warning is None when no
        collision occurred, or a human-readable message like
        "Table name 'x' already exists, using 'x_2'" when a suffix was applied.

    Rules:
    - Lowercase, underscores as separators
    - Unicode transliterated to ASCII (e.g., strassen from Straßen)
    - Truncated to 60 chars (PG limit is 63; leaves room for _N suffix)
    - Names starting with digit get underscore prefix
    - Collision handling: _2, _3, _4, ...
    """
    from slugify import slugify as _slugify

    slug = _slugify(name, separator="_", max_length=60, lowercase=True)

    # Handle empty slug (all special characters / emojis)
    if not slug:
        slug = "dataset"

    # Prefix underscore if starts with digit
    if slug[0].isdigit():
        slug = f"_{slug}"
        # Re-truncate if prefix pushed past 60
        slug = slug[:60]

    # Check for collision against catalog
    base_slug = slug
    suffix = 1
    collision_warning: str | None = None
    while True:
        result = await session.execute(
            select(Dataset.id).where(Dataset.table_name == slug)
        )
        if result.scalar_one_or_none() is None:
            break
        suffix += 1
        slug = f"{base_slug}_{suffix}"

    if suffix > 1:
        collision_warning = f"Table name '{base_slug}' already exists, using '{slug}'"

    return slug, collision_warning


async def create_ingest_job(
    session: AsyncSession,
    filename: str,
    file_path: str,
    user_id: uuid.UUID,
) -> IngestJob:
    """Create and persist an IngestJob record with status='pending'."""
    job = IngestJob(
        source_filename=filename,
        file_path=file_path,
        created_by=user_id,
        status="pending",
    )
    session.add(job)
    await session.flush()
    return job


async def register_existing_table(
    session: AsyncSession,
    request: RegisterRequest,
    user: User,
) -> "Dataset":
    """Register an existing data-schema table into the dataset catalog.

    Verifies the table exists, checks for duplicate registration,
    ensures geom_4326 column and reader access, extracts metadata,
    and creates a Dataset record.
    """
    table_name = request.table_name

    # Validate table name to prevent SQL injection
    if not re.match(r"^[a-z0-9_]+$", table_name):
        raise ValueError(
            f"Invalid table name: {table_name!r}. "
            "Must contain only lowercase letters, digits, and underscores."
        )

    # Verify table exists in data schema
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'data' AND table_name = :table_name"
            ")"
        ).bindparams(table_name=table_name)
    )
    if not result.scalar():
        raise ValueError(f"Table 'data.{table_name}' does not exist.")

    # Check for duplicate registration
    from app.modules.catalog.datasets.domain.models import Dataset

    from sqlalchemy import select

    existing = await session.execute(
        select(Dataset).where(Dataset.table_name == table_name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"Table '{table_name}' is already registered as a dataset.")

    # Check for geometry columns
    geom_result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :table_name "
            "AND column_name IN ('geom', 'geom_4326')"
        ).bindparams(table_name=table_name)
    )
    geom_cols = {row[0] for row in geom_result.all()}

    has_geom = "geom" in geom_cols
    has_4326 = "geom_4326" in geom_cols

    metadata = {}
    if has_geom:
        if not has_4326:
            srid = await get_table_srid(session, table_name)
            # Wrap in savepoint so a partial failure (column added but
            # index creation fails) rolls back cleanly instead of leaving
            # the table in a half-indexed state (R-8).
            try:
                async with session.begin_nested():
                    await add_4326_column(session, table_name, srid or 4326)
            except Exception as exc:
                raise ValueError(
                    f"Failed to add geom_4326 column to '{table_name}': {exc}"
                ) from exc

        await grant_reader_access(session, table_name)
        metadata = await extract_metadata(session, table_name)
    else:
        # Non-spatial table -- grant access but skip spatial metadata
        await grant_reader_access(session, table_name)

    # Extract sample values for attribute metadata example_values
    col_info = metadata.get("column_info", [])
    sample_vals = (
        await get_sample_values(session, table_name, col_info) if col_info else None
    )

    dataset = await create_dataset(
        session,
        table_name=table_name,
        title=request.title,
        created_by=user.id,
        summary=request.summary,
        srid=metadata.get("srid"),
        geometry_type=metadata.get("geometry_type"),
        feature_count=metadata.get("feature_count"),
        extent_wkt=metadata.get("extent_wkt"),
        column_info=col_info,
        sample_values=sample_vals,
        visibility=request.visibility,
    )

    return dataset


async def create_vrt_job(
    db: AsyncSession,
    request: VrtCreateRequest,
    user: User,
) -> IngestJob:
    """Validate source raster datasets, then create + defer a VRT creation job.

    K5/KISS-10 extraction: this was inline in ``router.create_vrt``. Moving it
    here keeps the router handler to "receive request, call service, return
    response" and gives the logic a place to be unit-tested without spinning
    up FastAPI.

    Raises:
        HTTPException 422: Fewer than 2 sources, a source was not found or
            is not a raster dataset, or source compatibility validation
            failed (mismatched CRS, band counts, etc.).
    """
    import json

    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.ingest.tasks import ingest_vrt
    from app.processing.raster.models import RasterAsset
    from app.processing.raster.validation import validate_sources

    # 1. Validate minimum source count
    if len(request.source_dataset_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least 2 source datasets are required to create a VRT",
        )

    # 2. Load RasterAsset rows for each source dataset
    result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(
            Dataset.id.in_(request.source_dataset_ids),
            Record.record_type == "raster_dataset",
        )
    )
    found_assets = result.scalars().all()

    # 3. Check all requested IDs were found and are raster_datasets
    found_dataset_ids = {asset.dataset_id for asset in found_assets}
    for sid in request.source_dataset_ids:
        if sid not in found_dataset_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Source dataset {sid} not found or not a raster dataset",
            )

    # 4. Validate source compatibility
    errors = validate_sources(request.vrt_type, list(found_assets))
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[e.model_dump() for e in errors],
        )

    # 5. Create IngestJob
    job = await create_ingest_job(db, f"vrt_{request.vrt_type}", "", user.id)
    job.user_metadata = {
        "vrt_type": request.vrt_type,
        "title": request.title,
        "summary": request.summary,
        "visibility": request.visibility,
    }
    await db.commit()

    # 6. Defer async VRT assembly task.
    # If Procrastinate is unreachable, the job row was already committed
    # as ``pending`` above — the orphan guard flips it to ``failed``
    # before propagating so stale-cleanup and /jobs listings reflect the
    # real state instead of waiting 60 minutes for PENDING_TIMEOUT
    # (RESILIENCE-2).
    async def _defer_vrt() -> None:
        await ingest_vrt.defer_async(
            job_id=str(job.id),
            user_id=str(user.id),
            source_dataset_ids=json.dumps(
                [str(sid) for sid in request.source_dataset_ids]
            ),
            vrt_type=request.vrt_type,
            resolution_strategy=request.resolution_strategy,
        )

    await defer_with_orphan_guard(
        _defer_vrt,
        rollback=make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue VRT task"
        ),
        db=db,
    )

    return job


async def queue_ingest_job(
    job: IngestJob,
    user_id: str,
    *,
    db: AsyncSession,
    token: str | None = None,
) -> None:
    """Route a committed ingest job to the right Procrastinate task.

    Extracts the routing decision tree from ``router.commit_import``
    (KISS-9). Chooses between `ingest_service` (source_url set),
    `ingest_raster` (file_type=raster), and `ingest_file` (default
    vector path), and sends small vector files to the priority queue.

    Each ``defer_async`` call is wrapped in ``defer_with_orphan_guard``
    (from ``app.jobs.defer_guard``) so a queue outage flips the committed
    pending job to ``failed`` and surfaces HTTP 503, matching the
    RESILIENCE-2 fix in ``create_vrt_job`` (Theme H in
    ``post-impl-20260410-HANDOFF-REMAINING.md``).

    Raises ``HTTPException 400`` when the job has no file_path and no
    source_url so the route handler surfaces a clear error.
    Raises ``HTTPException 503`` when Procrastinate is unreachable.
    """
    import os

    from app.processing.ingest.constants import PRIORITY_QUEUE_THRESHOLD_BYTES
    from app.processing.ingest.tasks import ingest_file, ingest_raster, ingest_service

    if job.source_url and not job.file_path:
        # Service job — route to ingest_service. Capture source_url into
        # a local so mypy preserves the ``str`` narrowing inside the
        # nested closure (the attribute access reverts to ``str | None``).
        source_url = job.source_url

        async def _defer_service() -> None:
            await ingest_service.defer_async(
                job_id=str(job.id),
                source_url=source_url,
                source_layer=job.source_layer or "",
                user_id=user_id,
                token=token,
            )

        await defer_with_orphan_guard(
            _defer_service,
            rollback=make_ingest_job_failed_rollback(job),
            db=db,
        )
        return

    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no file_path and no source_url — cannot queue ingest",
        )
    file_path = job.file_path

    if (job.user_metadata or {}).get("file_type") == "raster":
        # Raster file job — route to dedicated raster queue
        async def _defer_raster() -> None:
            await ingest_raster.defer_async(
                job_id=str(job.id),
                file_path=file_path,
                user_id=user_id,
            )

        await defer_with_orphan_guard(
            _defer_raster,
            rollback=make_ingest_job_failed_rollback(job),
            db=db,
        )
        return

    # Vector file — route small files to the priority queue.
    file_size = 0
    if file_path.startswith("/"):
        try:
            if Path(file_path).exists():
                file_size = os.path.getsize(file_path)
        except OSError:
            pass  # If we can't stat, use default queue

    if 0 < file_size <= PRIORITY_QUEUE_THRESHOLD_BYTES:

        async def _defer_priority() -> None:
            await ingest_file.configure(queue="priority").defer_async(
                job_id=str(job.id),
                file_path=file_path,
                user_id=user_id,
            )

        await defer_with_orphan_guard(
            _defer_priority,
            rollback=make_ingest_job_failed_rollback(job),
            db=db,
        )
    else:

        async def _defer_default() -> None:
            await ingest_file.defer_async(
                job_id=str(job.id),
                file_path=file_path,
                user_id=user_id,
            )

        await defer_with_orphan_guard(
            _defer_default,
            rollback=make_ingest_job_failed_rollback(job),
            db=db,
        )
