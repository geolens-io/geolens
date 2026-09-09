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

import structlog
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import String, and_, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.identity import Identity
from app.core.config import settings
from app.core.service_tokens import (
    ServiceCredential,
    header_token_rejection_reason,
    requires_header_token_policy,
)
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
from app.platform.jobs.heartbeat import (
    ATTEMPT_STAGING_NAME_PATTERN,
    is_attempt_scoped_staging_table,
)
from app.platform.jobs.models import (
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    IngestJob,
    commit_attempted_marker,
)
from app.platform.storage.titiler_url import resolve_current_storage_key

logger = structlog.get_logger(__name__)

# SpooledTemporaryFile buffers this many bytes in memory before spilling to
# disk, so large uploads don't consume hundreds of MB of heap per request.
_UPLOAD_SPOOL_MAX_BYTES: int = 16 * 1024 * 1024  # 16 MiB

# fix(#836): lives here, not router.py, so CatalogPort (platform layer) can
# read it without importing the API edge (which registers routes on import).
PART_SIZE = 10 * 1024 * 1024  # 10MB per part


async def _await_provider_call_draining(awaitable: Any) -> Any:
    """Await provider I/O without abandoning its background SDK thread."""
    provider_task = asyncio.ensure_future(awaitable)
    cancelled: asyncio.CancelledError | None = None
    while not provider_task.done():
        try:
            # asyncio.wait doesn't propagate our cancellation into provider_task.
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

    Excludes staging tables, old tables, and spatial_ref_sys. Bounded by
    ``limit``. In multi_tenant, searches the per-tenant ``data_t_{tid}``
    schema so cross-tenant tables are never returned.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tid = current_tenant_var.get()
    schema = tenant_data_schema(tid)

    # In multi_tenant, bind the LEFT JOIN exclusion to the active tenant so a
    # table registered by tenant A doesn't suppress discovery for tenant B
    # sharing the same table_name. In single_tenant, tid is None and the
    # filter must not apply (catalog.datasets may lack a tenant_id column).
    if is_multi_tenant() and tid is not None:
        tenant_join_clause = "AND d.tenant_id = :tenant_id"
        bind_params = dict(schema=schema, limit=limit, tenant_id=tid)
    else:
        tenant_join_clause = ""
        bind_params = dict(schema=schema, limit=limit)
    bind_params["attempt_staging_pattern"] = ATTEMPT_STAGING_NAME_PATTERN

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
                -- fix(#1858): the two patterns above are the swap's names.
                -- `attempt_scoped_staging_table` produces
                -- `<base>_staging_<32 hex>`, which ends in neither, so a
                -- staging table leaked by a worker that died mid-import was
                -- listed here and permanently registerable. Same expression
                -- the registration refusal uses.
                AND t.table_name !~ :attempt_staging_pattern
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

    fix(#1290): one consumer used to derive its key from the raw
    filename. A name carrying path separators then split the derivation —
    the logical URI kept the directory while the write basenamed it — so
    cleanup tracked a key nobody had written. One policy, one function.
    """
    return Path(filename or "").name or "upload"


async def save_upload_file(
    file: UploadFile,
    job_id: str,
    max_size_bytes: int | None = None,
) -> Path | str:
    """Save an uploaded file to staging (local) or S3. Returns a Path or S3 key.

    In S3 mode with ``max_size_bytes`` set, streams chunks into a
    ``tempfile.SpooledTemporaryFile`` (spills to disk past
    ``_UPLOAD_SPOOL_MAX_BYTES``) and raises ``HTTPException(413)`` mid-stream
    once the cumulative size exceeds the limit — the presigned path instead
    checks ``file_size`` declaratively at request time and uses 422. Without
    ``max_size_bytes``, ``file.file`` streams directly to S3.

    In local mode, reads chunks asynchronously (64 KiB) via
    ``run_in_executor``; a partial file is removed on write failure.

    Callers MUST validate ``file.filename`` is non-empty before calling, so
    the error surfaces as the route handler's HTTP 400, not a TypeError.
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
                # The per-chunk 413 check fires before the chunk is written, so
                # over-limit uploads are rejected mid-stream. The provider call
                # is drained before the spool closes, so a cancellation can't
                # make an SDK thread read a closed temporary file.
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
                # cancelled; remove that now-ownerless object.
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
    # No cancellation point between acquiring the descriptor and assigning it
    # to ``f``, or a cancelled executor future could leave it unreachable.
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
                # Drain the write before closing/unlinking, since a cancelled
                # request doesn't stop the worker thread.
                await run_in_thread_draining(f.write, chunk)
        finally:
            await run_in_thread_draining(f.close)
    except BaseException:
        # Covers cancellation/disconnect and I/O failures; the inner finally
        # has already drained and closed the descriptor.
        try:
            os.unlink(dest)
        except OSError:
            pass
        raise

    return dest


async def _cleanup_saved_upload(
    saved_path: Path | str,
    job_id: str,
) -> None:
    """Delete a saved upload regardless of storage backend.

    Rolls back a failed upload so it doesn't orphan a file. Never raises —
    S3 failures are logged instead.
    """
    if isinstance(saved_path, Path):
        # codeql[py/path-injection] fix(#1708): the Path branch only ever receives a staging-rooted path (save_upload_file, or job.file_path the server itself wrote). The URL-import flow reaches this helper with an S3 KEY STRING and so takes the branch below — it is that call which makes the taint visible here.
        saved_path.unlink(missing_ok=True)
        return
    from app.platform.storage import get_storage

    try:
        physical_saved_path = resolve_current_storage_key(saved_path)
        await _await_provider_call_draining(get_storage().delete(physical_saved_path))
    except (
        BaseException
    ):  # broad: cleanup is best-effort and must drain through request cancellation
        logger.warning(
            "S3 cleanup failed during validation error — file may be orphaned",
            s3_key=str(saved_path),
            job_id=job_id,
        )


async def _download_to_file_draining(storage: Any, key: str, dest: Path) -> None:
    """Download to ``dest`` without abandoning provider work on cancellation.

    Cancelling the wrapping coroutine doesn't stop a storage SDK's own
    thread, so this drains it before cleanup can safely unlink ``dest``.
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
    # Manifest storage sources are operator-owned physical keys, consumed as
    # declared. Only GeoLens `staging/` keys are logical identifiers that
    # cross the tenant resolver.
    physical_file_path = (
        resolve_current_storage_key(file_path)
        if file_path.startswith("staging/")
        else file_path
    )
    # A unique path per caller: a preview may overlap a worker or another
    # preview for the same job, and a shared path let one caller's finally
    # block unlink a file another GDAL process was using.
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
            # OSError is the transient bucket; permanent errors (NoSuchKey,
            # AccessDenied) surface as ClientError instead and aren't retried.
            last_exc = exc
            local_path.unlink(missing_ok=True)
            if attempt < 2:
                await asyncio.sleep(2**attempt)  # 1s, 2s
                # Some storage clients require the destination to exist.
                local_path.touch(mode=0o600, exist_ok=False)
                continue
            raise
        except (
            Exception
        ):  # broad: permanent storage providers expose backend-specific exception types
            # Not retried, but the partial file must not accumulate in staging.
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

    Raises ValueError otherwise. Falls back to settings.allowed_extensions_list
    when allowed_list is not given.
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

# fix(#1444): the collision walk refuses past this rather than emit a
# name Postgres would truncate — a truncated `{base}_100` would address the
# same relation as `{base}_10` while the catalog keeps both untruncated
# strings, putting two logical names on one table. `_with_collision_suffix`
# keeps every candidate inside the limit; this bound keeps the tag short
# enough that `_COLLISION_PROBE_CHARS` stays a prefix of all of them — the
# two constants must move together.
_MAX_COLLISION_SUFFIX = 9999
_COLLISION_PROBE_CHARS = _MAX_IDENTIFIER_CHARS - len(f"_{_MAX_COLLISION_SUFFIX}")


def _with_collision_suffix(base: str, suffix: int) -> str:
    """``base`` plus ``_N``, trimming the base so the whole name fits in 63."""
    tag = f"_{suffix}"
    return f"{base[: _MAX_IDENTIFIER_CHARS - len(tag)]}{tag}"


def _retired_tenant_scope(RetiredORM: Any, tenant_id: str | uuid.UUID | None) -> Any:
    """Which retired names bind for ``tenant_id``: its own, plus the NULL ones.

    ``current_tenant_var`` carries the id as a STRING against a
    ``UUID(as_uuid=True)`` column; coercion is explicit because a silent
    mismatch reads as "no name is retired" and hands one straight back.
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

    Returns ``(table_name, collision_warning)``; the warning is None unless a
    ``_N`` suffix was applied. Lowercased, ASCII-transliterated, truncated to
    60 chars (PG limit is 63), digit-leading names get an underscore prefix.
    Collision handling trims the base further as the suffix grows, and
    raises ValueError once _MAX_COLLISION_SUFFIX is exhausted rather than
    return a name Postgres would silently truncate onto another relation.
    """
    from slugify import slugify as _slugify

    slug = _slugify(name, separator="_", max_length=60, lowercase=True)

    if not slug:
        slug = "dataset"

    if slug[0].isdigit():
        slug = f"_{slug}"
        slug = slug[:60]

    DatasetORM = get_processing_port().get_dataset_orm_class()

    base_slug = slug
    collision_warning: str | None = None
    # fix(#1444): probe on the base trimmed to _COLLISION_PROBE_CHARS,
    # not the full base — a candidate with a long suffix has a shorter base
    # (`_with_collision_suffix` trims to stay inside 63), so a full-base probe
    # would miss it. Over-matches for longer slugs; under-matching would cost
    # the collision guarantee.
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
    # forever. The retry self-heals to a _N suffix — no auto-DROP here.
    # fix(#700): probe pg_catalog, not information_schema, which
    # filters to relations the current role has privileges on and can miss
    # an orphan that never reached grant_reader_access.
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

    # fix(#1443): also collide against RETIRED names. A delete clears both
    # probes above, so a deleted dataset's name was handed straight back to
    # the next one with that title — and the tile router's table_name ->
    # dataset cache could then authorize a caller against the deleted
    # dataset's visibility while querying the successor's table. Treating a
    # retired name as a live collision closes that: a deleted `roads`'s
    # successor gets `roads_2`.
    #
    # fix(#1444): tenant-scoped, mirroring migration 0020's per-tenant
    # uniqueness — names are already per-tenant everywhere it matters, so
    # retiring one globally would only cost unrelated tenants suffixes (and,
    # with the _MAX_COLLISION_SUFFIX bound above, could exhaust a shared
    # budget). NULL-tenant rows count in every scope: that's the
    # single-tenant namespace and where pre-multi-tenant retirements sit
    # uncorrected; over-collision there is the cheap direction.
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


def raster_stamped_metadata(
    user_metadata: dict | None, filename: str | None
) -> dict | None:
    """The ``user_metadata`` that should be persisted for ``filename``.

    fix(#1708): the pure form of ``_stamp_raster_metadata`` in router.py, for
    the paths that persist via a guarded CAS ``UPDATE`` rather than dirtying
    the ORM object (which would flush a second, unguarded UPDATE and bypass
    the CAS). fix(#1710): lives here rather than in the router so the URL
    fetch task can reach it without importing an HTTP module.
    """
    if not (filename or "").lower().endswith((".tif", ".tiff", ".vrt")):
        return user_metadata

    return {**(user_metadata or {}), "file_type": "raster"}


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

    fix(#1114): registered-table linear-geometry contract. ``geom_4326`` on a
    registered table must stay linear (no CIRCULARSTRING, COMPOUNDCURVE,
    CURVEPOLYGON, MULTICURVE, MULTISURFACE). Linearized once at registration
    (``linearize_existing_4326``); not policed afterward, since registration
    serves from the live table the owner keeps writing to directly. A later
    curved row degrades tiles/reads/analysis for that dataset only. STORED
    GENERATED ``geom_4326`` columns fall under the same contract.

    fix(#1738): "not policed afterward" means not policed continuously —
    direct writes can still leave ``geom_4326`` stale or NULL, invisible to
    every reader that filters on it. ``refresh_postgis`` is what picks that
    up: it re-derives the column, and restores it plus its GiST index and
    the reader grant if the table was dropped and recreated without them.

    fix(#1452): ``managed`` declares the CALLER created the table, so
    deleting the dataset may drop it again. Defaults False since the two
    register endpoints take an operator-named table; only the analysis
    materialize path (CTAS's its own output) passes True. Getting this
    wrong in the True direction drops a table GeoLens doesn't own — an
    explicit argument at the one call site that can answer it, not a guess.
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

    # Resolve the per-tenant schema so catalog queries target data_t_{tid}
    # in multi_tenant rather than the shared 'data' schema.
    _tid = current_tenant_var.get() if is_multi_tenant() else None
    _schema = tenant_data_schema(_tid)

    # fix(#1858): refused on the NAME alone, before the database is touched.
    # Discovery hides these but registration takes a name straight from the
    # caller, so hiding was never the same as refusing: a dataset bound to a
    # staging table is bound to storage the next import attempt will rename
    # away. Only the attempt-scoped shape is refused — `parcels_staging` and
    # `parcels_old` are names an ordinary title can produce.
    if is_attempt_scoped_staging_table(table_name):
        raise ValueError(
            f"Table '{table_name}' is an import staging table. It belongs to a "
            "single import attempt and is dropped when that attempt ends, so a "
            "dataset registered against it would lose its rows. Rename the "
            "table if you mean to keep it."
        )

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

    Dataset = get_processing_port().get_dataset_orm_class()

    existing = await session.execute(
        select(Dataset).where(Dataset.table_name == table_name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"Table '{table_name}' is already registered as a dataset.")

    # fix(#1444): registration takes a table name straight from the
    # caller instead of generate_table_name, so the retirement probe (see
    # GH-1443's disclosure) has to repeat here or it's bypassable: recreate a
    # table under a deleted public dataset's name, register it private, and a
    # worker still holding the predecessor's metadata authorizes anonymously
    # against `public` while querying the successor's rows. Refuse rather
    # than rename — registration serves from the caller's own live table.
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

    # fix(#1737): a spatial table whose geometry lives under any other name
    # used to register SILENTLY as non-spatial, since extract_metadata
    # reports srid/geometry_type/extent as None for an unrecognized column.
    # Must be told apart from the deliberate non-spatial path (#1359), where
    # a table truly has no geometry column. `ogr2ogr -f PostgreSQL` names its
    # column `wkb_geometry` by default, so this is the ordinary case.
    if not has_geom:
        other_geom = await session.execute(
            text(
                "SELECT f_geometry_column FROM geometry_columns "
                "WHERE f_table_schema = :schema AND f_table_name = :table_name "
                "LIMIT 1"
            ).bindparams(schema=_schema, table_name=table_name)
        )
        found = other_geom.scalar_one_or_none()
        if found is not None:
            raise ValueError(
                f"Table '{table_name}' stores geometry in a column named "
                f"'{found}'. GeoLens reads geometry from a column named "
                "'geom'. Rename the column, or re-export the table with "
                "`-lco GEOMETRY_NAME=geom`."
            )

    from app.processing.ingest.tasks_common import (
        _current_tenant_role,
    )

    # Per-tenant schema/role so published assets in multi_tenant land on the
    # correct reader role; no-op in single_tenant ('data'/'geolens_reader').
    _grant_role = _current_tenant_role()

    if has_geom:
        if not has_4326:
            srid = await get_table_srid(session, table_name, schema=_schema)
            # Savepoint so a partial failure (column added, index creation
            # failed) rolls back cleanly instead of a half-indexed table.
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
            # fix(#1113): a table registered after migration 0034 is
            # invisible to its backfill, so a pre-existing geom_4326 written
            # by someone else could reach readers curved, now that the
            # per-read ST_CurveToLine wraps are gone. Enforce linearity here,
            # on the write boundary, instead.
            try:
                async with session.begin_nested():
                    await linearize_existing_4326(session, table_name, schema=_schema)
            except Exception as exc:  # broad: UPDATE inside savepoint can fail for schema/permission reasons
                raise ValueError(
                    f"Failed to linearize geom_4326 on '{table_name}': {exc}"
                ) from exc

    await grant_reader_access(session, table_name, schema=_schema, role=_grant_role)

    # fix(#1359): one derivation for every registration, spatial or not — the
    # non-spatial branch used to skip this and register with column_info and
    # feature_count NULL. extract_metadata already reports srid/
    # geometry_type/extent_wkt as None for a table with no geom column.
    metadata = await extract_metadata(session, table_name, schema=_schema)

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

    # feat(#1218): registration serves from the live table, so the origin IS
    # that table — schema-qualified name only, no host/port/DSN/credential
    # (no external PostGIS federation in v1).
    #
    # fix(#1218): pass the SAME _schema this function verified,
    # granted, and extracted metadata in. Reading dataset.tenant_id instead
    # pointed every multi-tenant registration at `data.<table>`, since the
    # INSERT sends tenant_id NULL and a trigger fills it in the database —
    # the ORM attribute never sees the real value.
    set_postgis_origin(dataset, table_name, schema=_schema, managed=managed)

    return dataset


async def create_vrt_job(
    db: AsyncSession,
    request: VrtCreateRequest,
    user: Identity,
) -> IngestJob:
    """Validate source raster datasets, then create + defer a VRT creation job.

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

    if len(request.source_dataset_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least 2 source datasets are required to create a VRT",
        )

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

    found_dataset_ids = {asset.dataset_id for asset in found_assets}
    for sid in request.source_dataset_ids:
        if sid not in found_dataset_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Source dataset {sid} not found or not a raster dataset",
            )

    # Authorize EVERY source dataset before mosaicking: the worker compiles
    # all source pixels into one served asset, so a foreign private source
    # can't be filtered at read time — authorize at write/link time instead
    # (check_datasets_access_bulk raises 404). Runs before validate_sources
    # so a foreign source 404s rather than leaking a 422 about a dataset the
    # caller can't see.
    #
    # fix(#1298): batched — a 500-source request used to cost one round trip
    # per source.
    from app.modules.catalog.authorization import (
        check_datasets_access_bulk,
        get_user_roles,
    )

    user_roles = await get_user_roles(db, user)
    await check_datasets_access_bulk(db, request.source_dataset_ids, user, user_roles)

    errors = validate_sources(request.vrt_type, list(found_assets))
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[e.model_dump() for e in errors],
        )

    job = await create_ingest_job(db, f"vrt_{request.vrt_type}", "", user.id)
    job.user_metadata = {
        "vrt_type": request.vrt_type,
        "title": request.title,
        "summary": request.summary,
        "visibility": request.visibility,
    }
    await db.commit()

    # If Procrastinate is unreachable, the job row was already committed
    # as ``pending`` above — the orphan guard flips it to ``failed`` before
    # propagating so listings reflect reality instead of waiting out
    # PENDING_TIMEOUT.
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
        job=job,
    )

    return job


def _user_safe_error(exc: Exception) -> str:
    """Return a user-safe error string, stripped of absolute filesystem paths.

    Used so internal infrastructure isn't leaked in FanOutLayerResult.error.
    """
    import re

    msg = str(exc)
    msg = re.sub(r"/(?:[^/\s]+/)+[^/\s]*", "<path>", msg)  # Unix paths
    msg = re.sub(r"[A-Za-z]:\\[^\s]+", "<path>", msg)  # Windows paths
    return msg


async def create_fan_out_jobs(
    original_job: "IngestJob",
    layer: "Any",
    session: AsyncSession,
) -> "Any":
    """Clone an IngestJob for one layer and dispatch the ingest task.

    Called once per layer by the /ingest/commit-fan-out/{job_id} endpoint.
    Creates a new IngestJob pointing at the same file_path, sets
    layer_name + fan_out_parent_id in its user_metadata, then defers the
    standard ``ingest_file`` task. The Dataset row is created later by that
    task (not here), to preserve the full metadata extraction pipeline.

    Does NOT touch or remove original_job.file_path: fan-out jobs share the
    file on disk, and cleanup is keyed per fan-out job by
    ``_archive_original_file`` reading the cloned job's file_path.

    Returns FanOutLayerResult with status='queued', or status='failed' with
    an error sanitized by _user_safe_error() on exception.
    """
    from app.processing.ingest.schemas import FanOutLayerResult

    try:
        file_base = original_job.source_filename or "dataset"
        import re as _re

        file_base = _re.sub(r"\.[^.]+$", "", file_base)
        title = layer.title if layer.title else f"{file_base}: {layer.layer_name}"

        new_job = IngestJob(
            file_path=original_job.file_path,
            source_filename=original_job.source_filename,
            status="pending",
            created_by=original_job.created_by,
            user_metadata={
                **(original_job.user_metadata or {}),
                "layer_name": layer.layer_name,
                "title": title,
                "fan_out_parent_id": str(original_job.id),
                # Each fan-out job creates its own dataset in _finalize_ingest.
                "dataset_id": None,
                # fix(#1744): stamped here, not by the guard below, so it
                # rides the commit that makes the row visible. A process
                # death in the gap would leave it unstamped, and the stale
                # sweep would settle it `cancelled` — taking away the only
                # way to re-run this layer, since the layer selection lives
                # nowhere but the fan-out request body (#1709 r8).
                **commit_attempted_marker(),
            },
        )
        session.add(new_job)
        await session.flush()  # assigns new_job.id
        # COMMIT before deferring: defer_async uses a separate DB connection,
        # so an uncommitted row makes the worker log "job not found" and the
        # job stays 'pending' forever. Orphan risk on defer failure is
        # handled by defer_with_orphan_guard below.
        await session.commit()

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
            job=new_job,
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
        logger.warning(
            "Fan-out layer dispatch failed",
            layer_name=layer.layer_name,
            original_job_id=str(original_job.id),
            error=str(exc),
        )
        # fix(#1774): reset the session before returning — a
        # transactional failure in the commit above leaves the session
        # refusing every later statement, and the caller loops over remaining
        # layers on this same session then runs
        # `restore_fan_out_parent_pending`. Without the reset, one layer's
        # deadlock fails every sibling and strands the parent `fanned_out`.
        #
        # fix(#1774): reload the parent in the same
        # breath, since the reset expires it — a synchronous read of an
        # expired attribute on an AsyncSession raises MissingGreenlet, and
        # both the next layer and `restore_fan_out_parent_pending` read
        # attributes off this same instance.
        parent_job_id = str(original_job.id)
        try:
            await session.rollback()
            await session.refresh(original_job)
        except Exception:  # broad: a dead connection cannot be reset here
            logger.warning(
                "Fan-out layer session reset failed",
                layer_name=layer.layer_name,
                original_job_id=parent_job_id,
            )
        from app.processing.ingest.schemas import FanOutLayerResult

        return FanOutLayerResult(
            layer_name=layer.layer_name,
            new_job_id=None,
            dataset_id=None,
            status="failed",
            error=_user_safe_error(exc),
        )


async def claim_fan_out_parent(
    session: AsyncSession,
    job: IngestJob,
    *,
    parent_attempt_id: uuid.UUID | None,
) -> bool:
    """CAS the parent ``pending -> fanned_out`` BEFORE any child is dispatched.

    fix(#1709): an earlier shape (children first, terminal CAS
    after the loop) let a cancel commit mid-loop while an already-deferred
    fast child claimed and completed before cleanup — the child CAS refused
    the terminal row, so a 200 cancel still created that child's dataset.
    This CAS is now the mutex for the whole dispatch: it commits before the
    first child exists, so only two clean orderings remain — cancel first
    (zero children ever created, endpoint 409s, nothing to reconcile), or
    this CAS first (parent terminal, every cancel 409s, each child is its
    own individually-cancellable job). Committed here rather than riding a
    later flush, since a fence is only a fence once durable.

    Returns whether the claim landed. The caller renders the refusal.
    """
    from datetime import datetime, timezone

    from sqlalchemy import update as sa_update

    attempt_predicate = (
        IngestJob.attempt_id == parent_attempt_id
        if parent_attempt_id is not None
        else IngestJob.attempt_id.is_(None)
    )
    claim = await session.execute(
        sa_update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "pending",
            attempt_predicate,
        )
        .values(status="fanned_out", completed_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return bool(claim.rowcount)


async def restore_fan_out_parent_pending(
    session: AsyncSession,
    job: IngestJob,
    *,
    parent_attempt_id: uuid.UUID | None,
) -> bool:
    """Undo the pre-dispatch claim when EVERY layer failed to queue.

    Retry contract: an all-failed dispatch (e.g. Procrastinate outage) keeps
    the parent ``pending`` so the user can commit again without
    re-uploading. The restore is itself a fenced CAS on the attempt id,
    undoing only the flip THIS request wrote — a blind write would resurrect
    a row the round-2 fix removed that bug for.

    fix(#2016): a dispatch loop that outlives ``FAN_OUT_CHILDLESS_GRACE``
    finds the childless-fanout sweep has already settled the same row
    ``failed`` with the interrupted marker, which ``_retry_capability``
    refuses — the re-upload this restore exists to spare the user. So the CAS
    also accepts that row and drops the marker as it restores. Same row, same
    attempt, and the sweep only reached it because THIS dispatch was still
    running; the attempt fence is what keeps another attempt's ``failed`` row
    out. Only that one key is cleared, off the row's own metadata.

    Returns whether the CAS matched, so the caller can report a lost undo.
    """
    from sqlalchemy import update as sa_update

    attempt_predicate = (
        IngestJob.attempt_id == parent_attempt_id
        if parent_attempt_id is not None
        else IngestJob.attempt_id.is_(None)
    )
    restored = await session.execute(
        sa_update(IngestJob)
        .where(
            IngestJob.id == job.id,
            or_(
                IngestJob.status == "fanned_out",
                and_(
                    IngestJob.status == "failed",
                    IngestJob.user_metadata[FAN_OUT_INTERRUPTED_METADATA_KEY].astext
                    == "true",
                ),
            ),
            attempt_predicate,
        )
        .values(
            status="pending",
            completed_at=None,
            error_message=None,
            user_metadata=IngestJob.user_metadata.op("-")(
                literal(FAN_OUT_INTERRUPTED_METADATA_KEY, String)
            ),
        )
    )
    await session.commit()
    return bool(restored.rowcount)


def job_service_format(job: IngestJob) -> str | None:
    """The canonical service format this job's origin resolves to, or None.

    None for an unrecognized label: composes no header, so the credential
    degrades to the bare token the ArcGIS path takes, and the worker is left
    to report what it couldn't read.
    """
    from app.processing.ingest.ogr import IngestionError
    from app.processing.ingest.tasks import resolve_service_type

    try:
        _, source_format = resolve_service_type(
            str((job.user_metadata or {}).get("service_type") or "")
        )
    except IngestionError:
        return None
    return source_format


def _assert_header_token_dispatchable(job: IngestJob, token: str | None) -> None:
    """fix(#1746): refuse a header-auth token the worker is going to reject.

    The import-commit door used to hand any printable, whitespace-free token
    straight to ``resolve_dispatch_credential``; a WFS/OGC API token
    containing ``+`` or ``/`` got a 202, spent its single-use credential,
    then failed deterministically inside ogr2ogr's own charset check. Same
    422 and policy-only message the refresh door has returned since #1277 —
    a response body must never echo part of a credential.

    ArcGIS is exempt (``requires_header_token_policy``'s call): its token is
    a urlencoded query parameter, never a header line, so the strict charset
    doesn't apply. Judges the BARE token only, which is what
    ``ServiceCommitRequest`` carries; composition into a wire value happens
    in ``queue_ingest_job``.
    """
    if not token:
        return
    if not requires_header_token_policy(job_service_format(job)):
        return
    rejection = header_token_rejection_reason(token)
    if rejection is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_service_token", "message": rejection},
        )


async def queue_ingest_job(
    job: IngestJob,
    user_id: str,
    *,
    db: AsyncSession,
    token: str | None = None,
    credential: ServiceCredential | None = None,
) -> None:
    """Route a committed ingest job to the right Procrastinate task.

    Chooses between ``ingest_service`` (source_url set), ``ingest_raster``
    (file_type=raster), and ``ingest_file`` (default vector path), and sends
    small vector files to the priority queue.

    Each ``defer_async`` call is wrapped in ``defer_with_orphan_guard`` so a
    queue outage flips the committed pending job to ``failed`` and surfaces
    HTTP 503.

    Raises ``HTTPException 400`` when the job has no file_path and no
    source_url. Raises ``HTTPException 503`` when Procrastinate is
    unreachable, or a configured credential store can't be reached to stage
    a service token (see ``resolve_dispatch_credential``).

    feat(#1746) D2: ``credential`` is the structured spelling of the same
    thing as ``token``, so a caller with no HTTP layer (e.g. an overlay
    scheduler holding a resolved stored credential) can queue an
    authenticated ingest without assembling a request body. Wins over
    ``token`` when both are set. A method the job's service can't carry is
    refused with 422 ``unsupported_auth_method`` rather than dispatched
    unauthenticated — for ArcGIS that means only a username/password or a
    named API key, since that transport has room for a token and nothing else.
    """
    import os

    from app.platform.service_auth import (
        bearer_credential,
        wire_credential,
    )

    from app.platform.refresh.credentials import (
        CredentialStoreUnavailable,
        discard_service_credential,
        resolve_dispatch_credential,
    )
    from app.processing.ingest.constants import PRIORITY_QUEUE_THRESHOLD_BYTES
    from app.processing.ingest.tasks import ingest_file, ingest_raster, ingest_service

    if job.source_url and not job.file_path:
        # Capture source_url into a local so mypy preserves the ``str``
        # narrowing inside the nested closure.
        source_url = job.source_url
        job_failed = make_ingest_job_failed_rollback(job)

        # fix(#1746): before the stash below, so a token the worker will
        # refuse never burns a single-use credential.
        #
        # fix(#1746): only when the flat token is the
        # credential actually sent — the structured `credential` wins over
        # `token` when both are given, so checking the losing one could
        # refuse an in-process D2 caller for a stale token it already
        # replaced. `wire_credential` below applies the same rule to
        # whichever spelling is actually dispatched.
        if credential is None:
            _assert_header_token_dispatchable(job, token)

        # feat(#1746) plan D9: what crosses to the worker under `token` is
        # one finished header line for the two header-auth formats, or the
        # bare token for ArcGIS — composed here since the queue hop has no
        # later site to compose it, from whichever spelling the caller used.
        service_format = job_service_format(job)
        token = wire_credential(
            credential if credential is not None else bearer_credential(token),
            service_format=service_format,
        )

        # feat(#1676): the import door's half of the lease. With a shared
        # credential store this returns (None, ref) and the secret never
        # becomes a task argument; without one it returns the token
        # unchanged. resolve_dispatch_credential owns that whole decision,
        # so this door can't drift from the re-upload one.
        credential_ref: str | None = None
        try:
            token, credential_ref = await resolve_dispatch_credential(
                token, door="import"
            )
        except CredentialStoreUnavailable as exc:
            # The job row is already committed (commit_import commits before
            # dispatching), so a bare raise would strand it until the stale
            # sweep. Finalize it as the orphan guard would, then 503.
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
            task = ingest_service
            await defer_async_with_tenant(
                task,
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                source_url=source_url,
                source_layer=job.source_layer or "",
                user_id=user_id,
                token=token,
                # fix(#1689): ROLLING-DEPLOY SKEW, accepted like
                # #1220 accepted it at the refresh door. A previous-generation
                # worker takes `credential_ref` through `**kwargs`, discards
                # it, fetches unauthenticated, and fails the job blaming the
                # origin. The alternative — a task name old workers don't
                # register — is worse: Procrastinate fails its own job on
                # TaskNotFound without writing the ingest_jobs row, so it
                # hangs `pending` until the stale-job sweep, which reads
                # worse than a retriable failure. Narrower window than the
                # refresh door too: a storeless install dispatches no
                # reference at all, so only a REDIS_URL install mid-rollout
                # on a token-bearing import is exposed, and single-node
                # compose deploys never overlap generations. Nothing strands:
                # the old worker fails the job and the credential dies by TTL.
                credential_ref=credential_ref,
            )

        async def _rollback_service(defer_exc: BaseException) -> None:
            await job_failed(defer_exc)
            # Best-effort: the TTL is the real guarantee, this just shortens
            # a window nothing will use.
            await discard_service_credential(credential_ref)

        await defer_with_orphan_guard(
            _defer_service,
            rollback=_rollback_service,
            db=db,
            job=job,
        )
        return

    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no file_path and no source_url — cannot queue ingest",
        )
    file_path = job.file_path

    if (job.user_metadata or {}).get("file_type") == "raster":

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
            job=job,
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
        job=job,
    )
