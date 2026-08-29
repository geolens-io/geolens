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
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.identity import Identity
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.platform.dataset_origin import set_postgis_origin
from app.platform.extensions import get_processing_port
from app.processing.ingest.metadata import (
    add_4326_column,
    linearize_existing_4326,
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
from app.platform.storage.titiler_url import resolve_current_storage_key

# Spool threshold for S3 uploads (PERF-001): SpooledTemporaryFile buffers this
# many bytes in memory before spilling to a real temp file on disk.  16 MiB is
# a reasonable balance — small files stay fully in RAM while large uploads
# (e.g. a 200 MB GeoTIFF) do not consume hundreds of MB of heap per concurrent
# request.
_UPLOAD_SPOOL_MAX_BYTES: int = 16 * 1024 * 1024  # 16 MiB

# Presigned multipart part size. fix(#836): lives here, not in router.py, so the
# CatalogPort default (platform layer) can read it without importing the API
# edge — importing a router module executes route registration as a side effect.
PART_SIZE = 10 * 1024 * 1024  # 10MB per part


async def _await_provider_call_draining(awaitable: Any) -> Any:
    """Await provider I/O without abandoning its background SDK thread."""
    provider_task = asyncio.ensure_future(awaitable)
    cancelled: asyncio.CancelledError | None = None
    while not provider_task.done():
        try:
            # asyncio.wait does not propagate this task's cancellation into the
            # provider task. Keep draining through repeated shutdown cancels.
            await asyncio.wait({provider_task})
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc

    if cancelled is not None:
        if not provider_task.cancelled():
            provider_task.exception()  # retrieve provider failures before cancelling
        raise cancelled
    return provider_task.result()


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


def safe_upload_basename(filename: str | None) -> str:
    """The filename stripped to a basename, which is the only form safe to key on.

    fix(#1290 review): this was two inline `Path(x).name` copies inside
    ``save_upload_file``, and a third consumer (the archived-original key)
    derived from the RAW filename instead. A name carrying path separators then
    split the derivation — the logical URI kept the directory while the actual
    write basenamed it — so the counted row pointed at a nonexistent object and
    cleanup tracked a key nobody had written. One policy, one function, every
    consumer.
    """
    return Path(filename or "").name or "upload"


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
        safe_name = safe_upload_basename(file.filename)  # strip path traversal
        s3_key = f"staging/{job_id}/{safe_name}"
        physical_s3_key = resolve_current_storage_key(s3_key)
        put_started = False
        try:
            if max_size_bytes is not None:
                # Stream-and-accumulate with a SpooledTemporaryFile so S3 mode
                # enforces the same size limit as local mode without holding the
                # entire upload in memory.  SpooledTemporaryFile buffers up to
                # _UPLOAD_SPOOL_MAX_BYTES in RAM; once that threshold is exceeded
                # it spills to a real temp file on disk, bounding heap usage to the
                # spool threshold regardless of upload size (PERF-001).
                #
                # The per-chunk 413 check fires BEFORE the chunk is written so
                # over-limit uploads are rejected mid-stream. The provider call
                # is drained before the spool closes, preventing cancellation
                # from making an SDK thread read a closed temporary file.
                total = 0
                spooled = tempfile.SpooledTemporaryFile(
                    max_size=_UPLOAD_SPOOL_MAX_BYTES
                )
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
                    put_started = True
                    await _await_provider_call_draining(
                        storage.put(physical_s3_key, spooled)
                    )
                finally:
                    spooled.close()
            else:
                put_started = True
                await _await_provider_call_draining(
                    storage.put(physical_s3_key, file.file)
                )
        except BaseException:
            if put_started:
                # A drained PUT may have completed just as the request was
                # cancelled. Remove that now-ownerless object before the route's
                # job transaction rolls back.
                try:
                    await _await_provider_call_draining(storage.delete(physical_s3_key))
                except BaseException:
                    pass
            raise
        return s3_key

    staging_dir = Path(settings.upload_staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    safe_name = safe_upload_basename(file.filename)  # strip path traversal
    dest = staging_dir / f"{job_id}_{safe_name}"

    total = 0
    # Opening synchronously is intentional: there must be no cancellation point
    # between acquiring the descriptor and assigning it to ``f``, otherwise a
    # cancelled executor future can leave an unreachable open descriptor behind.
    f = open(dest, "wb")
    try:
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
                # A cancelled request does not stop a worker thread. Drain the
                # write before closing/unlinking so no background thread can
                # continue writing through an unlinked descriptor.
                await run_in_thread_draining(f.write, chunk)
        finally:
            await run_in_thread_draining(f.close)
    except BaseException:
        # Includes CancelledError/client disconnect as well as ordinary I/O and
        # streamed-size failures. The descriptor has been drained and closed by
        # the inner finally before the path is removed.
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise

    return dest


async def _download_to_file_draining(storage: Any, key: str, dest: Path) -> None:
    """Download to ``dest`` without abandoning provider work on cancellation.

    Storage providers commonly wrap blocking SDKs with ``asyncio.to_thread``.
    Cancelling that coroutine does not stop the SDK thread, so the caller must
    shield it from cancellation and wait until it releases the destination
    before cleanup can safely unlink the file.
    """
    await _await_provider_call_draining(storage.get_to_file(key, dest))


async def resolve_file_path(file_path: str, job_id: str | None = None) -> str:
    """Resolve a file path that may be an S3 key to a local file path.

    If the file exists locally, returns as-is. If not (presigned S3 upload),
    downloads from S3 to a local temp path and returns that path. The S3
    download retries up to 2 times on transient network failures with linear
    backoff so a single S3 blip mid-ingest doesn't force the user to reupload.
    """
    from app.core.tenancy import is_multi_tenant

    candidate = Path(file_path)
    if candidate.exists() and (candidate.is_absolute() or not is_multi_tenant()):
        return file_path

    # File was uploaded directly to S3 via presigned URL
    import asyncio

    from app.platform.storage import get_storage

    storage = get_storage()
    # Manifest storage sources are operator-owned physical keys and must be
    # consumed exactly as declared. Only GeoLens upload staging keys are
    # logical catalog/job identifiers that cross the tenant resolver.
    physical_file_path = (
        resolve_current_storage_key(file_path)
        if file_path.startswith("staging/")
        else file_path
    )
    # Every caller owns a distinct local copy. Preview requests may overlap a
    # worker or another preview for the same job; a deterministic path allowed
    # one caller's finally block to unlink a file another GDAL process was using.
    safe_name = Path(file_path).name
    prefix = f"{job_id}_" if job_id else "download_"
    fd, unique_path = tempfile.mkstemp(
        prefix=prefix,
        suffix=f"_{safe_name}",
        dir=settings.upload_staging_dir,
    )
    os.close(fd)
    local_path = Path(unique_path)

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await _download_to_file_draining(storage, physical_file_path, local_path)
            return str(local_path)
        except (OSError, asyncio.TimeoutError, ConnectionError) as exc:
            # OSError covers most botocore network failures (BotoCoreError is a subclass).
            # Re-raise immediately on permanent errors (NoSuchKey, AccessDenied) — those
            # surface as ClientError with specific codes; OSError is the transient bucket.
            last_exc = exc
            local_path.unlink(missing_ok=True)
            if attempt < 2:
                await asyncio.sleep(2**attempt)  # 1s, 2s
                # Some storage clients require the destination to exist;
                # recreate the same caller-owned path for the next attempt.
                local_path.touch(mode=0o600, exist_ok=False)
                continue
            raise
        except (
            Exception
        ):  # broad: permanent storage providers expose backend-specific exception types
            # Permanent storage errors are not retried, but any partial file is
            # still owned by this call and must not accumulate in staging.
            local_path.unlink(missing_ok=True)
            raise
        except BaseException:
            # Cancellation is delivered only after the provider download has
            # drained, so unlink cannot race a still-running SDK thread.
            local_path.unlink(missing_ok=True)
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


# PostgreSQL truncates any identifier past NAMEDATALEN-1 = 63 bytes, silently
# and with only a NOTICE. Slugs are ASCII-transliterated, so bytes == chars.
_MAX_IDENTIFIER_CHARS = 63

# fix(#1444 review): the collision walk refuses past this rather than emitting a
# name Postgres would truncate. At a 60-char base, `_100` is the first candidate
# that crosses 63 — before retirement that took 99 LIVE datasets sharing one
# title, but retired names accumulate forever, so the walk genuinely reaches it
# now. A truncated `{base}_100` addresses the same physical relation as
# `{base}_10` while the catalog keeps both untruncated strings, which puts two
# logical names on one table and hands the disclosure straight back.
# `_with_collision_suffix` keeps every candidate inside the limit, and this
# bound keeps the tag short enough that `_COLLISION_PROBE_CHARS` below stays a
# prefix of all of them. The two constants have to move together.
_MAX_COLLISION_SUFFIX = 9999
_COLLISION_PROBE_CHARS = _MAX_IDENTIFIER_CHARS - len(f"_{_MAX_COLLISION_SUFFIX}")


def _with_collision_suffix(base: str, suffix: int) -> str:
    """``base`` plus ``_N``, trimming the base so the whole name fits in 63."""
    tag = f"_{suffix}"
    return f"{base[: _MAX_IDENTIFIER_CHARS - len(tag)]}{tag}"


def _retired_tenant_scope(RetiredORM: Any, tenant_id: str | uuid.UUID | None) -> Any:
    """Which retired names bind for ``tenant_id``: its own, plus the NULL ones.

    ``current_tenant_var`` carries the id as a STRING, and the column is
    ``UUID(as_uuid=True)``. The coercion is explicit rather than left to the
    dialect because the failure direction is silent: a comparison that matches
    nothing reads as "no name is retired" and hands one straight back.
    """
    scope = RetiredORM.tenant_id.is_(None)
    if tenant_id is not None:
        as_uuid = (
            tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
        )
        scope = or_(scope, RetiredORM.tenant_id == as_uuid)
    return scope


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
    - Collision handling: _2, _3, _4, ..., with the base trimmed further when a
      longer suffix would push the name past PostgreSQL's 63-byte identifier
      limit. Raises ValueError once _MAX_COLLISION_SUFFIX is exhausted, rather
      than returning a name the database would silently truncate onto another
      dataset's relation.
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
    # fix(#1444 review): the LIKE prefix is the base trimmed to
    # _COLLISION_PROBE_CHARS, not the base itself, because a candidate carrying
    # a long suffix has a SHORTER base — `_with_collision_suffix` trims to keep
    # the whole name inside 63 — and a probe keyed on the full base would not
    # match it. Trimming here makes the prefix a prefix of every candidate the
    # walk below can produce. It over-matches for slugs longer than
    # _COLLISION_PROBE_CHARS, which costs those names a suffix they might not
    # have needed; under-matching would cost the guarantee.
    probe_prefix = base_slug[:_COLLISION_PROBE_CHARS]
    result = await session.execute(
        select(DatasetORM.table_name).where(
            DatasetORM.table_name.like(f"{probe_prefix}%")
        )
    )
    existing = {row[0] for row in result.all()}

    # fix(#692): also collide against live relations. A worker killed between
    # committing an output table and registering it leaves a physical table
    # with no Dataset row; a catalog-only probe would hand out that name
    # forever, failing every retry on CREATE TABLE. The retry self-heals to a
    # _N suffix instead — deliberately NO auto-DROP of the orphan here.
    # fix(#700 review): probe pg_catalog, not information_schema — the SQL
    # standard filters information_schema to relations the current role has
    # privileges on, so a role that doesn't own the orphan (it never reached
    # grant_reader_access) can be blind to exactly the collision this probe
    # exists to find. pg_class is visible to every role and covers all
    # relation kinds that contend for the name.
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    _tid = current_tenant_var.get() if is_multi_tenant() else None
    _schema = tenant_data_schema(_tid)
    info_result = await session.execute(
        text(
            "SELECT c.relname FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = :schema AND c.relname LIKE :pattern"
        ).bindparams(schema=_schema, pattern=f"{probe_prefix}%")
    )
    existing |= {row[0] for row in info_result.all()}

    # fix(#1443): and collide against RETIRED names. Both probes above ask
    # what exists NOW, and a delete clears both, so the name of a deleted
    # dataset was handed straight back to the next one with that title. The
    # tile router caches table_name -> dataset metadata and reads
    # authorization out of that snapshot, so a worker that missed the delete
    # authorized the caller against the DELETED dataset's visibility and then
    # queried a table its successor owns. Treating a retired name exactly like
    # a live collision is what makes that unreachable: the successor of a
    # deleted `roads` gets `roads_2`, and no cached entry can outlive its
    # dataset's exclusive claim on the name.
    #
    # fix(#1444 review): tenant-scoped, mirroring migration 0020's per-tenant
    # uniqueness on catalog.datasets.table_name. Names are already per-tenant
    # everywhere it matters — the tile metadata cache keys on {tid}:{table} and
    # its query filters on tenant_id, and each tenant's tables live in their own
    # data_t_{tid} schema — so one tenant's tombstone cannot be inherited by
    # another and retiring it globally only costs unrelated tenants suffixes.
    # With the _MAX_COLLISION_SUFFIX bound above, that stopped being cosmetic:
    # a busy tenant's create/delete history could exhaust a shared budget and
    # refuse a title for everyone.
    #
    # NULL-tenant rows count in every scope, deliberately. That is the
    # single-tenant namespace (the uq_datasets_table_name_global half of 0020),
    # and it is also where any row retired before a single -> multi transition
    # sits, since nothing back-stamps this table. Over-collision on a bounded
    # historical set is the cheap direction; missing those rows would quietly
    # reopen the window on exactly the oldest names.
    RetiredORM = get_processing_port().get_retired_table_name_orm_class()
    retired_result = await session.execute(
        select(RetiredORM.table_name).where(
            RetiredORM.table_name.like(f"{probe_prefix}%"),
            _retired_tenant_scope(RetiredORM, _tid),
        )
    )
    existing |= {row[0] for row in retired_result.all()}

    if slug in existing:
        suffix = 2
        while _with_collision_suffix(base_slug, suffix) in existing:
            suffix += 1
            if suffix > _MAX_COLLISION_SUFFIX:
                raise ValueError(
                    f"Exhausted table names for '{base_slug}': "
                    f"{_MAX_COLLISION_SUFFIX} variants are taken or retired. "
                    "Give this dataset a more distinctive title."
                )
        slug = _with_collision_suffix(base_slug, suffix)
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
    *,
    managed: bool = False,
) -> "Any":
    """Register an existing data-schema table into the dataset catalog.

    Verifies the table exists, checks for duplicate registration,
    ensures geom_4326 column and reader access, extracts metadata,
    and creates a Dataset record.

    fix(#1114): registered-table linear-geometry contract. ``geom_4326``
    on a registered table must stay linear -- curved geometry types
    (CIRCULARSTRING, COMPOUNDCURVE, CURVEPOLYGON, MULTICURVE,
    MULTISURFACE) are not supported. GeoLens linearizes the column once
    at registration (``linearize_existing_4326`` below) and does not
    police the table afterward: registration copies no data and serves
    from the live table, so the owner keeps writing to it directly. A
    curved row written that way degrades vector tiles, feature reads,
    and analysis for that dataset only; other datasets are unaffected.
    STORED GENERATED ``geom_4326`` columns fall under the same
    contract -- their generation expression must produce linear output.

    fix(#1452): ``managed`` declares that the CALLER created the table it is
    handing over, so deleting the resulting dataset may drop it again. It
    defaults to False because the two register endpoints take a table name
    from an operator and GeoLens has no claim on what it names; the analysis
    materialize path, which CTAS's its own output and registers it through
    this same function, is the one caller that passes True. Getting this
    wrong in the True direction drops a table GeoLens does not own, which is
    the bug GH-1452 exists to fix -- so it is an explicit argument at the one
    call site that can answer it, never a guess made from the table's shape.
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
    _tid = current_tenant_var.get() if is_multi_tenant() else None
    _schema = tenant_data_schema(_tid)

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

    # fix(#1444 review): registration is the one path that takes a table name
    # from the caller instead of generate_table_name, so the retirement probe
    # has to be repeated here or it is bypassable. Recreate a physical table
    # under a deleted public dataset's name, register it as private, and a
    # worker still holding the predecessor's metadata authorizes anonymously
    # against `public` while querying the successor's rows — the disclosure
    # GH-1443 exists to prevent, reached through the front door.
    #
    # Refuse rather than rename. Registration copies no data and serves from
    # the caller's own live table, so renaming it would be this service
    # reaching into storage it does not own to fix a name the caller chose.
    RetiredORM = get_processing_port().get_retired_table_name_orm_class()
    retired = await session.execute(
        select(RetiredORM.id)
        .where(
            RetiredORM.table_name == table_name,
            _retired_tenant_scope(RetiredORM, _tid),
        )
        .limit(1)
    )
    if retired.scalar_one_or_none() is not None:
        raise ValueError(
            f"Table '{table_name}' carries the name of a deleted dataset and "
            "cannot be registered. Rename the table and register it again."
        )

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

    if has_geom:
        if not has_4326:
            srid = await get_table_srid(session, table_name, schema=_schema)
            # Wrap in savepoint so a partial failure (column added but
            # index creation fails) rolls back cleanly instead of leaving
            # the table in a half-indexed state (R-8).
            try:
                async with session.begin_nested():
                    await add_4326_column(
                        session, table_name, srid or 4326, schema=_schema
                    )
            except Exception as exc:  # broad: ALTER TABLE/CREATE INDEX inside savepoint can fail for schema/permission reasons
                raise ValueError(
                    f"Failed to add geom_4326 column to '{table_name}': {exc}"
                ) from exc
        else:
            # fix(#1113 review): a pre-existing geom_4326 was written by
            # someone else, and a table registered AFTER migration 0034 ran is
            # invisible to its backfill — curved values here would reach the
            # readers with the per-read ST_CurveToLine wraps now gone.
            # Registration is the write boundary for such tables, so the
            # linear invariant is enforced on the way in.
            try:
                async with session.begin_nested():
                    await linearize_existing_4326(session, table_name, schema=_schema)
            except Exception as exc:  # broad: UPDATE inside savepoint can fail for schema/permission reasons
                raise ValueError(
                    f"Failed to linearize geom_4326 on '{table_name}': {exc}"
                ) from exc

    await grant_reader_access(session, table_name, schema=_schema, role=_grant_role)

    # fix(#1359): one derivation for every registration, spatial or not. The
    # non-spatial branch used to skip this entirely and register the table
    # with column_info and feature_count NULL — the same "the stats bar
    # contradicts the schema" state the ArcGIS import produced, reached a
    # different way. extract_metadata already reports srid, geometry_type,
    # and extent_wkt as None for a table with no geom column, so the spatial
    # fields land exactly as they did before.
    metadata = await extract_metadata(session, table_name, schema=_schema)

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

    # feat(#1218): registration copies no data and serves from the live table,
    # so the origin IS that table. Gate 2 (no external PostGIS federation in
    # v1) is why the ref carries a schema-qualified name and no connection
    # detail — the allowlist accepts no host, port, DSN, or credential key.
    #
    # fix(#1218 review r2): pass the SAME _schema this function verified,
    # granted, and extracted metadata in. Reading dataset.tenant_id instead
    # pointed every multi-tenant registration at `data.<table>`: the INSERT
    # sends tenant_id NULL and the trg_stamp_current_tenant_on_insert trigger
    # fills it in the database, so the ORM attribute never sees the real
    # value. _schema comes from the active tenant context and already fails
    # closed in multi-tenant mode when that context is missing.
    set_postgis_origin(dataset, table_name, schema=_schema, managed=managed)

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
    # denial, check_datasets_access_bulk raises 404. This runs BEFORE
    # validate_sources so a foreign source 404s rather than leaking a 422
    # compatibility error about a dataset the caller cannot see.
    #
    # fix(#1298): batched — a 500-source request used to cost one
    # get_dataset() + check_dataset_access() round trip per source.
    from app.modules.catalog.authorization import (
        check_datasets_access_bulk,
        get_user_roles,
    )

    user_roles = await get_user_roles(db, user)
    await check_datasets_access_bulk(db, request.source_dataset_ids, user, user_roles)

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
            attempt_id=str(job.attempt_id),
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
                attempt_id=str(new_job.attempt_id),
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


async def finalize_fan_out_parent(
    session: AsyncSession,
    job: IngestJob,
    *,
    parent_attempt_id: uuid.UUID | None,
    results: list[Any],
) -> list[Any]:
    """CAS the parent to ``fanned_out``; on loss, cancel the queued children.

    fix(#1709 review r2 P1): the fan-out endpoint queues children (each one
    committed and deferred inside ``create_fan_out_jobs``) BEFORE the parent
    reaches its terminal status, and the old ``job.status = "fanned_out"``
    attribute write was blind — ``POST /jobs/{id}/cancel`` could terminate
    the still-pending parent mid-loop and this endpoint would overwrite that
    committed ``cancelled`` row while every child kept importing. The
    transition is now the same fenced CAS the cancel endpoint uses (expected
    ``pending`` + the attempt id read when this request validated the
    parent), so exactly one of the two writers wins.

    When this side loses, the only writer that can have moved a pending
    parent is that cancel CAS (retry only offers ``failed`` rows), and
    honoring it means the children this call just queued must not keep
    importing: a guarded CAS flips each still-active child to ``cancelled``
    (a child a worker already finalized keeps its terminal state), then
    best-effort queue aborts accelerate the stop — the ingest
    claim/finalize fences make eventual delivery a no-op regardless. The
    returned results mark those layers ``failed`` so the caller sees the
    true outcome instead of ``queued`` rows that will never produce
    datasets.
    """
    from datetime import datetime, timezone

    import structlog
    from sqlalchemy import update as sa_update

    from app.processing.ingest.schemas import FanOutLayerResult

    now = datetime.now(timezone.utc)
    attempt_predicate = (
        IngestJob.attempt_id == parent_attempt_id
        if parent_attempt_id is not None
        else IngestJob.attempt_id.is_(None)
    )
    parent_cas = await session.execute(
        sa_update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "pending",
            attempt_predicate,
        )
        .values(status="fanned_out", completed_at=now)
    )
    await session.commit()
    if parent_cas.rowcount:
        return results

    child_ids = [r.new_job_id for r in results if r.status == "queued" and r.new_job_id]
    cancelled_result = await session.execute(
        sa_update(IngestJob)
        .where(
            IngestJob.id.in_(child_ids),
            IngestJob.status.in_(("pending", "running")),
        )
        .values(
            status="cancelled",
            error_message="Cancelled by user",
            completed_at=now,
        )
        .returning(IngestJob.id)
    )
    cancelled_ids = set(cancelled_result.scalars())
    await session.commit()
    structlog.get_logger().warning(
        "fan_out_parent_lost_to_cancel",
        parent_job_id=str(job.id),
        children_cancelled=[str(i) for i in sorted(cancelled_ids, key=str)],
    )

    # Best-effort queue aborts, one child at a time — the same args->>
    # correlation and log-and-continue discipline as the cancel endpoint's
    # own post-commit block. Inlined SQL rather than importing the cancel
    # router's private constant, matching how the sweeps each carry their
    # own copy of this correlation.
    for child_id in sorted(cancelled_ids, key=str):
        try:
            rows = await session.execute(
                text(
                    "SELECT id FROM catalog.procrastinate_jobs"
                    " WHERE args->>'job_id' = :job_id"
                    " AND status IN ('todo', 'doing')"
                ),
                {"job_id": str(child_id)},
            )
            queue_job_ids = list(rows.scalars())
        except Exception:  # broad: queue abort is acceleration, never the guarantee
            structlog.get_logger().warning(
                "fan_out_child_queue_lookup_failed",
                child_job_id=str(child_id),
                exc_info=True,
            )
            continue
        for queue_job_id in queue_job_ids:
            try:
                from app.processing.ingest.tasks import task_app

                await task_app.job_manager.cancel_job_by_id_async(
                    queue_job_id, abort=True
                )
            except Exception:  # broad: queue abort is acceleration, never the guarantee
                structlog.get_logger().warning(
                    "fan_out_child_queue_abort_failed",
                    child_job_id=str(child_id),
                    queue_job_id=queue_job_id,
                    exc_info=True,
                )

    return [
        FanOutLayerResult(
            layer_name=r.layer_name,
            new_job_id=r.new_job_id,
            dataset_id=None,
            status="failed",
            error=(
                "Cancelled: the source job was cancelled while this layer "
                "was being queued."
            ),
        )
        if r.new_job_id in cancelled_ids
        else r
        for r in results
    ]


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
    Raises ``HTTPException 503`` when Procrastinate is unreachable, or when a
    configured credential store cannot be reached to stage a service token
    (feat(#1676) — see ``resolve_dispatch_credential``).
    """
    import os

    from app.platform.refresh.credentials import (
        CredentialStoreUnavailable,
        discard_service_credential,
        resolve_dispatch_credential,
    )
    from app.processing.ingest.constants import PRIORITY_QUEUE_THRESHOLD_BYTES
    from app.processing.ingest.tasks import ingest_file, ingest_raster, ingest_service

    if job.source_url and not job.file_path:
        # Service job — route to ingest_service. Capture source_url into
        # a local so mypy preserves the ``str`` narrowing inside the
        # nested closure (the attribute access reverts to ``str | None``).
        source_url = job.source_url
        job_failed = make_ingest_job_failed_rollback(job)

        # feat(#1676): the import door's half of the lease. On an install with
        # a shared credential store this returns (None, ref) and the secret
        # never becomes a task argument; without one it returns the token
        # unchanged, which is what this door has always dispatched. The whole
        # decision — including which of those two an install gets — is
        # resolve_dispatch_credential's, so this door cannot drift from the
        # re-upload one.
        credential_ref: str | None = None
        try:
            token, credential_ref = await resolve_dispatch_credential(
                token, door="import"
            )
        except CredentialStoreUnavailable as exc:
            # The job row is already committed by the time this runs
            # (commit_import commits before dispatching), so a bare raise
            # would strand it pending until the stale sweep. Finalize it the
            # way the orphan guard would have, then answer with the 503 the
            # refresh door gives for the same condition.
            await job_failed(exc)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "credential_store_unavailable",
                    "message": (
                        "Could not stage the service credential for this "
                        "import. Check that the credential store is "
                        "reachable and try again."
                    ),
                },
            ) from exc

        async def _defer_service() -> None:
            await defer_async_with_tenant(
                ingest_service,
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                source_url=source_url,
                source_layer=job.source_layer or "",
                user_id=user_id,
                token=token,
                # fix(#1689 codex r1) — ROLLING-DEPLOY SKEW, accepted, and
                # accepted the way #1220 accepted the identical question at
                # the refresh door (router_refresh.py carries the long form).
                # A worker from the previous generation takes `credential_ref`
                # through `**kwargs` and discards it, fetches unauthenticated,
                # collects the origin's 401, and fails the job blaming the
                # origin.
                #
                # The gate that would close it is a task name old workers do
                # not register, and it is the WORSE option for the reason
                # #1220 wrote down: Procrastinate marks its OWN job failed on
                # TaskNotFound, but nothing then writes the ingest_jobs row,
                # so it sits `pending` in the user's job list until the
                # stale-job sweep. A hang reads worse than a failure you can
                # retry, and the retry succeeds because by then the window has
                # closed.
                #
                # The window is narrower here than at the refresh door. A
                # storeless install dispatches no reference at all (state 3),
                # so the default deployment has no skew; only an install with
                # REDIS_URL set, mid-rollout, on a token-bearing import is
                # exposed, and single-node compose deploys never overlap
                # generations. Nothing is stranded either: the old worker
                # fails the job, `ingest_jobs.status` leaves ('pending',
                # 'running'), renewal stops, and the credential dies by TTL.
                credential_ref=credential_ref,
            )

        async def _rollback_service(defer_exc: BaseException) -> None:
            await job_failed(defer_exc)
            # The worker will never come for it. Best-effort; the TTL is the
            # real guarantee, and this only shortens a window we already know
            # nothing will use.
            await discard_service_credential(credential_ref)

        await defer_with_orphan_guard(
            _defer_service,
            rollback=_rollback_service,
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
                attempt_id=str(job.attempt_id),
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
            attempt_id=str(job.attempt_id),
            file_path=file_path,
            user_id=user_id,
        )

    await defer_with_orphan_guard(
        _defer_vector,
        rollback=make_ingest_job_failed_rollback(job),
        db=db,
    )
