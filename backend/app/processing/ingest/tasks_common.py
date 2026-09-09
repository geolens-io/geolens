"""Shared helpers, dataclasses, and app configuration for ingest tasks.

Contains the Procrastinate App instance, shared dataclasses (IngestContext,
StagingResult), job lifecycle helpers, metadata extraction utilities,
validation, and the finalize pipeline used across vector, raster, VRT,
and reupload workflows.
"""

import asyncio
import functools
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from app.core.async_io import await_draining, run_in_thread_draining

from procrastinate import App, PsycopgConnector

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import classify_origin, set_dataset_origin
from app.core.config import settings
from app.core.service_tokens import reset_registered_credential_secrets
from app.core.url_redaction import redact_exception_text, redact_url_credentials
from app.processing.embeddings.helpers import defer_embedding
from app.processing.ingest.source_format import derive_source_format
from app.platform.storage import get_storage

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.processing.ingest.warnings import IngestJobWarning
    from app.platform.jobs.models import IngestJob


def _current_tenant_schema() -> str:
    """Return the data schema for the current tenant (or 'data' in single_tenant).

    Reads ``current_tenant_var`` and delegates to ``tenant_data_schema`` which
    is a hard no-op returning ``'data'`` in single_tenant mode.
    Called by ingest task helpers to route CREATE/RENAME/DROP/GRANT statements
    to the correct per-tenant schema (DP-01, Phase 1209-02).
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tenant_id = current_tenant_var.get()
    if is_multi_tenant() and tenant_id is None:
        raise RuntimeError("Ingest task is missing tenant context in multi-tenant mode")
    return tenant_data_schema(tenant_id)


async def rename_pkey_to_match_table(session: "AsyncSession", table_name: str) -> None:
    """Rename a just-published table's PK constraint to ``<table>_pkey``.

    ALTER TABLE ... RENAME TO keeps the constraint (and its backing index)
    named after the attempt-scoped staging table (``*_staging_<uuid>_pkey``),
    which is what QGIS/pgAdmin/DBeaver users see on a direct connection
    (db-audit #529). Call inside the publish transaction, which already
    holds the table's AccessExclusiveLock from the rename, so this cannot
    block. Failure is cosmetic and must never fail the ingest — it is
    swallowed under a SAVEPOINT and logged.
    """
    from sqlalchemy import text

    from app.processing.ingest.metadata import _qtable, _sql_quote_ident

    schema = _current_tenant_schema()
    desired = f"{table_name[:58]}_pkey"
    try:
        async with session.begin_nested():
            result = await session.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_class c ON c.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :tn "
                    "AND con.contype = 'p'"
                ),
                {"schema": schema, "tn": table_name},
            )
            current = result.scalar()
            if current and current != desired:
                await session.execute(
                    text(
                        f"ALTER TABLE {_qtable(table_name, schema=schema)} "
                        f"RENAME CONSTRAINT {_sql_quote_ident(current)} "
                        f"TO {_sql_quote_ident(desired)}"
                    )
                )
    except Exception:  # broad: cosmetic rename must never fail the publish
        structlog.get_logger().warning(
            "pkey_rename_failed",
            table_name=table_name,
            schema=schema,
            exc_info=True,
        )


def _current_tenant_role() -> str:
    """Return the reader role for the current tenant (or 'geolens_reader' in single_tenant).

    Reads ``current_tenant_var`` and delegates to ``tenant_reader_role`` which
    is a hard no-op returning ``'geolens_reader'`` in single_tenant mode.
    Called by ingest task helpers to GRANT SELECT to the correct per-tenant
    reader role (DP-01, Phase 1209-02).
    """
    from app.core.db.tenant_schema import tenant_reader_role
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tenant_id = current_tenant_var.get()
    if is_multi_tenant() and tenant_id is None:
        raise RuntimeError("Ingest task is missing tenant context in multi-tenant mode")
    return tenant_reader_role(tenant_id)


async def _emit_billing_event(
    tenant_id: str | None,
    dimension: str,
    value: int = 1,
    *,
    event_id: str | None = None,
    table_name: str | None = None,
) -> None:
    """Dispatch a billable usage event to registered BillingExtensions (METER-01).

    Imports ONLY ``get_billing_extensions`` from ``app.platform.extensions`` —
    zero billing/stripe symbols enter core (T-1213-06); no-op in OSS/
    single_tenant since ``DefaultBillingExtension`` has no ``on_usage_event``.
    Each extension call is wrapped in try/except that logs and continues:
    a failing billing extension must never fail an ingest task (T-1213-05).
    ``tenant_id`` comes from the worker's ``current_tenant_var`` (set by
    middleware), never client input (T-1213-07 spoofing).

    Args:
        tenant_id: None (single_tenant, or context unset) returns immediately.
        dimension: e.g. ``'ingest_jobs'``, ``'raster_egress_bytes'``.
        value: event magnitude; use byte count for egress dimensions.
        event_id: dedup key — pass the Procrastinate job_id so retries stay
            idempotent at the DB layer.
        table_name: workers leave this None; the tile/OGC request path
            passes it to drive the METER-03 last_accessed_at signal.
    """
    if not tenant_id:
        return  # single_tenant no-op: no ledger, no billing (byte-identical OSS)

    # Billing-import-free: only import the extension accessor, never billing symbols
    from app.platform.extensions import get_billing_extensions

    _log = structlog.get_logger()
    for ext in get_billing_extensions():
        if not hasattr(ext, "on_usage_event"):
            continue  # DefaultBillingExtension + other extensions without the hook
        try:
            await ext.on_usage_event(  # type: ignore[attr-defined]
                tenant_id=tenant_id,
                dimension=dimension,
                value=value,
                event_id=event_id,
                table_name=table_name,
            )
        except Exception:  # broad: billing emit must NEVER fail an ingest task; varied extension errors
            # Per-extension isolation — mirrors lifespan dispatch D-10 pattern
            # (api/main.py bootstrap.py). Log and continue to next extension.
            _log.warning(
                "billing_emit_error",
                dimension=dimension,
                tenant_id=tenant_id,
                ext=type(ext).__name__,
                exc_info=True,
            )


@dataclass
class IngestContext:
    """Bundle of parameters shared across the post-ogr2ogr finalize pipeline.

    KISS-2 / K7: ``_finalize_ingest`` used to take 11 keyword-only
    parameters, which made every call site noisy and hard to keep in sync.
    Collecting them in a dataclass keeps the call sites terse and adds a
    single obvious place to add future finalize inputs.
    """

    session: "AsyncSession"
    job: "IngestJob"
    table_name: str
    user_id: str
    has_geometry: bool | None
    effective_srid: int | None
    source_format: str
    source_filename: str | None
    original_srid: int | None
    user_metadata: dict[str, Any]
    source_url: str | None = None
    attempt_id: uuid.UUID | None = None
    # feat(#1218): typed origin_ref for the created dataset, minus `kind`
    # (derived from source_format). Keys are validated against the
    # per-kind allowlist in app/platform/dataset_origin.py, so nothing
    # unexpected — a credential most of all — reaches the column. Callers
    # pass their own payload rather than one being inferred here.
    origin_ref: dict[str, Any] | None = None


@dataclass
class StagingResult:
    """Intermediate staging outputs before dataset creation."""

    metadata: dict
    sample_values: dict
    three_d: dict
    has_geometry: bool
    geometry_type: str | None
    # fix(#888): clip_to_mercator_bounds accounting, so the caller (which owns
    # the job row) can warn the user about geometry the clamp destroyed.
    mercator_clip: dict | None = None


_connector_kwargs: dict = {
    "min_size": 1,
    "max_size": 3,
    "kwargs": {"connect_timeout": 5},
}
if settings.db_use_external_pooler:
    _connector_kwargs["kwargs"]["prepare_threshold"] = None

task_app = App(
    connector=PsycopgConnector(
        conninfo=settings.procrastinate_conninfo,
        **_connector_kwargs,
    ),
    import_paths=[
        "app.processing.ingest.tasks_vector",
        "app.processing.ingest.tasks_raster",
        "app.processing.ingest.tasks_vrt",
        "app.processing.ingest.tasks_reupload",
        "app.processing.embeddings.tasks",
        "app.processing.analysis.tasks",
        # fix(#1542): the queued admin embedding backfill. It lives under
        # modules/admin/ because it emits the run's audit events, which
        # processing/ may not import; this list is how the worker finds it.
        "app.modules.admin.backfill_jobs",
    ],
)


# fix(#1746): without a credential store, service tasks are dispatched with
# the raw token in job kwargs; the worker only deletes SUCCESSFUL rows, so a
# terminal failure leaves it in `procrastinate_jobs.args->>'token'`
# indefinitely.
async def purge_queued_job_token(job_context: Any) -> None:
    """Best-effort: drop `token` from the running job's own queue row.

    Takes the Procrastinate ``JobContext`` (not a bare id) so a direct call
    passing ``None`` is a no-op instead of an error.

    Never raises — runs while a real failure is being handled, and
    displacing that exception would cost the diagnosis. The warning logs
    only the row id, never the value it failed to remove.
    """
    row_id = getattr(getattr(job_context, "job", None), "id", None)
    if row_id is None:
        return
    from app.core.db import async_session
    from app.platform.jobs.sweep import purge_queue_row_tokens

    try:
        async with async_session() as session:
            await purge_queue_row_tokens(session, [row_id])
    except Exception:  # broad: a purge failure must not replace the real one
        structlog.get_logger().warning(
            "queued_job_token_purge_failed", procrastinate_job_id=row_id
        )


def purge_token_on_failure(fn):
    """Wrap a ``pass_context=True`` task so a dying attempt purges its token.

    Applied UNDER ``@tenant_task`` so the purge runs with the job's tenant
    context still bound. Absorbs the ``JobContext`` Procrastinate passes
    positionally, keeping the task's own keyword-only call shape unchanged —
    a direct caller (tests, ``.func``) supplies no context, so there's no
    row to purge and the wrapper is transparent.

    Catches ``Exception``, not ``BaseException``: a cancelled attempt
    (worker shutdown) leaves the row `doing`, not terminal, and
    ``platform/jobs/sweep.py`` is the backstop for settling it later.
    """

    @functools.wraps(fn)
    async def _wrapper(job_context: Any = None, /, **kwargs: Any) -> Any:
        try:
            return await fn(**kwargs)
        except Exception:  # broad: every terminal failure strands the token
            await purge_queued_job_token(job_context)
            raise

    return _wrapper


@asynccontextmanager
async def cleanup_step(what: str, *, job_id: str) -> AsyncGenerator[None, None]:
    """Run one terminal-cleanup step; log a failure in it rather than raise it.

    fix(#1755): a `finally`-block cleanup step must never replace the
    exception the block is already propagating, and must not skip the steps
    after it — wrap ONE step per `async with`; isolation is per block, not
    per `finally`.

    Catches ``Exception``, not ``BaseException``, so a worker-shutdown
    ``CancelledError`` still propagates.

    ``what`` names the step for the operator and is logged verbatim, so
    keep it a fixed string. The failure log redacts its message since an
    ingest exception can carry a credentialed URL.
    """
    try:
        yield
    except (
        Exception
    ) as exc:  # broad: cleanup must not replace the exception it runs past
        structlog.get_logger().exception(
            "ingest_cleanup_step_failed",
            step=what,
            job_id=job_id,
            error=redact_exception_text(exc),
        )


# ArcGIS esriFieldType → column_info type mapping
_ARCGIS_TYPE_MAP = {
    "esriFieldTypeString": "text",
    "esriFieldTypeSmallInteger": "integer",
    "esriFieldTypeInteger": "integer",
    "esriFieldTypeSingle": "real",
    "esriFieldTypeDouble": "double precision",
    "esriFieldTypeDate": "timestamp without time zone",
    "esriFieldTypeOID": "integer",
    "esriFieldTypeGlobalID": "text",
    "esriFieldTypeGUID": "text",
    "esriFieldTypeBlob": "text",
    "esriFieldTypeXML": "text",
}


def _arcgis_type_to_column_type(esri_type: str) -> str:
    """Map an ArcGIS esriFieldType string to a PostgreSQL column type name."""
    return _ARCGIS_TYPE_MAP.get(esri_type, "text")


def _append_job_warning(job, warning: "IngestJobWarning") -> None:
    """Append a structured warning to ``job.user_metadata['warnings']``.

    Mutates ``job.user_metadata`` in place, creating the list if absent.
    Caller is responsible for committing the session. ``warning`` is a
    TypedDict from ``app.ingest.warnings.IngestJobWarning`` — route through
    that module's producer helpers rather than building one inline, to keep
    this in sync with the Pydantic ``JobStatusResponse`` (TYPE-1).
    """
    warnings_list = list((job.user_metadata or {}).get("warnings", []))
    warnings_list.append(warning)
    job.user_metadata = {
        **(job.user_metadata or {}),
        "warnings": warnings_list,
    }


def _append_mercator_clip_warning(job, clip: dict | None) -> None:
    """Warn when the Web Mercator clamp destroyed geometry (fix(#888)).

    ``clip`` is the ``clip_to_mercator_bounds`` return value. No-ops for the
    no-loss clip that every ordinary dataset produces, so each of the three
    ingest call sites stays a single unconditional statement.
    """
    from app.processing.ingest.warnings import make_mercator_clip_warning

    warning = make_mercator_clip_warning(clip)
    if warning is not None:
        _append_job_warning(job, warning)


def _parse_temporal_fields(
    *,
    temporal_start: str | None,
    temporal_end: str | None,
) -> tuple["date | None", "date | None", dict[str, str]]:
    """Parse raster ingest temporal fields, returning (start, end, errors).

    Each field is ISO-8601-parsed independently. A field that fails to
    parse is dropped from the return tuple but recorded in ``errors``
    (keyed by field name, value truncated to 100 chars) so the caller can
    persist it to ``job.user_metadata.temporal_parse_errors`` for the UI (N5).
    """
    from datetime import date as _date

    logger = structlog.get_logger()
    parsed_start: date | None = None
    parsed_end: date | None = None
    errors: dict[str, str] = {}

    if temporal_start:
        try:
            parsed_start = _date.fromisoformat(temporal_start)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Ignoring unparseable temporal_start on raster ingest",
                raw_value=str(temporal_start)[:100],
                error=str(exc),
            )
            errors["temporal_start"] = str(temporal_start)[:100]

    if temporal_end:
        try:
            parsed_end = _date.fromisoformat(temporal_end)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Ignoring unparseable temporal_end on raster ingest",
                raw_value=str(temporal_end)[:100],
                error=str(exc),
            )
            errors["temporal_end"] = str(temporal_end)[:100]

    return parsed_start, parsed_end, errors


def apply_manifest_record_metadata(record: Any, user_metadata: dict | None) -> None:
    """Copy manifest-supplied catalog metadata onto a freshly created record.

    ``record`` is duck-typed rather than annotated ``Record``: importing the
    catalog ORM class here would add a ``processing`` -> ``modules.catalog``
    edge, which ``ProcessingPort`` exists to keep out.

    feat(#1472): the read-back for ``manifest_job_metadata``'s
    ``metadata.attribution`` write, called once per ingest tail after the
    record exists and before the phase transaction commits — without it an
    operator-supplied attribution credit was accepted then silently dropped.

    Only manifest-namespaced keys are copied; un-namespaced ``title``/
    ``summary``/``visibility`` go through ``create_dataset``'s own
    arguments, since non-manifest ingests set those too and this helper
    must be a no-op for them.
    """
    if not user_metadata:
        return
    attribution = user_metadata.get("manifest_attribution")
    if isinstance(attribution, str) and attribution.strip():
        record.attribution = attribution.strip()


@asynccontextmanager
async def _job_phase_session(
    job_uuid: uuid.UUID,
    *,
    phase: str,
    attempt_id: uuid.UUID | None = None,
    lock_and_statement_timeout_ms: int | None = None,
    require_status: str | None = None,
) -> "AsyncGenerator[tuple[AsyncSession, IngestJob | None], None]":
    """Two-phase session bracket for ingest workers (REMED-03 / P2-05).

    Yields ``(session, job)``; ``job`` is ``None`` if the IngestJob row
    vanished between phases (caller should early-return; this logs and
    continues rather than raising). ``phase`` labels that warning. Caller
    owns commits. Session lifetime is scoped to the ``async with`` block —
    CPU/subprocess work must happen outside it (the #100 greenlet rule; see
    ``ingest_file`` / ``ingest_raster`` docstrings).

    ``lock_and_statement_timeout_ms``, if given, issues ``SET LOCAL
    lock_timeout``/``statement_timeout`` before the SELECT.

    fix(#1778): pass ``require_status="running"`` at any phase that must not
    resume after a stale-job sweep has failed the row — a worker that was
    only paused (not dead) can still hold a matching ``attempt_id`` and
    resume into a terminal row otherwise. This also switches the SELECT to
    ``FOR NO KEY UPDATE``, holding the row lock until commit so the
    ``SELECT ... FOR UPDATE SKIP LOCKED`` passes in sweep.py and worker.py's
    startup recovery exclude this row instead of racing it. Leave ``None`` for
    phase 1 (before the row reaches ``running``) or ``error_write`` (must
    record regardless of status: a raster tail's object-storage put is not
    undone by any rollback).
    """
    from app.core.db import async_session
    from app.platform.jobs.models import IngestJob
    from sqlalchemy import select, text

    async with async_session() as session:
        if lock_and_statement_timeout_ms is not None:
            # `SET LOCAL` takes a literal, not a bind parameter (Postgres
            # rejects `SET x = $1`); this interpolates an integer the caller
            # computed from a module constant, never request-supplied data.
            await session.execute(
                text(f"SET LOCAL lock_timeout = {lock_and_statement_timeout_ms}")
            )
            await session.execute(
                text(f"SET LOCAL statement_timeout = {lock_and_statement_timeout_ms}")
            )
        filters = [IngestJob.id == job_uuid]
        if attempt_id is not None:
            filters.append(IngestJob.attempt_id == attempt_id)
        if require_status is not None:
            filters.append(IngestJob.status == require_status)
        stmt = select(IngestJob).where(*filters)
        if require_status is not None:
            # fix(#1778): held through this phase's own first
            # irreversible write and up to its next commit — see the
            # docstring above.
            stmt = stmt.with_for_update(key_share=True)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            structlog.get_logger().warning(
                "Ingest job not found in phase, skipping",
                job_id=str(job_uuid),
                phase=phase,
                require_status=require_status,
            )
            try:
                yield session, None
            except Exception:  # broad: rollback before re-raising to avoid a pool leak
                await session.rollback()
                raise
            return
        try:
            yield session, job
        except Exception:  # broad: rollback before re-raising to avoid a pool leak
            await session.rollback()
            raise


def _bind_task_log_context(*, task_name: str, job_id: str, **extra: object) -> None:
    """Bind structlog contextvars for a worker task entry point (N1/R-18/R-24).

    Procrastinate tasks run outside the request loop and so lack the
    ``request_id`` the HTTP middleware binds; ``job_id`` is the correlation
    key instead, letting operators filter concurrent ingests to one job's
    events. Clears stale vars first so a re-used worker can't leak a prior
    job's context.
    """

    structlog.contextvars.clear_contextvars()
    # fix(#1770): also resets the credential-secret registry
    # (`core/service_tokens.register_credential_secret`) — otherwise a
    # prior job's registered secret lingers and mis-scrubs a later job's
    # log lines.
    reset_registered_credential_secrets()
    structlog.contextvars.bind_contextvars(
        service="worker",
        task=task_name,
        job_id=job_id,
        **extra,
    )


# File formats whose missing CRS declaration conventionally means EPSG:4326
# (lon/lat). Anything else with geometry but no detectable CRS must fail (or
# carry a user srid_override) instead of silently assuming 4326. Shared by
# ingest_file and reupload_file (fix(#541): reupload lacked the gate).
ASSUMES_4326_SUFFIXES = (".csv", ".geojson", ".json", ".xlsx", ".xls")


def check_missing_crs(
    *,
    file_path: str,
    has_geometry: bool,
    detected_srid: int | None,
    srid_override: int | None,
) -> str | None:
    """Missing-CRS gate: the error message when a spatial source declares no
    CRS and the user gave no override, or None when ingest may proceed."""
    if not has_geometry or detected_srid is not None or srid_override is not None:
        return None
    if file_path.lower().endswith(ASSUMES_4326_SUFFIXES):
        return None
    return (
        "Missing CRS: no coordinate system detected. "
        "Ensure the file includes CRS information "
        "(e.g., .prj file for Shapefiles) or provide an SRID override."
    )


async def reap_downloaded_staging_source(
    job_id: str,
    *,
    original_file_path: str,
    final_status: str,
    failed_source_replayable: bool,
    is_fan_out_child: bool = False,
) -> None:
    """Delete the storage object this task DOWNLOADED its source from.

    fix(#430): without this the `staging/{job_id}/` key a task downloaded
    from lives forever when a run fails before creating a dataset.

    fix(#1213): after a presigned completion, `original_file_path` is the
    FROZEN copy, not the client-writable original. This reaps the frozen
    object; `reap_presigned_staging_object` reaps the client's key. Both
    are required — shared between vector and reupload tails so they can't
    drift (reupload previously shipped without this reaper).

    fix(#1213): the reap signal is the `staging/` PREFIX on
    `original_file_path`, not `file_path != original_file_path` — a
    download that raises never performs that rewrite, so the equality
    check skipped reaping on exactly the error path, leaking a possibly
    multi-GB frozen snapshot. The prefix alone is a sound discriminator:
    only a presigned completion (S3-only) produces a `staging/`-shaped
    path. Fan-out children are skipped (siblings share the original; a
    retention policy reaps those).

    fix(#1213): `failed_source_replayable` is required, not defaulted, so
    each caller states whether a FAILED job may be reaped. Ordinary
    imports pass True and retain on failure (`_retry_capability` in
    `platform/jobs/router.py` allows retrying them while the object still
    exists); the reupload caller passes False because `_retry_capability`
    refuses reupload jobs outright, so nothing else will ever reap them.

    Never raises — a failed sweep leaves an orphan, which beats failing a
    job whose work is already committed.
    """
    if final_status not in ("complete", "failed"):
        return
    if final_status == "failed" and failed_source_replayable:
        return
    if is_fan_out_child or not original_file_path.startswith("staging/"):
        return
    try:
        from app.platform.storage import get_storage
        from app.platform.storage.titiler_url import resolve_current_storage_key

        await await_draining(
            get_storage().delete(resolve_current_storage_key(original_file_path))
        )
    except (
        BaseException
    ):  # broad: terminal cleanup must complete through cancellation (KISS-N9)
        structlog.get_logger().warning(
            "Failed to delete staging source object",
            job_id=job_id,
            storage_key=original_file_path,
        )


async def reap_presigned_staging_object(
    job_id: str, owned_staging_key: str | None, *, final_status: str
) -> None:
    """Best-effort delete of a job's OWN presigned staging object.

    fix(#1202): a completed presigned upload points ``file_path`` at the
    frozen copy, so a reaper keyed off ``file_path`` misses the staging key
    the client's PUT URL can still recreate outside size/quota accounting.
    Called by every terminal task tail.

    Pass the result of ``owned_presigned_staging_key``, which declines a
    fan-out child's inherited parent key so a child can't reap the
    original its siblings still read.

    Never raises — a failed sweep leaves an orphan, better than failing a
    job whose work is already committed.
    """
    # fix(#1207): terminal-status guard lives HERE, not per tail — a
    # non-terminal exit (missing job/dataset, lost heartbeat claim) must not
    # sweep, since the attempt may be re-claimed and still need these bytes.
    if final_status not in ("complete", "failed") or not owned_staging_key:
        return
    try:
        from app.platform.storage import get_storage
        from app.platform.storage.titiler_url import resolve_current_storage_key

        await await_draining(
            get_storage().delete(resolve_current_storage_key(owned_staging_key))
        )
    except (
        BaseException
    ):  # broad: terminal cleanup must complete through cancellation (KISS-N9)
        structlog.get_logger().warning(
            "Failed to delete presigned staging object",
            job_id=job_id,
            storage_key=owned_staging_key,
        )


async def _validate_upload_file_safety(
    session,
    *,
    file_path: str,
    source_filename: str | None,
) -> None:
    """Run the three-step upload-safety gauntlet before ogr2ogr touches a file.

    - content validation (magic bytes, extension match, CSV parse)
    - size validation (against the persistent_config max)
    - ZIP-container bomb / path-traversal validation

    Shared by ``ingest_file``, ``reupload_file``, and ``ingest_raster``
    (KISS-3/5/6 consolidation). Raises ``ValueError`` on any check so
    each caller can map to its own job-failure handling.
    """
    from app.processing.ingest.validation import (
        validate_file_content,
        validate_file_size,
        validate_archive_safety,
        validate_content_directives,
    )
    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

    # validate_file_content wants a non-None filename for extension parsing;
    # fall back to the file's own basename so the content-check still runs.
    effective_filename = source_filename or Path(file_path).name
    validate_file_content(file_path, effective_filename)
    validate_file_size(file_path, max_size_mb * 1024 * 1024)
    validate_archive_safety(file_path, effective_filename)
    # fix(#1846, GHSA-hrf5-v3cq-frx5): what the file says to do is as much a
    # property of the upload as its shape is. Off the event loop: the linear
    # schema walk is still real work on a request thread.
    await run_in_thread_draining(
        validate_content_directives, file_path, effective_filename
    )


def _resolve_effective_srid(
    *,
    detected_srid: int | None,
    srid_override: int | None,
) -> int:
    """Decide which SRID to feed to ``add_4326_column``.

    User override takes precedence, otherwise the detected source SRID,
    otherwise 4326 (safe default for GeoJSON/CSV). K1/KISS-3 extraction from
    ``ingest_file``. Callers in non-spatial paths should not invoke this
    helper — the fallback only makes sense when the caller has already
    decided a geometry column will exist.
    """
    if srid_override is not None:
        return int(srid_override)
    if detected_srid is not None:
        return int(detected_srid)
    return 4326


async def _detect_and_override_geometry(
    session,
    *,
    table_name: str,
    user_metadata: dict[str, Any],
    effective_srid: int,
) -> str | None:
    """Apply user x/y or WKT geometry overrides to a freshly-loaded table.

    Runs ``construct_point_geometry`` or ``construct_wkt_geometry`` when the
    user supplied ``x_column + y_column`` or ``geom_column`` in the commit
    metadata. Returns the geometry type string the caller should use in place
    of the ogrinfo-detected value (or ``None`` if neither override is set —
    callers guard on ``user_wants_geom`` so this branch is defensive only).

    Callers are responsible for importing the file as non-spatial (see the
    ``ogr_geometry_type = None if user_wants_geom else ...`` branch in
    ``ingest_file``) before invoking this helper. K1/KISS-3 extraction.
    """
    from app.processing.ingest.metadata import _qtable

    x_column = (user_metadata.get("x_column") or "").lower() or None
    y_column = (user_metadata.get("y_column") or "").lower() or None
    geom_column = (user_metadata.get("geom_column") or "").lower() or None

    if x_column and y_column:
        from app.processing.ingest.metadata import construct_point_geometry

        await construct_point_geometry(
            session,
            table_name,
            x_column,
            y_column,
            effective_srid,
            schema=_current_tenant_schema(),
        )
        return "Point"

    if geom_column:
        from sqlalchemy import text as _text

        from app.processing.ingest.metadata import construct_wkt_geometry

        await construct_wkt_geometry(
            session,
            table_name,
            geom_column,
            effective_srid,
            schema=_current_tenant_schema(),
        )
        # Re-detect geometry type from the constructed column so downstream
        # metadata reflects what was actually built (lines/polygons/etc).
        result = await session.execute(
            _text(
                f"SELECT GeometryType(geom) FROM {_qtable(table_name, schema=_current_tenant_schema())} "
                f"WHERE geom IS NOT NULL LIMIT 1"
            )
        )
        geometry_type = result.scalar_one_or_none() or "Geometry"
        return geometry_type

    return None


async def _archive_original_file(
    session,
    *,
    job,
    dataset_id,
    file_path: str,
    log_message: str = "Failed to archive original file to storage",
    commit: bool = True,
    archive_name: str | None = None,
) -> bool:
    """Upload the original source file to the storage provider (best-effort).

    Returns True when the archive landed. fix(#1290): raster tails call this
    to satisfy ADR-002 Decision 7 when a conversion was lossy and must not
    delete the staged upload unless the durable copy exists — for them the
    return value is a decision input, not just a breadcrumb. Vector callers
    ignore it.

    Archive failures must NOT fail the ingest (the dataset is already
    committed) — instead the failure is recorded on ``job.user_metadata``
    for UI/operator audit (R-2). ``commit=False`` lets ``reupload_file``'s
    caller fold that metadata write into its own ``job.status="complete"``
    commit instead of a second round trip.

    When ``commit`` is True, the metadata-update commit is wrapped in its
    own try/except: a transient DB error there must not flip an
    already-successful ingest into a ``failed`` job — on failure this logs
    and gives up, and the operator just loses the ``archive_failed``
    breadcrumb.
    """

    logger = structlog.get_logger()
    # fix(#1290): `file_path` is a temp download on any object-store
    # deployment, so deriving the name from it archives the upload under a
    # generated filename nobody recognises. Callers that know what the user
    # actually uploaded pass it.
    archive_key = f"originals/{dataset_id}/{archive_name or Path(file_path).name}"
    try:
        from app.core.db.tenant_session import current_tenant_var
        from app.platform.storage.titiler_url import resolve_storage_key

        storage = get_storage()
        physical_archive_key = resolve_storage_key(
            archive_key, tenant_id=current_tenant_var.get()
        )
        with open(file_path, "rb") as fobj:
            await storage.put(physical_archive_key, fobj)
        return True
    except Exception as archive_exc:  # broad: archive is best-effort; S3/local I/O can fail for any reason
        logger.warning(
            log_message,
            archive_key=archive_key,
            dataset_id=str(dataset_id),
            error=str(archive_exc)[:500],
        )
        job.user_metadata = {
            **(job.user_metadata or {}),
            "archive_failed": True,
            "archive_error": str(archive_exc)[:500],
        }
        if not commit:
            return False
        try:
            await session.commit()
        except Exception as commit_exc:  # broad: transient DB errors (deadlock, pooler drop) during flag persistence
            await session.rollback()
            logger.warning(
                "Failed to persist archive_failed flag on job",
                archive_key=archive_key,
                dataset_id=str(dataset_id),
                error=str(commit_exc)[:500],
            )
        return False


async def run_paged_arcgis_service_fetch(
    *,
    service_type_raw: str,
    service_type: str,
    source_url: str,
    layer_name: str,
    layer_id: "int | str | None",
    token: "str | None",
    staging_table: str,
    db_conn_str: str,
    schema: str,
    feature_count: int,
    page_size: int,
    order_field: str,
    is_non_spatial: bool = False,
    on_spawn: Any = None,
    on_page: Any = None,
) -> None:
    """Guarded resultOffset paging for an ArcGIS FeatureServer fetch.

    fix(#1675): shared by initial import and the refresh/reupload executor
    so both distrust driver-side paging the same way — a page that makes
    no row-count progress aborts the fetch rather than looping or
    silently stopping short.

    ``on_spawn`` is forwarded to every page's subprocess spawn (the refresh
    door's origin-contact stamp is a monotonic OR, so repeated arming is
    harmless). ``on_page`` (async, ``(imported_rows, feature_count)``) lets
    the import path publish per-page progress; pass None to skip.
    """
    from sqlalchemy import text as _text

    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.processing.ingest import ogr
    from app.processing.ingest.metadata import _qtable

    port = get_processing_port()
    imported_rows = 0
    append = False
    for offset in range(0, feature_count, page_size):
        page_source, page_layer = port.build_gdal_source(
            service_type_raw,
            source_url,
            layer_name,
            layer_id,
            token=token,
            order_field=order_field,
            result_limit=page_size,
            result_offset=offset,
        )
        await ogr.run_ogr2ogr_service(
            page_source,
            page_layer,
            staging_table,
            db_conn_str,
            service_type,
            token=token,
            is_non_spatial=is_non_spatial,
            append=append,
            schema=schema,
            on_spawn=on_spawn,
        )
        async with async_session() as session:
            result = await session.execute(
                _text(f"SELECT COUNT(*) FROM {_qtable(staging_table, schema=schema)}")
            )
            next_imported_rows = int(result.scalar_one())
        grew = next_imported_rows - imported_rows
        if grew <= 0:
            raise ogr.IngestionError(
                "ArcGIS service import made no row-count progress "
                f"at offset {offset}; upstream pagination may be "
                "unsupported or returned an empty page."
            )
        expected = min(page_size, feature_count - offset)
        if grew != expected:
            # fix(#1675): positive growth alone isn't enough — a server
            # returning fewer rows than requested while offset advances by
            # page_size would silently skip records. A mid-fetch source
            # mutation trips this too; failing is the safe direction.
            raise ogr.IngestionError(
                f"ArcGIS page at offset {offset} returned {grew} rows where "
                f"{expected} were expected; the server may cap responses "
                "below its advertised page size or the source changed "
                "mid-fetch. Refusing to continue with a potentially "
                "incomplete copy."
            )
        imported_rows = next_imported_rows
        if on_page is not None:
            await on_page(imported_rows, feature_count)
        append = True


async def _run_staging_pipeline(
    session,
    *,
    table_name: str,
    has_geometry: bool,
    effective_srid: int | None,
) -> StagingResult:
    """Run the post-ogr2ogr staging pipeline on a table.

    fix(#1018): the only production caller is ``tasks_reupload.reupload_file``.
    ``_ingest_vector_into_staging`` also calls it but is test-only; NEW
    vector ingest does NOT — ``_finalize_ingest`` reruns these same steps
    inline instead.

    Performs: ensure_geom_column,
    clip_to_mercator_bounds, add_4326_column, grant_reader_access,
    extract_metadata, detect_3d_metadata, promote_z_to_elev, and
    get_sample_values. Does not commit.
    """
    from app.processing.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        detect_3d_metadata,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
        promote_z_to_elev,
    )

    _schema = _current_tenant_schema()
    mercator_clip = None
    if has_geometry:
        has_geometry = await ensure_geom_column(session, table_name, schema=_schema)
        if has_geometry:
            mercator_clip = await clip_to_mercator_bounds(
                session, table_name, schema=_schema
            )
            if effective_srid is not None:
                await add_4326_column(
                    session, table_name, effective_srid, schema=_schema
                )

    await grant_reader_access(
        session,
        table_name,
        schema=_schema,
        role=_current_tenant_role(),
    )

    metadata = await extract_metadata(session, table_name, schema=_schema)
    three_d = await detect_3d_metadata(session, table_name, schema=_schema)

    if three_d.get("is_3d"):
        elev_promoted = await promote_z_to_elev(
            session, table_name, metadata.get("geometry_type"), schema=_schema
        )
        if elev_promoted:
            from app.processing.ingest.metadata import get_column_info

            metadata["column_info"] = await get_column_info(
                session, table_name, schema=_schema
            )

    sample_values = await get_sample_values(
        session, table_name, metadata.get("column_info", []), schema=_schema
    )

    return StagingResult(
        metadata=metadata,
        sample_values=sample_values,
        three_d=three_d,
        has_geometry=has_geometry,
        geometry_type=metadata.get("geometry_type"),
        mercator_clip=mercator_clip,
    )


async def stamp_failed_origin_health(
    session,
    dataset_cls: Any,
    dataset_uuid: uuid.UUID,
    *,
    health: str | None,
    detail: str | None,
    bound: tuple | None,
) -> None:
    """Persist what a failed refresh learned about its origin, if anything.

    This owns the dataset-side verdict; ``record_refresh_failure`` owns the
    run row (caller passes ``contacted_origin=False`` there so the run
    finalizer doesn't also write the dataset).

    Guarded on the ``(origin_uri, origin_ref, source_format)`` triple the
    failing attempt read, so a refresh against an origin the dataset has
    since been rebound to (e.g. to an upload, which has no probe/refresh of
    its own) cannot overwrite the rebind's own, now-current verdict —
    losing that race is a silent skip.

    ``health=None`` writes nothing: a failure that established nothing about
    the origin (statement timeout, a search that couldn't run) must leave
    the last conclusive verdict standing rather than replace it with a guess.

    feat(#1266): shared rather than duplicated per strategy so the guard
    doesn't end up with a second, drifting spelling in the STAC strategy
    beside ``_record_failed_origin_contact``.
    """
    if health is None or bound is None:
        return
    from sqlalchemy import update as sa_update

    bound_uri, bound_ref, bound_format = bound
    outcome = await session.execute(
        sa_update(dataset_cls)
        .where(
            dataset_cls.id == dataset_uuid,
            dataset_cls.origin_uri.is_not_distinct_from(bound_uri),
            dataset_cls.origin_ref.is_not_distinct_from(bound_ref),
            dataset_cls.source_format.is_not_distinct_from(bound_format),
        )
        .values(
            source_health=health,
            source_health_detail=detail,
            # The attempt reached the origin and got an answer — a dropped
            # relation and a withdrawn item both ARE answers, the same way
            # the probe dates a 404. That is the whole meaning of the column.
            last_checked_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    if outcome.rowcount:
        # GET /datasets/ serves these fields from a 60s cache; every other
        # writer invalidates it, and a lost guard race changed nothing worth
        # invalidating for.
        await invalidate_catalog_cache()


async def load_job_for_error_write(
    session,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID | None,
    *,
    task_name: str,
):
    """Load the job row a failure tail is about to settle, under the shared budget.

    Never raises — every caller reaches it from inside an ``except``, where
    a raise would replace the ingest failure with a lock timeout.

    Returns ``None`` when the row is gone, a newer attempt owns it, or the
    budget expired (logged as its own event); on any ``None`` the
    transaction is ended so the caller's remaining writes run unbudgeted
    on a clean session. On a hit the transaction stays open and budgeted —
    ending it here would expire the row instance before the caller passes
    it to ``_cleanup_staging_on_failure``.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError

    from app.platform.jobs.heartbeat import (
        arm_job_error_write_budget,
        log_job_error_write_failure,
    )
    from app.platform.jobs.models import IngestJob

    async def _end_transaction() -> None:
        # A rollback on a connection that is already gone raises, and this
        # helper's whole job is to not raise.
        with suppress(Exception):  # broad: best-effort, the caller re-raises
            await session.rollback()

    filters = [IngestJob.id == job_uuid]
    if attempt_uuid is not None:
        filters.append(IngestJob.attempt_id == attempt_uuid)
    try:
        await arm_job_error_write_budget(session)
        result = await session.execute(select(IngestJob).where(*filters))
        job = result.scalar_one_or_none()
        if job is None:
            await _end_transaction()
        return job
    except DBAPIError as write_failure:
        await _end_transaction()
        log_job_error_write_failure(write_failure, job_id=str(job_uuid), task=task_name)
        return None


async def _cleanup_staging_on_failure(
    session,
    *,
    staging_table: str,
    job,
    exc: Exception,
    task_name: str,
    attempt_id: uuid.UUID | None = None,
) -> None:
    """Mark the job failed, then drop the staging table, in that order.

    The single terminal-write site for ``reupload_file``/``reupload_service``
    and the import tasks: applies the ``redact_url_credentials`` backstop,
    the ``pending``-inclusive attempt fence (fix(#1274): a worker-time refusal
    that raises before the claim must still finalize the job it owns rather
    than leave it for the stale sweep), and the ``ingest_failed`` notification.

    fix(#1778): ``staging_table`` is "" for paths with none (the VRT tail
    reaps its object keys in its own ``finally``) — an empty name skips the
    DROP rather than interpolating and raising inside the best-effort guard.

    fix(#1778): ORDER is the contract — the failure row is written and
    committed BEFORE the drop, because a statement error aborts the whole
    transaction and every later statement on that session raises until
    rolled back. Drop-first previously left a job ``running`` with no
    reason recorded when the drop hit a lock/statement timeout. Anything
    added here that can fail goes after the commit, in its own guarded
    block with its own rollback.

    fix(#1950): the failure UPDATE runs under ``JOB_ERROR_WRITE_TIMEOUT_MS``;
    on a contended row it logs ``job_error_write_timeout`` and returns
    rather than waiting — the job stays ``running`` and the caller re-raises
    the failure it was already handling.
    """
    from sqlalchemy import text
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import DBAPIError

    from app.platform.jobs.heartbeat import (
        arm_job_error_write_budget,
        log_job_error_write_failure,
    )
    from app.processing.ingest.metadata import _qtable

    job_id = job.id
    completed_at = datetime.now(timezone.utc)
    # fix(#1277): last boundary before this text becomes durable — feeds the
    # persisted error_message, the log record, and the notification reason,
    # so redacting once here covers all three for every caller. Pattern-based
    # (also scrubs the reupload commit door's token, never held as a distinct
    # value). The exception object itself is left unmodified.
    error_message = redact_url_credentials(str(exc))
    await session.rollback()

    failure_update = sa_update(type(job)).where(type(job).id == job_id)
    if attempt_id is not None:
        # The fence is the attempt-id equality — a superseded attempt carries
        # a different token and can never match. `pending` is included
        # because a failure BEFORE the claim (fix(#1274) review: the worker-
        # time SSRF refusal) must still finalize the job it owns; requiring
        # `running` made the legitimate attempt's pre-claim failures
        # invisible, leaving the job pending until the stale sweep.
        failure_update = failure_update.where(
            type(job).attempt_id == attempt_id,
            type(job).status.in_(("pending", "running")),
        )
    # fix(#1950): an expired budget must not become the task's outcome. Swallowed
    # and logged as its own event, so the caller re-raises the ingest failure and
    # the report below still runs; `written` gates what the write earned.
    written = False
    result = None
    try:
        # fix(#1950): armed AFTER the rollback that would discard it and before
        # the UPDATE, which is the statement that blocks on a contended job row;
        # inside the guard because arming can fail on a lost connection too.
        await arm_job_error_write_budget(session)
        result = await session.execute(
            failure_update.values(
                status="failed",
                error_message=error_message,
                completed_at=completed_at,
            )
        )
        await session.commit()
        written = True
    except DBAPIError as write_failure:
        # Same reason as the loader's: the callers below re-raise the ingest
        # failure, and a rollback that raises would take its place.
        with suppress(Exception):  # broad: best-effort, the caller re-raises
            await session.rollback()
        log_job_error_write_failure(write_failure, job_id=str(job_id), task=task_name)

    # DROP after commit — see docstring. Runs before the rowcount return so
    # this attempt's (attempt-scoped) table is dropped even when a newer
    # attempt already owns the job row.
    if staging_table:
        try:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS {_qtable(staging_table, schema=_current_tenant_schema())}"
                )
            )
            await session.commit()
        except Exception as cleanup_exc:  # broad: best-effort cleanup
            structlog.get_logger().warning(
                f"Staging-table cleanup failed during {task_name} failure",
                staging_table=staging_table,
                cleanup_error=str(cleanup_exc),
                original_error=str(exc),
            )
            try:
                await session.rollback()
            except Exception:  # broad: a dead connection cannot be rolled back
                structlog.get_logger().warning(
                    "staging_cleanup_rollback_failed",
                    staging_table=staging_table,
                    task=task_name,
                )

    if written and attempt_id is not None and not result.rowcount:
        return
    if written:
        job.status = "failed"
        job.error_message = error_message
        job.completed_at = completed_at
    structlog.get_logger().exception(
        "Ingest task failed",
        job_id=str(job_id),
        task=task_name,
    )

    # EVENT-03: notify on ingest failed (non-fatal, after commit — deferred import discipline).
    # status="failed" + error_message are already committed above so a notification
    # error can never roll back or alter the terminal job write (T-1230-09 / fail-safe).
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    _job_id_str = str(job_id)
    _reason = error_message
    _task = task_name
    await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {_task}",
            body=f"Ingest job (task={_task}) failed.",
            reason=_reason,
            extra={"job_id": _job_id_str, "task": _task},
        ),
    )


async def _ingest_vector_into_staging(
    session,
    *,
    job,
    file_path: str,
    target_table: str,
    source_srid: int | None,
    ogr_geometry_type: str | None,
    has_geometry: bool,
    effective_srid: int | None,
    layer_name: str | None = None,
    ogrinfo_columns: list[dict] | None = None,
    user_wants_geom: bool = False,
    user_metadata: dict[str, Any] | None = None,
) -> StagingResult:
    """Load a vector source into staging and return extracted staging metadata.

    TEST-ONLY (#1018): nothing in ``app/`` calls this, only
    ``tests/test_staging_pipeline.py`` and ``test_staging_pipeline_integration
    .py``. Gives those tests a seam over vector ingest's pre-staging half,
    which production runs inline in its own job lifecycle. Mirrors
    ``run_ogr2ogr``, ``rename_reserved_columns``, the DBF-truncation check,
    then ``_detect_and_override_geometry`` under ``user_wants_geom`` — the
    same four as ``tasks_vector.ingest_file`` (the only production path with
    the override); ``tasks_reupload.reupload_file`` runs only the first
    three and passes its detected type straight to ``run_ogr2ogr``.

    Calls the real ``_run_staging_pipeline``, but that eight-step sequence
    also exists inlined in ``_finalize_ingest`` (used by ``tasks_vector.
    ingest_file``) and as a SHORTER copy (no 3D detection, no elevation
    promotion) in ``tasks_reupload.reupload_service`` — do not "fix" that
    shorter copy by symmetry without finding out why first. A change to the
    shared six steps has three sites; this test covers the one production
    reaches least.

    Performs no commits.
    """
    from app.processing.ingest.metadata import rename_reserved_columns
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr

    if user_wants_geom and user_metadata is None:
        raise ValueError("user_metadata is required when user_wants_geom=True")

    db_conn_str = build_pg_conn_str()
    await run_ogr2ogr(
        file_path,
        target_table,
        db_conn_str,
        source_srid=source_srid,
        geometry_type=ogr_geometry_type,
        layer_name=layer_name,
        schema=_current_tenant_schema(),
        effective_srid=effective_srid,
    )

    reserved_renames = await rename_reserved_columns(
        session, target_table, schema=_current_tenant_schema()
    )
    if reserved_renames:
        from app.processing.ingest.warnings import make_reserved_rename_warning

        _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

    # Shapefile-only. Keyed on the derived format, not the .zip suffix — a
    # File Geodatabase arrives in a .zip too and has no DBF to truncate.
    if derive_source_format(file_path) == "shapefile":
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions
        from app.processing.ingest.ogr import run_ogrinfo_preview
        from app.processing.ingest.warnings import make_dbf_truncation_warning

        preview_cols = ogrinfo_columns or []
        if not preview_cols:
            preview_info = await run_ogrinfo_preview(
                file_path, sample_limit=0, layer_name=layer_name
            )
            preview_cols = preview_info.get("columns") or []
        dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
        if dbf_collisions:
            _append_job_warning(job, make_dbf_truncation_warning(dbf_collisions))

    geometry_type = ogr_geometry_type
    if user_wants_geom:
        override_geom_type = await _detect_and_override_geometry(
            session,
            table_name=target_table,
            user_metadata=user_metadata or {},
            effective_srid=effective_srid or 4326,
        )
        if override_geom_type is not None:
            has_geometry = True
            geometry_type = override_geom_type

    result = await _run_staging_pipeline(
        session,
        table_name=target_table,
        has_geometry=has_geometry,
        effective_srid=effective_srid,
    )

    # Preserve the original geometry_type fallback: if _run_staging_pipeline
    # returned a geometry_type from metadata, use it; otherwise fall back to
    # the ogr_geometry_type (possibly overridden by user_wants_geom).
    if result.geometry_type is None and geometry_type is not None:
        result.geometry_type = geometry_type

    return result


async def _generate_quicklook(
    session, dataset, table_name: str, geometry_type: str
) -> None:
    """Generate and upload a vector quicklook thumbnail (non-fatal).

    Runs after the outer ingest commit so a connection-killing query
    (OOM, timeout on complex geometry) cannot roll back the dataset.
    Separate try/except blocks around generate+upload, rollback+URI-write,
    and commit let operators tell which phase failed from the logs.

    INGEST-01 / Phase 1091-02: caller MUST pass a FRESH session isolated
    from the outer ``_finalize_ingest`` session (use ``_job_phase_session
    (job_uuid, phase="quicklook")``). The generation timeout can cancel the
    inner geom query mid-flight and poison the asyncpg cursor; the
    defensive ``rollback()`` below then expires every ORM attribute
    (``expire_on_rollback=True``). On the outer session that trips
    ``MissingGreenlet`` on ``dataset.record``'s next lazy access.

    The outer session's view of ``quicklook_256_uri`` is stale after this
    returns — callers needing it must ``session.refresh(dataset)`` or
    re-fetch via ``port.get_dataset``.
    """
    import io as _io

    _ql_log = structlog.get_logger()
    try:
        from app.processing.vector.quicklook import (
            generate_vector_quicklook_with_timeout as generate_vector_quicklook,
        )

        ql_bytes = await generate_vector_quicklook(
            session,
            table_name,
            geometry_type,
            256,
            schema=_current_tenant_schema(),
        )
        from app.core.db.tenant_session import current_tenant_var
        from app.platform.storage.titiler_url import resolve_storage_key

        ql_storage = get_storage()
        ql_key = f"vectors/{dataset.id}/quicklook_256.png"
        await ql_storage.put(
            resolve_storage_key(ql_key, tenant_id=current_tenant_var.get()),
            _io.BytesIO(ql_bytes),
        )
    except Exception as _ql_exc:  # broad: quicklook generation is non-fatal; geometry rendering can OOM/timeout
        _ql_log.warning(
            "quicklook_failed",
            phase="generate",
            table=table_name,
            error=str(_ql_exc),
        )
        return

    # INGEST-01 iter-2: recovers a cursor poisoned by a wait_for cancel;
    # no-op on the clean path. WR-01: wrapped in try/except because
    # rollback()/merge() are themselves IO that can raise if the
    # connection died — an uncaught escape here would propagate to
    # status="failed" on a job whose dataset is already committed
    # (dataset-published + job-failed, OPS-01's disagreement).
    try:
        await session.rollback()

        # Re-merge into the now-clean session; the pre-generation merge
        # entry was discarded by the rollback above.
        merged_dataset = await session.merge(dataset)
        merged_dataset.quicklook_256_uri = ql_key
    except Exception as _ql_recovery_exc:  # broad: non-fatal contract — connection drop between upload and recovery must not propagate
        try:
            await session.rollback()
        except Exception:  # broad: best-effort cleanup; connection may be irrecoverable
            pass
        _ql_log.warning(
            "quicklook_failed",
            phase="recovery",
            table=table_name,
            error=str(_ql_recovery_exc)[:500],
        )
        return

    try:
        await session.commit()
    except (
        Exception
    ) as _ql_commit_exc:  # broad: transient commit failure after successful generation
        await session.rollback()
        _ql_log.warning(
            "quicklook_failed",
            phase="commit",
            table=table_name,
            error=str(_ql_commit_exc),
        )


async def _finalize_ingest(ctx: IngestContext):
    """Shared post-ogr2ogr pipeline for both file and service ingestion.

    Steps: normalize geometry column, clip to valid bounds, add 4326
    column; grant reader access; extract column info and sample values;
    create dataset record; compute quality score; commit job + dataset
    atomically; generate quicklook thumbnail (non-fatal); invalidate
    caches and backfill embedding.

    ``ctx`` is an ``IngestContext`` bundle — see its dataclass docstring
    for field descriptions. Returns the created Dataset ORM instance.
    """
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        compute_quality_score,
        detect_3d_metadata,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
        promote_z_to_elev,
    )

    port = get_processing_port()

    session = ctx.session
    job = ctx.job
    table_name = ctx.table_name
    user_metadata = ctx.user_metadata
    source_filename = ctx.source_filename

    # Normalize geometry column name to 'geom'
    _schema = _current_tenant_schema()
    has_geometry = ctx.has_geometry
    if has_geometry is None:
        has_geometry = await ensure_geom_column(session, table_name, schema=_schema)
    elif has_geometry:
        await ensure_geom_column(session, table_name, schema=_schema)

    # Clip geometries to Web Mercator bounds and add 4326 column.
    # When has_geometry is truthy, callers always supply a non-null
    # effective_srid — guard for mypy since the two params are independent
    # at the signature level.
    if has_geometry:
        assert ctx.effective_srid is not None, (
            "effective_srid must be set when has_geometry is True"
        )
        # fix(#888): the clamp is intentional, staying silent about it was not.
        _append_mercator_clip_warning(
            job, await clip_to_mercator_bounds(session, table_name, schema=_schema)
        )
        await add_4326_column(session, table_name, ctx.effective_srid, schema=_schema)

    # Grant reader access (per-tenant schema+role in multi_tenant; data/geolens_reader in single_tenant)
    await grant_reader_access(
        session,
        table_name,
        schema=_schema,
        role=_current_tenant_role(),
    )

    # Extract metadata (CR-03: pass per-tenant schema so catalog queries target
    # data_t_{tid} in multi_tenant, not the shared 'data' schema)
    metadata = await extract_metadata(session, table_name, schema=_schema)

    # Detect 3D geometry properties (per Phase 999.2)
    three_d = await detect_3d_metadata(session, table_name, schema=_schema)

    # Attribute promotion: extract ST_Z into elev column for 3D points
    if three_d.get("is_3d"):
        elev_promoted = await promote_z_to_elev(
            session, table_name, metadata.get("geometry_type"), schema=_schema
        )
        if elev_promoted:
            # Re-extract column_info so elev appears in the column list
            from app.processing.ingest.metadata import get_column_info

            metadata["column_info"] = await get_column_info(
                session, table_name, schema=_schema
            )

    # ArcGIS column_info fallback: if the DB-based extraction returned empty
    # column_info (e.g., non-spatial table where ogr2ogr only created a gid column),
    # fall back to the ArcGIS fields captured at preview time and stored in user_metadata.
    if not metadata.get("column_info") and user_metadata.get("source_columns"):
        source_columns = user_metadata["source_columns"]
        metadata["column_info"] = [
            {
                "name": col["name"],
                "type": _arcgis_type_to_column_type(col.get("type", "string")),
                "ordinal_position": idx + 1,
                "is_nullable": True,
            }
            for idx, col in enumerate(source_columns)
            if col.get("name")  # skip columns without a name
        ]

    # Extract sample values for attribute search
    sample_values = await get_sample_values(
        session, table_name, metadata.get("column_info", []), schema=_schema
    )

    # Create Dataset record
    dataset_name = user_metadata.get("title") or source_filename or table_name
    ingestion_fields: dict = {
        **metadata,
        "sample_values": sample_values,
        "source_format": ctx.source_format,
        "source_filename": source_filename,
        "original_srid": ctx.original_srid
        if ctx.original_srid is not None
        else metadata.get("srid"),
        "is_3d": three_d.get("is_3d"),
        "n_dims": three_d.get("n_dims"),
        "z_min": three_d.get("z_min"),
        "z_max": three_d.get("z_max"),
    }
    if ctx.source_url is not None:
        ingestion_fields["source_url"] = ctx.source_url
    ingestion = port.create_ingestion_result(**ingestion_fields)
    dataset = await port.create_dataset(
        session,
        table_name=table_name,
        title=dataset_name,
        created_by=uuid.UUID(ctx.user_id),
        summary=user_metadata.get("summary"),
        visibility=user_metadata.get("visibility", "private"),
        ingestion=ingestion,
    )
    # fix(#430): create_dataset defaults the record to 'published',
    # so the before_insert hook has already stamped published_at by the time
    # this overwrite runs. A non-published final status must not keep that
    # timestamp — the real transition path (_apply_record_status_change)
    # stamps it when the dataset is actually published later.
    final_status = user_metadata.get("record_status", "published")
    dataset.record.record_status = final_status
    if final_status != "published":
        dataset.record.published_at = None

    # feat(#1472): the manifest's credit line, which create_dataset has no
    # argument for. Same transaction as the record it annotates.
    apply_manifest_record_metadata(dataset.record, user_metadata)

    # feat(#1218): system-managed origin pointer, in the same transaction that
    # creates the dataset. Service ingest supplies the enriched URL through
    # ctx.source_url; an uploaded file has no remote origin to point at, so
    # its origin_uri stays NULL and only the ref carries the filename.
    ingest_origin_kind = classify_origin(ctx.source_format)
    set_dataset_origin(
        dataset,
        ingest_origin_kind,
        uri=ctx.source_url,
        **(ctx.origin_ref or {}),
    )
    # fix(#1271): a first service or STAC ingest fetched its bytes
    # from the origin moments ago, so the import IS a contact — same contract
    # as the reupload swap below. Without this, every freshly imported
    # service dataset reported last_checked_at NULL until someone probed it.
    if ingest_origin_kind in ("service", "stac"):
        dataset.last_checked_at = datetime.now(timezone.utc)

    # Compute quality score (requires Dataset to exist for metadata checks)
    quality_score = await compute_quality_score(
        session,
        table_name,
        metadata.get("column_info", []),
        dataset,
        schema=_schema,
    )
    dataset.quality_detail = quality_score

    # Update job to complete and commit dataset + job atomically. The
    # attempt predicate is the worker lease fence: if a stale worker resumes
    # after a retry rotated the token, this no-op raises and the surrounding
    # phase transaction rolls back the dataset it built.
    # REMED-02 / ingest-audit P2-07: stamp the terminal progress signal so the
    # polling UI sees current_step=complete + progress=1.0 immediately on
    # success. ``rows_processed`` is the feature_count derived by
    # ``extract_metadata`` above; raster ingests (which do not call this
    # helper) leave the column NULL — see tasks_raster.ingest_raster.
    from app.platform.jobs.heartbeat import require_ingest_job_update

    await require_ingest_job_update(
        session,
        job.id,
        ctx.attempt_id or job.attempt_id,
        values={
            "status": "complete",
            "dataset_id": dataset.id,
            "completed_at": datetime.now(timezone.utc),
            "current_step": "complete",
            "progress": 1.0,
            "rows_processed": metadata.get("feature_count"),
        },
    )
    await session.commit()

    # EVENT-02: notify on ingest complete (non-fatal, after commit — deferred import discipline).
    # Placed here: status="complete" is already committed above so a notification
    # error can never roll back or alter the terminal job write (T-1230-09 / fail-safe).
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    _dataset_title = getattr(dataset, "title", None) or table_name
    _job_id_str = str(job.id)
    await emit_event_safe(
        event_key="ingest_complete",
        build=lambda: build_event_notification(
            "ingest_complete",
            subject=f"Ingest complete: {_dataset_title}",
            body=f"Vector dataset '{_dataset_title}' has been successfully ingested.",
            extra={"job_id": _job_id_str, "dataset": _dataset_title},
        ),
    )

    # Generate vector quicklook thumbnail (non-fatal, after commit).
    # INGEST-01 / Phase 1091-02: opens its OWN session so a cancellation
    # inside quicklook generation can't poison `session` and trip
    # `MissingGreenlet` on the outer `dataset.record` — see
    # `_generate_quicklook`'s docstring.
    if has_geometry:
        async with _job_phase_session(job.id, phase="quicklook") as (
            ql_session,
            _ql_job,
        ):
            await _generate_quicklook(
                ql_session, dataset, table_name, metadata.get("geometry_type", "")
            )

    # Invalidate caches after successful ingest
    await invalidate_catalog_cache()

    # Generate embedding (non-fatal)

    await defer_embedding(dataset)

    return dataset


def resolve_service_type(raw: str) -> tuple[str, str]:
    """Map raw service_type string to (service_type, source_format)."""
    from app.processing.ingest.ogr import IngestionError

    if raw.startswith("ArcGIS"):
        return "arcgis_featureserver", "arcgis_featureserver"
    elif raw.startswith("WFS"):
        return "wfs", "wfs"
    elif raw.startswith("OGC API"):
        return "ogcapi_features", "ogcapi_features"
    raise IngestionError(
        f"Unrecognized service type '{raw}'. "
        f"Expected a type starting with 'ArcGIS', 'WFS', or 'OGC API'."
    )


def _is_lock_timeout_error(exc: BaseException) -> bool:
    """Detect PostgreSQL lock_timeout (SQLSTATE 55P03) across asyncpg + SQLAlchemy wrapping.

    asyncpg raises ``asyncpg.exceptions.LockNotAvailableError``; SQLAlchemy
    wraps it in ``DBAPIError`` with ``.orig`` pointing at the original
    asyncpg exception. Check both shapes so behavior is identical
    regardless of where the exception bubbles up from.

    ING-06 / P2-08: used by ``_apply_reupload_swap`` to gate its single
    retry. Returns False for any other exception class or SQLSTATE so
    real errors (e.g., 23505 unique violation) still propagate
    immediately.
    """
    # Direct asyncpg exception
    try:
        from asyncpg.exceptions import LockNotAvailableError

        if isinstance(exc, LockNotAvailableError):
            return True
    except ImportError:
        pass

    # SQLAlchemy-wrapped: check the underlying .orig for SQLSTATE 55P03
    orig = getattr(exc, "orig", None)
    if orig is not None:
        sqlstate = getattr(orig, "sqlstate", None)
        if sqlstate == "55P03":
            return True

    return False


def _looks_like_auth_error(error_message: str) -> bool:
    """Best-effort detection for remote auth failures from GDAL stderr."""
    lowered = error_message.lower()
    markers = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "authentication",
        "access denied",
        "invalid token",
        "token required",
    )
    return any(marker in lowered for marker in markers)


async def _run_service_import_with_wfs_fallback(
    import_fn,
    source_layer: str,
    *,
    token: str | None = None,
    auth_error_message: str | None = None,
) -> None:
    """Run a service import with WFS namespace retry + optional auth detection.

    Extracts the retry pattern that appears in both ingest_service and
    reupload_service (KISS-8). If the initial import raises
    ``IngestionError`` and the layer name has a ``ns:name`` prefix,
    retries with the unqualified name. If ``auth_error_message`` is
    provided and the token is None and the error looks like an auth
    failure, re-raises with the custom message so users get a clear
    "you probably need a token" hint instead of the raw GDAL stderr.

    ``import_fn`` must be an async callable that accepts a single
    ``layer_name: str`` argument and does the actual ogr2ogr work.
    """
    from app.processing.ingest.ogr import IngestionError

    try:
        await import_fn(source_layer)
    except IngestionError as exc:
        if ":" in source_layer:
            unqualified = source_layer.split(":", 1)[1]
            try:
                await import_fn(unqualified)
            except IngestionError as retry_exc:
                if (
                    auth_error_message is not None
                    and token is None
                    and _looks_like_auth_error(str(retry_exc))
                ):
                    raise IngestionError(auth_error_message) from retry_exc
                raise
        elif (
            auth_error_message is not None
            and token is None
            and _looks_like_auth_error(str(exc))
        ):
            raise IngestionError(auth_error_message) from exc
        else:
            raise


async def invalidate_tile_cache_for_table(table_name: str) -> None:
    """Best-effort MVT tile-cache purge after a table's contents change.

    fix(#394) B-019/VT-01: reupload swaps the whole table under the same
    ``table_name`` but was the one write path that never purged the Valkey
    tile cache — the cache key has no content-version dimension, so stale
    geometry/attributes kept 304-serving for up to ``tile_cache_ttl``.
    Call AFTER the owning transaction commits, so a concurrent tile request
    can't re-cache pre-swap rows. Never raises.
    """
    from app.platform.cache.provider import get_tile_cache

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(table_name)


# What PostGIS records in ``geometry_columns.type`` for an untyped column.
# A specific value ("POLYGON", "MULTILINESTRING", ...) describes what the
# column will accept; this one describes nothing.
_GENERIC_GEOMETRY_TYPE = "GEOMETRY"

# The record types ``service_create.py`` derives from "does this dataset have
# geometry". Raster and VRT records carry their own modality and must never be
# re-derived from a geometry column they do not have.
_DERIVED_RECORD_TYPES: frozenset[str] = frozenset({"table", "vector_dataset"})


async def _declared_geometry_type(
    session: Any, *, schema: str, table: str
) -> str | None:
    """The geom column's DECLARED type, or None when the relation has no geom.

    fix(#1313): ``extract_metadata`` derives the type by sampling a row,
    so an emptied spatial table reports None — indistinguishable from one
    that never had geometry. Writing that None reclassifies the dataset as
    tabular, which locks ``_require_feature_table`` out of ever
    repopulating it and drops it from the builder. ``geometry_columns``
    answers what the sample can't: a row there means the relation is
    spatial regardless of current contents.

    fix(#1373): shared with the reupload swap, which hits the identical
    trap from the other direction (an empty spatial file), so the two
    paths can't end up disagreeing via two spellings of this query.
    """
    from sqlalchemy import text

    return await session.scalar(
        text(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_schema = :schema AND f_table_name = :table "
            "AND f_geometry_column = 'geom'"
        ),
        {"schema": schema, "table": table},
    )


def _effective_geometry_type(
    *, measured: str | None, declared: str | None, stored: str | None
) -> str | None:
    """The geometry type this measurement establishes, from the best evidence.

    One rule in one place: both the write and the quality score use it, so a
    second spelling of this precedence is how those two would disagree.

    fix(#1382): when nothing was measured and the declared column is the
    generic ``geometry`` sentinel, this falls back to ``stored`` rather than
    always returning it — otherwise a never-measured dataset with a generic
    empty column resolved to None and stayed classified ``table``, locked
    out of feature writes despite plainly having a geometry column.
    """
    if measured is not None:
        return measured
    if declared is None:
        return None
    if declared != _GENERIC_GEOMETRY_TYPE:
        return declared
    return stored if stored is not None else _GENERIC_GEOMETRY_TYPE


def _derived_record_type(current: str | None, geometry_type: str | None) -> str | None:
    """``record_type`` as ``service_create.py`` derives it, for the two it owns."""
    if current not in _DERIVED_RECORD_TYPES:
        return current
    return "table" if geometry_type is None else "vector_dataset"


async def _retire_geometry_attribute_row(
    session: Any, dataset_id: uuid.UUID, *, geometry_type: str | None
) -> None:
    """Retire the synthetic ``geom`` attribute row of a de-spatialized dataset.

    ``refresh_attribute_metadata`` only touches this row for a non-null
    ``geometry_type`` and excludes ``geom`` from its removed-column sweep by
    name — right when a caller replaces contents while keeping shape, wrong
    for the registered-PostGIS refresh (owner can drop the column) and the
    reupload swap (CSV over a shapefile), whose relation can lose geometry
    while keeping identity. Left stale, the attributes API and validation
    service keep advertising a geometry field the relation no longer has.

    fix(#1313) added this for the refresh path; fix(#1380) reuses it for the
    reupload swap instead of a second copy. Pass the EFFECTIVE geometry
    type (same value given to ``refresh_attribute_metadata``) and call
    unconditionally — the null check lives inside so a caller can't hold
    one half of the pair and forget the other.
    """
    if geometry_type is not None:
        return

    from app.platform.extensions import get_processing_port
    from sqlalchemy import update

    AttributeMetadata = get_processing_port().get_attribute_metadata_orm_class()
    await session.execute(
        update(AttributeMetadata)
        .where(
            AttributeMetadata.dataset_id == dataset_id,
            AttributeMetadata.field_name == "geom",
        )
        .values(is_current=False)
    )


# The AccessExclusiveLock budget the reupload swap DDL spends: first attempt,
# the single retry, and the pause between them (#1917).
_SWAP_FIRST_TIMEOUT = "5s"
_SWAP_RETRY_TIMEOUT = "15s"
_SWAP_RETRY_SLEEP_MS = 200

# fix(#1921): the budget for the catalog wait that FOLLOWS the swap. The
# transaction holds AccessExclusiveLock on the table it just installed across
# it, so a holder that outlasts this is stuck, not working.
_POST_SWAP_CATALOG_TIMEOUT = "60s"

# fix(#1921): `lock_catalog_rows` reports an expired budget and a lost
# deadlock alike, and the two send an operator looking for different things.
_POST_SWAP_WAIT_FAILURES = {
    "55P03": (
        "reupload_swap_catalog_lock_timeout",
        "The post-swap catalog wait expired. Find the holder of this "
        "dataset's catalog.datasets row in pg_stat_activity.",
    ),
    "40P01": (
        "reupload_swap_catalog_deadlock",
        "PostgreSQL chose this swap as the deadlock victim. Look for the "
        "other side of the cycle: a transaction holding this dataset's "
        "catalog row and waiting on its live table.",
    ),
}
_POST_SWAP_WAIT_UNKNOWN = (
    "reupload_swap_catalog_lock_failed",
    "The post-swap catalog wait failed and reported no SQLSTATE.",
)


async def _apply_reupload_swap(
    session,
    *,
    dataset,
    staging_table: str,
    metadata: dict,
    sample_values: dict,
    user_id: str,
    source_filename: str | None,
    source_format: str | None,
    original_srid: int | None,
    source_url: str | None = None,
    file_hash: str | None = None,
    origin_ref: dict[str, Any] | None = None,
) -> Any:
    """Apply shared atomic swap + version invariants for all reupload sources.

    ``origin_ref`` carries the typed per-origin payload for the bytes this
    swap installs, minus the ``kind`` discriminator (derived from
    ``source_format``). Same contract as ``IngestContext.origin_ref``: keys go
    through the per-kind allowlist, and callers supply their own rather than
    one being inferred here.

    Returns the ``DatasetVersion`` this swap produced, flushed so its id is
    populated. feat(#1219): the refresh run row links to that id, and building
    the version here while resolving it by (dataset_id, version_number) at the
    call site would be two ways to name one row.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata import (
        compute_quality_score,
        refresh_attribute_metadata,
    )
    from sqlalchemy import func, text

    port = get_processing_port()
    DatasetVersion = port.get_dataset_version_orm_class()

    actor_id = uuid.UUID(user_id)
    new_version = dataset.current_version + 1
    table_name = dataset.table_name

    from app.processing.ingest.metadata import _qtable

    # Tenant schema for this ingest: same schema for staging, live, and _old tables
    # (T-1209-07: staging→live RENAME must stay intra-schema so it is atomic DDL).
    _tenant_schema = _current_tenant_schema()

    # Resolve live_exists once — independent of lock contention; this
    # SELECT does not need the AccessExclusiveLock we're about to acquire.
    live_exists_result = await session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=:schema AND table_name=:tn)"
        ),
        {"schema": _tenant_schema, "tn": table_name},
    )
    live_exists = live_exists_result.scalar()

    # ING-06 (P2-08): wrap the swap DDL in SAVEPOINTs + single retry on
    # lock_timeout. Autovacuum can hold AccessExclusiveLock long enough to
    # collide with the 5s default; bumping to 15s on retry plus a 200ms
    # sleep gives the autovacuum a chance to clear without surfacing the
    # failure to the user. Beyond this single retry we surface the error
    # so ops can investigate. See:
    #   .planning/audits/INGEST-AUDIT-2026-05-21.md (P2-08)
    #   .planning/phases/1076-backend-ingest-p2-closure/1076-04-PLAN.md

    async def _swap_with_timeout(timeout_str: str) -> None:
        """Run SET LOCAL lock_timeout + the 3 ALTER TABLE swap statements.

        All three references (live, staging, _old) use the SAME _tenant_schema
        so the RENAME operations are intra-schema (T-1209-07).

        The ``SET LOCAL`` outlives a released savepoint, so the caller restores
        the previous value once the swap is done.
        """
        await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_str}'"))
        if live_exists:
            await session.execute(
                text(
                    f"ALTER TABLE {_qtable(table_name, schema=_tenant_schema)} "
                    f'RENAME TO "{table_name}_old"'
                )
            )
        await session.execute(
            text(
                f"ALTER TABLE {_qtable(staging_table, schema=_tenant_schema)} "
                f'RENAME TO "{table_name}"'
            )
        )
        if live_exists:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS {_qtable(table_name + '_old', schema=_tenant_schema)}"
                )
            )
        # After the _old table (and its identically-named pkey index) is gone,
        # give the new live table's PK its final name.
        await rename_pkey_to_match_table(session, table_name)

    # fix(#1917): a `SET LOCAL` survives RELEASE SAVEPOINT, so the DDL budget
    # below outlives its savepoint and would clamp every later wait in this
    # transaction. Capture what is in effect; it is put back after the swap.
    pre_swap_lock_timeout = await session.scalar(
        text("SELECT current_setting('lock_timeout')")
    )

    try:
        async with session.begin_nested():
            await _swap_with_timeout(_SWAP_FIRST_TIMEOUT)
    except Exception as first_exc:  # broad: catch any swap failure to inspect for lock-timeout before re-raising
        if not _is_lock_timeout_error(first_exc):
            raise

        structlog.get_logger().warning(
            "reupload_swap_lock_contention",
            dataset_id=str(dataset.id),
            table_name=table_name,
            attempt=1,
            first_timeout_seconds=5,
            retry_timeout_seconds=15,
            sleep_ms=_SWAP_RETRY_SLEEP_MS,
            hint=(
                "AccessExclusiveLock contention on first swap attempt — "
                "likely autovacuum collision; retrying once with longer "
                "timeout. Correlate with pg_stat_activity / pg_stat_user_tables."
            ),
        )
        await asyncio.sleep(_SWAP_RETRY_SLEEP_MS / 1000.0)

        # Retry inside its own SAVEPOINT so a second failure surfaces cleanly.
        async with session.begin_nested():
            await _swap_with_timeout(_SWAP_RETRY_TIMEOUT)

        structlog.get_logger().info(
            "reupload_swap_retry_succeeded",
            dataset_id=str(dataset.id),
            table_name=table_name,
            attempt=2,
            retry_timeout_seconds=15,
        )

    # fix(#1917): the DDL budget ends here. `set_config(..., true)` is
    # `SET LOCAL` taking a bind parameter.
    await session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": pre_swap_lock_timeout},
    )

    # fix(#1373): resolve the geometry type ONCE from the relation the swap
    # just installed, using the same `_declared_geometry_type`/
    # `_effective_geometry_type` helpers as the refresh path — see their
    # docstrings for the empty-relation trap this avoids. Read `stored`
    # before the write below: it must be the PRE-swap value.
    previous_geometry_type = dataset.geometry_type
    effective_geometry_type = _effective_geometry_type(
        measured=metadata["geometry_type"],
        declared=await _declared_geometry_type(
            session, schema=_tenant_schema, table=table_name
        ),
        stored=previous_geometry_type,
    )

    # fix(#448): belt-and-braces after the swap — the staging pipeline is
    # responsible for the GIST index, but a re-ingest of a table that already
    # lost its index (the IF-NOT-EXISTS name-collision regression) must
    # self-heal here rather than serve full-scan tiles until the next audit.
    if effective_geometry_type is not None:
        from app.processing.ingest.metadata import ensure_geom_4326_gist_index

        await ensure_geom_4326_gist_index(session, table_name, schema=_tenant_schema)

    # fix(#1847, #1917, #1921): the catalog writes start here and dirty both
    # rows. The swap's DDL budget was put back above; this wait gets its own,
    # and the value the transaction arrived with is restored after it.
    from app.core.db.sqlstate import sqlstate
    from app.platform.catalog_locks import (
        CatalogLockConflict,
        bump_tile_cache_version_on,
        lock_catalog_rows,
    )
    from app.platform.extensions import get_processing_port
    from sqlalchemy.exc import DBAPIError

    _port = get_processing_port()
    # fix(#1921): lock_catalog_rows rolls back before it raises, and a
    # rolled-back session expires every loaded instance.
    _log_dataset_id = str(dataset.id)
    _wait_started = time.perf_counter()
    try:
        await lock_catalog_rows(
            session,
            dataset_cls=_port.get_dataset_orm_class(),
            record_cls=_port.get_record_orm_class(),
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            lock_timeout=_POST_SWAP_CATALOG_TIMEOUT,
        )
    except CatalogLockConflict as conflict:
        cause = conflict.__cause__
        code = sqlstate(cause) if isinstance(cause, DBAPIError) else None
        event, hint = _POST_SWAP_WAIT_FAILURES.get(code, _POST_SWAP_WAIT_UNKNOWN)
        structlog.get_logger().warning(
            event,
            dataset_id=_log_dataset_id,
            table_name=table_name,
            waited_ms=round((time.perf_counter() - _wait_started) * 1000),
            budget=_POST_SWAP_CATALOG_TIMEOUT,
            sqlstate=code,
            hint=(
                f"{hint} The whole swap rolled back, so no half-swapped table is left."
            ),
        )
        raise

    structlog.get_logger().info(
        "reupload_swap_catalog_lock_acquired",
        dataset_id=_log_dataset_id,
        table_name=table_name,
        waited_ms=round((time.perf_counter() - _wait_started) * 1000),
        budget=_POST_SWAP_CATALOG_TIMEOUT,
    )
    # fix(#1921): this wait's budget ends here, like the DDL's above it.
    await session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": pre_swap_lock_timeout},
    )

    dataset.srid = metadata["srid"]
    dataset.geometry_type = effective_geometry_type
    # fix(#1361): modality is derived, so keep deriving it. `service_create.py`
    # sets `record_type` from whether the dataset has geometry, and a reupload
    # is one of the two operations that can change the answer afterwards.
    # `build_assets` reads it live, so leaving it stale means a de-spatialized
    # dataset goes on advertising vector-tile and OGC-Features links against a
    # relation with no geometry column, and a newly-spatial one never advertises
    # them at all. Fed the EFFECTIVE type rather than the sampled one, or an
    # empty spatial reupload would flip a still-spatial dataset to `table`.
    dataset.record.record_type = _derived_record_type(
        dataset.record.record_type, effective_geometry_type
    )
    dataset.feature_count = metadata["feature_count"]
    if metadata["extent_wkt"] is not None:
        dataset.record.spatial_extent = func.ST_GeomFromText(
            metadata["extent_wkt"], 4326
        )
    dataset.column_info = metadata["column_info"]
    dataset.sample_values = sample_values

    await refresh_attribute_metadata(
        session,
        dataset.id,
        metadata["column_info"],
        geometry_type=effective_geometry_type,
        sample_values=sample_values,
    )
    # fix(#1380): the one row that helper will not retire. Fed the EFFECTIVE
    # type, like the refresh above it, so a reupload that empties a still-
    # spatial table cannot retire the row of a relation whose geom column is
    # right there.
    await _retire_geometry_attribute_row(
        session, dataset.id, geometry_type=effective_geometry_type
    )

    # fix(#1314): a reupload can flip a dataset between spatial and
    # non-spatial, leaving the auto-generated `record_distributions` rows as
    # stale as on the refresh path. Gated on the modality FLIP only —
    # reconcile normalizes `is_primary`, and a reupload keeping modality has
    # no business rewriting it.
    #
    # fix(#1373): the flip is read off the EFFECTIVE type — the same value
    # written to `geometry_type`/`record_type` above — so all three agree.
    # Demote is safe because `_declared_geometry_type` returns None exactly
    # when there is no geom column (reconciling on a sampled None alone
    # would wrongly delete distribution rows of a still-spatial dataset).
    # Promote now also fires for a TABULAR dataset reuploaded from an empty
    # spatial file, since a declared column type is written even then.
    was_spatial = previous_geometry_type is not None
    is_spatial = effective_geometry_type is not None
    if was_spatial != is_spatial:
        await port.reconcile_distributions(
            session,
            dataset.id,
            dataset.record_id,
            table_name,
            geometry_type=effective_geometry_type,
        )

    dataset.source_format = source_format
    dataset.source_filename = source_filename
    dataset.original_srid = original_srid
    dataset.current_version = new_version
    # fix(#1911): evaluated at write time, under the lock, so the counter read
    # into `dataset` before the wait is never written back over a peer's commit.
    await bump_tile_cache_version_on(session, dataset)
    dataset.record.updated_by = actor_id
    if source_url is not None:
        dataset.source_url = source_url

    # fix(#1218): restamp the binding to describe where the CURRENT bytes
    # came from. Without this a file reupload of a registered-postgis or
    # service dataset leaves the old pointer in place — computed origin
    # `upload` beside a stored ref still claiming `postgis` — and a later
    # refresh follows the stale pointer. Kind is derived from the NEW
    # source_format, same as first ingest, so a service reupload stays a
    # service origin and a file reupload clears `origin_uri`.
    #
    # #1220's shared refresh executor takes over both writes for
    # server-side refresh; until it lands, this path owns them.
    origin_kind = classify_origin(source_format)
    set_dataset_origin(
        dataset,
        origin_kind,
        uri=source_url,
        **(origin_ref or {}),
    )
    # The swap commit time, which is what migration 0036's backfill reads off
    # max(dataset_versions.uploaded_at) for a pre-existing dataset. A Python
    # datetime rather than func.now(): a SQL expression leaves the attribute
    # expired after flush, and the next read of dataset.last_refreshed_at then
    # lazy-loads against a session that may already be closed.
    swap_time = datetime.now(timezone.utc)
    # fix(#1271): set_dataset_origin just cleared the probe state, and
    # for a service or STAC origin this swap IS a contact — the bytes were
    # fetched from that origin moments ago. Leaving last_checked_at NULL
    # would make the API claim the origin was never contacted, which is the
    # column's contract violated in the other direction. source_health stays
    # NULL: the health vocabulary belongs to the probe's classifier. A file
    # upload or registered table contacts nothing and stamps nothing.
    if origin_kind in ("service", "stac"):
        dataset.last_checked_at = swap_time
    dataset.last_refreshed_at = swap_time

    quality_score = await compute_quality_score(
        session,
        dataset.table_name,
        metadata["column_info"],
        dataset,
        schema=_tenant_schema,
    )
    dataset.quality_detail = quality_score

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=new_version,
        source_filename=source_filename,
        source_format=source_format,
        feature_count=metadata["feature_count"],
        srid=metadata["srid"],
        # The effective type, so the version history and the dataset row it
        # describes never disagree about what this swap installed (#1373).
        geometry_type=effective_geometry_type,
        file_hash=file_hash,
        uploaded_by=actor_id,
    )
    session.add(version)
    await session.flush()
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor_id,
            action="reupload.commit",
            resource_type="dataset",
            resource_id=dataset.id,
            details={
                "version_number": new_version,
                "source_type": "service_url" if source_url else "file",
                "source_format": source_format,
                "source_filename": source_filename,
            },
        ),
    )
    return version
