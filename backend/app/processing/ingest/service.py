"""Ingestion orchestration service.

Handles file saving, validation, table name generation, job creation,
and table registration for existing PostGIS tables.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.platform.extensions import get_processing_port
from app.processing.ingest.metadata import (
    add_4326_column,
    extract_metadata,
    get_sample_values,
    get_table_srid,
    grant_reader_access,
)
from app.processing.ingest.schemas import (
    DiscoveredTable,
    RegisterRequest,
    VrtCreateRequest,
)
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob

# Spool threshold for S3 uploads (PERF-001): SpooledTemporaryFile buffers this
# many bytes in memory before spilling to a real temp file on disk.  16 MiB is
# a reasonable balance — small files stay fully in RAM while large uploads
# (e.g. a 200 MB GeoTIFF) do not consume hundreds of MB of heap per concurrent
# request.
_UPLOAD_SPOOL_MAX_BYTES: int = 16 * 1024 * 1024  # 16 MiB


async def discover_unregistered_tables(
    session: AsyncSession, limit: int = 1000
) -> list[DiscoveredTable]:
    """Find tables in the data schema not yet registered in catalog.datasets.

    Excludes staging tables, old tables, and spatial_ref_sys. Returns
    typed ``DiscoveredTable`` instances (TYPE-7). Bounded by ``limit`` to
    protect instances with thousands of unregistered tables (PERF-11).

    In single_tenant: searches the shared ``data`` schema (unchanged behavior).
    In multi_tenant: searches the per-tenant ``data_t_{tid}`` schema derived
    from ``current_tenant_var`` so cross-tenant tables are never returned
    (T-1209-08: discover must not leak other-tenant tables).
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tid = current_tenant_var.get()
    schema = tenant_data_schema(tid)

    # IN-01 (Phase 1209-CR): in multi_tenant, bind the LEFT JOIN exclusion to
    # the active tenant so a table registered by tenant A does not suppress
    # discovery for tenant B when both tenants share the same table_name.
    # single_tenant: tid is None and the tenant_id filter must not apply
    # (catalog.datasets may have no tenant_id column before the multi_tenant
    # migration is applied).
    if is_multi_tenant() and tid is not None:
        tenant_join_clause = "AND d.tenant_id = :tenant_id"
        bind_params = dict(schema=schema, limit=limit, tenant_id=tid)
    else:
        tenant_join_clause = ""
        bind_params = dict(schema=schema, limit=limit)

    result = await session.execute(
        text(
            f"""
            SELECT
                t.table_name,
                gc.type AS geometry_type,
                gc.srid,
                c.reltuples::bigint AS estimated_rows
            FROM information_schema.tables t
            LEFT JOIN catalog.datasets d ON d.table_name = t.table_name
                {tenant_join_clause}
            LEFT JOIN geometry_columns gc
                ON gc.f_table_schema = :schema
                AND gc.f_table_name = t.table_name
                AND gc.f_geometry_column = 'geom'
            LEFT JOIN pg_catalog.pg_class c
                ON c.relname = t.table_name
                AND c.relnamespace = (
                    SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = :schema
                )
            WHERE t.table_schema = :schema
                AND t.table_type = 'BASE TABLE'
                AND d.table_name IS NULL
                AND t.table_name NOT LIKE '%\\_staging' ESCAPE '\\'
                AND t.table_name NOT LIKE '%\\_old' ESCAPE '\\'
                AND t.table_name != 'spatial_ref_sys'
            ORDER BY t.table_name
            LIMIT :limit
            """
        ).bindparams(**bind_params)
    )
    return [DiscoveredTable(**dict(row)) for row in result.mappings().all()]


async def get_job_or_404(
    db: AsyncSession, job_id: uuid.UUID, user: Identity
) -> IngestJob:
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
        port = get_processing_port()
        user_roles = await port.get_user_roles(db, user)
        if "admin" not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this job",
            )

    return job


async def save_upload_file(
    file: UploadFile,
    job_id: str,
    max_size_bytes: int | None = None,
) -> Path | str:
    """Save an uploaded file to staging (local) or S3.

    In S3 mode with ``max_size_bytes`` set, streams chunks into a
    ``tempfile.SpooledTemporaryFile`` (threshold ``_UPLOAD_SPOOL_MAX_BYTES``).
    Small files stay in memory; large files spill to disk so heap usage is
    bounded regardless of upload size (PERF-001).  Without ``max_size_bytes``,
    the raw ``file.file`` handle is streamed directly to S3.  Returns the S3
    key string in both cases.

    In local mode, reads chunks asynchronously (64 KiB) and writes via
    ``run_in_executor`` so synchronous file I/O does not block the event
    loop.  On write failure the partial file is removed before the
    exception propagates.

    Callers MUST validate `file.filename` is non-empty before calling —
    raising on a missing filename is the route handler's responsibility so
    the error surfaces as HTTP 400, not an internal TypeError (TYPE-6).

    IA-P0-02 (Phase 1066): when ``max_size_bytes`` is provided, the chunk
    loop accumulates bytes and raises ``HTTPException(413)`` as soon as the
    cumulative byte count exceeds the limit, BEFORE the upload completes —
    closing asymmetry with the presigned path which checks ``file_size`` at
    request time (``router.py:158-165``). The presigned path uses 422
    because the Pydantic schema validates ``file_size`` declaratively; the
    multipart path uses 413 (Payload Too Large) because the limit is hit
    while streaming and 413 matches reverse-proxy semantics.

    Partial files in local mode are cleaned up via the existing
    ``except: os.unlink`` block; the 413 raise hits that path naturally.
    """
    if not file.filename:
        raise ValueError("Upload missing filename")

    if settings.storage_provider == "s3":
        from app.platform.storage import get_storage

        storage = get_storage()
        safe_name = Path(file.filename).name  # strip path traversal
        s3_key = f"staging/{job_id}/{safe_name}"
        if max_size_bytes is not None:
            # Stream-and-accumulate with a SpooledTemporaryFile so S3 mode
            # enforces the same size limit as local mode without holding the
            # entire upload in memory.  SpooledTemporaryFile buffers up to
            # _UPLOAD_SPOOL_MAX_BYTES in RAM; once that threshold is exceeded
            # it spills to a real temp file on disk, bounding heap usage to the
            # spool threshold regardless of upload size (PERF-001).
            #
            # The per-chunk 413 check fires BEFORE the chunk is written so
            # over-limit uploads are rejected mid-stream, matching the existing
            # local-mode and presigned-URL behavior.  The try/finally ensures
            # the temp file is closed (and therefore deleted, since
            # delete=True is the default) on both the success path and the
            # 413 raise path.
            total = 0
            spooled = tempfile.SpooledTemporaryFile(max_size=_UPLOAD_SPOOL_MAX_BYTES)
            try:
                while chunk := await file.read(65536):
                    total += len(chunk)
                    if total > max_size_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=(
                                f"File size exceeds maximum allowed "
                                f"({max_size_bytes / (1024 * 1024):.1f} MB)."
                            ),
                        )
                    spooled.write(chunk)
                spooled.seek(0)
                await storage.put(s3_key, spooled)
            finally:
                spooled.close()
        else:
            await storage.put(s3_key, file.file)
        return s3_key

    staging_dir = Path(settings.upload_staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name  # strip path traversal
    dest = staging_dir / f"{job_id}_{safe_name}"

    loop = asyncio.get_event_loop()
    total = 0
    try:
        f = await loop.run_in_executor(None, open, dest, "wb")
        try:
            while chunk := await file.read(65536):
                if max_size_bytes is not None:
                    total += len(chunk)
                    if total > max_size_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=(
                                f"File size exceeds maximum allowed "
                                f"({max_size_bytes / (1024 * 1024):.1f} MB)."
                            ),
                        )
                await loop.run_in_executor(None, f.write, chunk)
        finally:
            await loop.run_in_executor(None, f.close)
    except Exception:  # broad: streaming upload may fail at any I/O step; ensure dest cleanup then re-raise
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise

    return dest


async def resolve_file_path(file_path: str, job_id: str | None = None) -> str:
    """Resolve a file path that may be an S3 key to a local file path.

    If the file exists locally, returns as-is. If not (presigned S3 upload),
    downloads from S3 to a local temp path and returns that path. The S3
    download retries up to 2 times on transient network failures with linear
    backoff so a single S3 blip mid-ingest doesn't force the user to reupload.
    """
    if Path(file_path).exists():
        return file_path

    # File was uploaded directly to S3 via presigned URL
    import asyncio

    from app.platform.storage import get_storage

    storage = get_storage()
    local_name = f"{job_id}_{Path(file_path).name}" if job_id else Path(file_path).name
    local_path = Path(settings.upload_staging_dir) / local_name

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await storage.get_to_file(file_path, local_path)
            return str(local_path)
        except (OSError, asyncio.TimeoutError, ConnectionError) as exc:
            # OSError covers most botocore network failures (BotoCoreError is a subclass).
            # Re-raise immediately on permanent errors (NoSuchKey, AccessDenied) — those
            # surface as ClientError with specific codes; OSError is the transient bucket.
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(2**attempt)  # 1s, 2s
                continue
            raise
    if last_exc is not None:  # pragma: no cover - unreachable, satisfies type checker
        raise last_exc
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

    # Check for collision against catalog — single query instead of loop
    DatasetORM = get_processing_port().get_dataset_orm_class()

    base_slug = slug
    collision_warning: str | None = None
    result = await session.execute(
        select(DatasetORM.table_name).where(DatasetORM.table_name.like(f"{base_slug}%"))
    )
    existing = {row[0] for row in result.all()}

    if slug in existing:
        suffix = 2
        while f"{base_slug}_{suffix}" in existing:
            suffix += 1
        slug = f"{base_slug}_{suffix}"
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
    user: Identity,
) -> "Any":
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

    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    # CR-03 (Phase 1209): resolve the per-tenant schema so catalog queries
    # target data_t_{tid} in multi_tenant rather than the shared 'data' schema.
    _schema = tenant_data_schema(
        current_tenant_var.get() if is_multi_tenant() else None
    )

    # Verify table exists in the correct schema
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = :schema AND table_name = :table_name"
            ")"
        ).bindparams(schema=_schema, table_name=table_name)
    )
    if not result.scalar():
        raise ValueError(f"Table '{_schema}.{table_name}' does not exist.")

    # Check for duplicate registration
    Dataset = get_processing_port().get_dataset_orm_class()

    existing = await session.execute(
        select(Dataset).where(Dataset.table_name == table_name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"Table '{table_name}' is already registered as a dataset.")

    # Check for geometry columns
    geom_result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name "
            "AND column_name IN ('geom', 'geom_4326')"
        ).bindparams(schema=_schema, table_name=table_name)
    )
    geom_cols = {row[0] for row in geom_result.all()}

    has_geom = "geom" in geom_cols
    has_4326 = "geom_4326" in geom_cols

    from app.processing.ingest.tasks_common import (
        _current_tenant_role,
    )

    # CR-03 (Phase 1212): use per-tenant schema/role for the grant so published
    # assets in multi_tenant land on the correct per-tenant reader role rather
    # than the global 'geolens_reader' default. No-op in single_tenant
    # (_current_tenant_schema()='data', _current_tenant_role()='geolens_reader').
    _grant_role = _current_tenant_role()

    metadata = {}
    if has_geom:
        if not has_4326:
            srid = await get_table_srid(session, table_name, schema=_schema)
            # Wrap in savepoint so a partial failure (column added but
            # index creation fails) rolls back cleanly instead of leaving
            # the table in a half-indexed state (R-8).
            try:
                async with session.begin_nested():
                    await add_4326_column(session, table_name, srid or 4326)
            except Exception as exc:  # broad: ALTER TABLE/CREATE INDEX inside savepoint can fail for schema/permission reasons
                raise ValueError(
                    f"Failed to add geom_4326 column to '{table_name}': {exc}"
                ) from exc

        await grant_reader_access(session, table_name, schema=_schema, role=_grant_role)
        metadata = await extract_metadata(session, table_name, schema=_schema)
    else:
        # Non-spatial table -- grant access but skip spatial metadata
        await grant_reader_access(session, table_name, schema=_schema, role=_grant_role)

    # Extract sample values for attribute metadata example_values
    col_info = metadata.get("column_info", [])
    sample_vals = (
        await get_sample_values(session, table_name, col_info, schema=_schema)
        if col_info
        else None
    )

    port = get_processing_port()
    ingestion = port.create_ingestion_result(
        **{**metadata, "column_info": col_info, "sample_values": sample_vals}
    )
    dataset = await port.create_dataset(
        session,
        table_name=table_name,
        title=request.title,
        created_by=user.id,
        summary=request.summary,
        visibility=request.visibility,
        ingestion=ingestion,
    )

    return dataset


async def create_vrt_job(
    db: AsyncSession,
    request: VrtCreateRequest,
    user: Identity,
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

    from app.processing.ingest.tasks import ingest_vrt
    from app.processing.raster.models import RasterAsset
    from app.processing.raster.validation import validate_sources

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

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

    # 3b. SEC-C: authorize EVERY source dataset against the caller before
    # mosaicking. The worker compiles all source pixels into a single served
    # asset, so a foreign private source cannot be filtered at read time —
    # authorize at write/link time (mirrors #234's create_relationship). On
    # denial, check_dataset_access raises 404. This runs BEFORE
    # validate_sources so a foreign source 404s rather than leaking a 422
    # compatibility error about a dataset the caller cannot see.
    from app.modules.catalog.authorization import (
        check_dataset_access,
        get_user_roles,
    )
    from app.modules.catalog.datasets.domain.service import get_dataset

    user_roles = await get_user_roles(db, user)
    for sid in request.source_dataset_ids:
        src_dataset = await get_dataset(db, sid)  # existence proven above; non-None
        await check_dataset_access(db, src_dataset, sid, user, user_roles=user_roles)

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
        await defer_async_with_tenant(
            ingest_vrt,
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


def _user_safe_error(exc: Exception) -> str:
    """Return a user-safe error string from an exception (T-1058D-04).

    Strips absolute file-system paths so internal infrastructure is not
    leaked in FanOutLayerResult.error responses.

    Patterns removed:
      - Leading path component matching '/<word>/' prefix (Unix absolute paths)
      - Windows-style paths C:\\...
      - Common staging dir prefixes from settings
    """
    import re

    msg = str(exc)
    # Remove Unix-style absolute paths (e.g. /tmp/staging/..., /Users/...).
    msg = re.sub(r"/(?:[^/\s]+/)+[^/\s]*", "<path>", msg)
    # Remove Windows-style absolute paths (e.g. C:\Users\...).
    msg = re.sub(r"[A-Za-z]:\\[^\s]+", "<path>", msg)
    return msg


async def create_fan_out_jobs(
    original_job: "IngestJob",
    layer: "Any",
    session: AsyncSession,
) -> "Any":
    """Clone an IngestJob for one layer and dispatch the ingest task.

    Called once per layer by the /ingest/commit-fan-out/{job_id} endpoint.
    Creates a new IngestJob (pointing at the same file_path), sets
    layer_name + fan_out_parent_id in its user_metadata, then defers the
    standard ``ingest_file`` Procrastinate task.

    The Dataset row is created later by the ingest task itself
    (``_finalize_ingest`` in tasks_common.py) — NOT here — to preserve the
    full metadata extraction pipeline (geom_4326, column metadata, quality
    score, etc.).

    IMPORTANT: Does NOT touch or remove original_job.file_path. Multiple
    fan-out jobs share the same file on disk; file cleanup is keyed on
    individual per-fan-out job IDs by _archive_original_file in
    tasks_common.py (which reads job.file_path on the cloned job, not the
    parent), so the file remains available for every sibling task.

    Returns FanOutLayerResult with status='queued' on success or
    status='failed' with a user-safe error on exception.

    T-1058D-04: error messages are sanitized by _user_safe_error() to
    prevent internal file-system paths from leaking to the client.
    """
    from app.processing.ingest.schemas import FanOutLayerResult

    try:
        # 1. Determine the dataset title for this layer.
        file_base = original_job.source_filename or "dataset"
        # Strip common extensions to get a clean basename.
        import re as _re

        file_base = _re.sub(r"\.[^.]+$", "", file_base)
        title = layer.title if layer.title else f"{file_base}: {layer.layer_name}"

        # 2. Clone the original IngestJob for this layer.
        new_job = IngestJob(
            file_path=original_job.file_path,
            source_filename=original_job.source_filename,
            status="pending",
            created_by=original_job.created_by,
            # Merge parent metadata with per-layer overrides.
            user_metadata={
                **(original_job.user_metadata or {}),
                # Overwrite keys that are layer-specific:
                "layer_name": layer.layer_name,
                "title": title,
                "fan_out_parent_id": str(original_job.id),
                # Clear dataset_id from parent metadata — each fan-out job
                # creates its own dataset during _finalize_ingest.
                "dataset_id": None,
            },
        )
        session.add(new_job)
        await session.flush()  # assigns new_job.id
        # Phase 1060 close-gate fix: COMMIT before deferring the Procrastinate
        # task. defer_async uses a separate DB connection, so the worker can
        # pick up the task before our session commits — when it tries to load
        # the IngestJob row, it logs "Ingest job not found, skipping" and the
        # job stays in 'pending' forever. Committing here makes the new_job
        # row visible to the worker before the task is enqueued.
        # Orphan risk on defer failure is handled by defer_with_orphan_guard
        # below, which flips the committed row to status='failed' via the
        # rollback closure.
        await session.commit()

        # 3. Defer ingest_file for the cloned job.
        from app.processing.ingest.tasks import ingest_file
        from app.platform.jobs.defer_guard import (
            defer_with_orphan_guard,
            make_ingest_job_failed_rollback,
        )

        file_path = new_job.file_path or ""

        async def _defer_fan_out_layer() -> None:
            await defer_async_with_tenant(
                ingest_file,
                job_id=str(new_job.id),
                file_path=file_path,
                user_id=str(new_job.created_by or ""),
            )

        await defer_with_orphan_guard(
            _defer_fan_out_layer,
            rollback=make_ingest_job_failed_rollback(new_job),
            db=session,
        )

        return FanOutLayerResult(
            layer_name=layer.layer_name,
            new_job_id=new_job.id,
            dataset_id=None,  # populated by the ingest task after completion
            status="queued",
        )

    except (
        Exception
    ) as exc:  # broad: any clone/defer failure returns per-layer error, not a 500
        logger = None
        try:
            import structlog as _structlog

            logger = _structlog.get_logger(__name__)
        except Exception:  # broad: structlog optional — defer to print if unavailable
            pass
        if logger:
            logger.warning(
                "Fan-out layer dispatch failed",
                layer_name=layer.layer_name,
                original_job_id=str(original_job.id),
                error=str(exc),
            )
        from app.processing.ingest.schemas import FanOutLayerResult

        return FanOutLayerResult(
            layer_name=layer.layer_name,
            new_job_id=None,
            dataset_id=None,
            status="failed",
            error=_user_safe_error(exc),
        )


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
            await defer_async_with_tenant(
                ingest_service,
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
            await defer_async_with_tenant(
                ingest_raster,
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

    use_priority = 0 < file_size <= PRIORITY_QUEUE_THRESHOLD_BYTES

    async def _defer_vector() -> None:
        task = ingest_file
        if use_priority:
            task = task.configure(queue="priority")
        await defer_async_with_tenant(
            task,
            job_id=str(job.id),
            file_path=file_path,
            user_id=user_id,
        )

    await defer_with_orphan_guard(
        _defer_vector,
        rollback=make_ingest_job_failed_rollback(job),
        db=db,
    )
