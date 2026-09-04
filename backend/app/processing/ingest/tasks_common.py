"""Shared helpers, dataclasses, and app configuration for ingest tasks.

Contains the Procrastinate App instance, shared dataclasses (IngestContext,
StagingResult), job lifecycle helpers, metadata extraction utilities,
validation, and the finalize pipeline used across vector, raster, VRT,
and reupload workflows.
"""

import asyncio
import functools
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from app.core.async_io import await_draining

from procrastinate import App, PsycopgConnector

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import classify_origin, set_dataset_origin
from app.core.config import settings
from app.core.service_tokens import reset_registered_credential_secrets
from app.core.url_redaction import redact_url_credentials
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

    Billing-import-free seam: this function imports ONLY ``get_billing_extensions``
    from ``app.platform.extensions`` — zero billing / stripe symbols enter core.
    The dispatch is a no-op in OSS/single_tenant (DefaultBillingExtension has no
    ``on_usage_event``; the hasattr guard short-circuits immediately).

    Args:
        tenant_id: UUID string of the tenant.  When None (single_tenant or context
            not set), the function returns immediately — preserving byte-identical
            OSS behaviour with zero overhead.
        dimension: Billing dimension e.g. ``'ingest_jobs'``, ``'raster_egress_bytes'``.
        value: Event magnitude (default 1; use byte count for egress dimensions).
        event_id: Caller-provided dedup key — pass the Procrastinate job_id so
            ingest task retries remain idempotent at the DB layer.
        table_name: Optional dataset table_name.  Workers leave this None; the
            tile/OGC request path (1213-06 seam) passes it to drive the METER-03
            last_accessed_at signal through the same on_usage_event hook.

    Threat mitigations:
        T-1213-05 (DoS — failing billing breaks ingest): each extension is wrapped
            in try/except that logs a warning and continues.  Billing emit NEVER
            fails an ingest task.
        T-1213-06 (info disclosure — billing key leaks into core): this function
            imports zero billing/stripe symbols; verified by the grep gate in
            Task 3 verification.
        T-1213-07 (spoofing — cross-tenant ledger write): tenant_id flows from
            the worker's current_tenant_var (set by Phase 1208/1209 middleware),
            not from client input.
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
    # feat(#1218): typed origin_ref payload for the dataset the finalize
    # pipeline creates, minus the `kind` discriminator (derived from
    # source_format). Keys are validated against the per-kind allowlist in
    # app/platform/dataset_origin.py, so nothing unexpected — a credential
    # most of all — can reach the column. Callers pass their own payload
    # rather than one being inferred here: an incomplete ref is visible in
    # the stored JSON, whereas a plausible default would not be.
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


# fix(#1746): with no credential store configured — the default — the import
# and re-upload commit doors dispatch the service tasks with the raw service
# token sitting in the job's own kwargs. The worker deletes SUCCESSFUL rows
# only, so a terminal failure leaves `procrastinate_jobs.args->>'token'`
# holding that secret for as long as the row survives, which is the retention
# horizon at best and forever at worst. Deleting the key is safe because both
# service tasks are `retry=0`: the first exception IS the terminal one, and
# nothing will ever re-run the row from these args.
_PURGE_JOB_TOKEN_SQL = (
    "UPDATE catalog.procrastinate_jobs SET args = args - 'token' WHERE id = :job_id"
)


async def purge_queued_job_token(job_context: Any) -> None:
    """Best-effort: drop `token` from the running job's own queue row.

    Takes the Procrastinate ``JobContext`` rather than a bare id so the one
    caller that has it does not have to reach through it, and so a direct
    (non-worker) call passing ``None`` is a no-op instead of an error.

    Never raises. It runs while a real failure is being handled, and
    displacing that exception would cost the diagnosis. The warning names the
    row, never the value it failed to remove.
    """
    row_id = getattr(getattr(job_context, "job", None), "id", None)
    if row_id is None:
        return
    from sqlalchemy import text

    from app.core.db import async_session

    try:
        async with async_session() as session:
            await session.execute(text(_PURGE_JOB_TOKEN_SQL), {"job_id": row_id})
            await session.commit()
    except Exception:  # broad: a purge failure must not replace the real one
        structlog.get_logger().warning(
            "queued_job_token_purge_failed", procrastinate_job_id=row_id
        )


def purge_token_on_failure(fn):
    """Wrap a ``pass_context=True`` task so a dying attempt purges its token.

    Applied UNDER ``@tenant_task`` so the purge runs with the job's tenant
    context still bound. It absorbs the ``JobContext`` Procrastinate passes as
    the first positional argument, which keeps the task's own signature and
    keyword-only call shape unchanged — every direct caller (tests, ``.func``,
    ``.__wrapped__``) supplies no context, and with no context there is no row
    to purge and the wrapper is transparent.

    Catches ``Exception``, not ``BaseException``: a cancelled attempt (worker
    shutdown) leaves the row `doing`, which is not terminal, and the sweep in
    ``platform/jobs/sweep.py`` is the backstop for whatever settles it later.
    """

    @functools.wraps(fn)
    async def _wrapper(job_context: Any = None, /, **kwargs: Any) -> Any:
        try:
            return await fn(**kwargs)
        except Exception:  # broad: every terminal failure strands the token
            await purge_queued_job_token(job_context)
            raise

    return _wrapper


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

    Consolidates the 6× duplicated pattern from the ingest entry points
    (KISS-1). Mutates ``job.user_metadata`` in place, creating the list if
    absent. Caller is responsible for committing the session.

    The ``warning`` argument is a TypedDict from
    ``app.ingest.warnings.IngestJobWarning`` — one of
    ``ReservedRenameWarning``, ``DbfTruncationCollisionWarning``, or
    ``MercatorClipWarning``. Routing through the producer helpers in that
    module closes the type gap between the Python task code and the Pydantic
    ``JobStatusResponse`` (TYPE-1).
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

    Each field is ISO-8601-parsed independently. Values that fail to parse
    are dropped from the return tuple but recorded in the errors dict (keyed
    by field name, value is the raw input truncated to 100 chars) so the
    caller can persist them to ``job.user_metadata.temporal_parse_errors``
    for the UI to surface (N5).

    Extracted from ``ingest_raster`` to keep the parse branch unit-testable
    without spinning up a raster subprocess.
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
    edge, which is the dependency ``ProcessingPort`` exists to keep out.

    feat(#1472): ``manifest_job_metadata`` writes ``metadata.attribution`` into
    the job ledger at apply time, but nothing read it back, so a credit line an
    operator supplied to satisfy a source's terms was accepted and then dropped.
    This is the read-back, called once per ingest tail after the record exists
    and before the phase transaction commits.

    Only the manifest-namespaced keys are copied. The un-namespaced ``title`` /
    ``summary`` / ``visibility`` keys stay where they are, applied through
    ``create_dataset``'s own arguments, because non-manifest ingests (upload,
    service, STAC) set those too and this helper must be a no-op for them.
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

    Yields ``(session, job)`` where ``job`` is ``None`` if the IngestJob row
    vanished between phases — the caller is expected to early-return; the
    helper does NOT raise on missing rows because the existing pattern logs
    a warning and continues.

    Wraps the four pieces of boilerplate that previously appeared at every
    session-bracket call site in ``tasks_vector`` / ``tasks_raster``:

    - ``async_session()`` lifecycle (open/close).
    - ``SELECT IngestJob WHERE id = job_uuid``.
    - "vanished between phases" warning log + yield ``None`` on missing job.
    - rollback-on-exception (re-raises so the outer error handler still runs).

    The caller owns commits — multiple commits per phase block are normal
    ("load → mark running → commit → continue mutating → commit again" is
    the shape ``ingest_file`` actually uses).

    **Enforces the #100 greenlet rule** by keeping the SQLAlchemy session
    lifetime scoped to the ``async with`` block. Long-running CPU /
    asyncio subprocess work MUST happen OUTSIDE this block, never inside
    — see ``.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md``
    and the docstrings on ``ingest_file`` / ``ingest_raster``.

    The ``phase`` keyword (``"phase1"``, ``"phase2"``, ``"progress_write"``,
    etc.) is included in the missing-row warning so operators can tell
    which bracket lost the row.

    ``lock_and_statement_timeout_ms``, when given, issues ``SET LOCAL
    lock_timeout`` and ``SET LOCAL statement_timeout`` on this transaction
    BEFORE the SELECT below — fix(#1778 codex r6): a caller that set those
    timeouts itself, after entering this context manager, left the SELECT
    unprotected, and a SELECT can itself stall behind a lock the row's own
    later UPDATE would never even see (e.g. another session holding an
    ACCESS EXCLUSIVE lock on the table). ``None`` (the default) leaves the
    session on Postgres's server-wide default, unchanged for every other
    caller of this shared helper.

    fix(#1778 audit r11): ``require_status`` is None by default, matching the
    original ``attempt_id``-only fence — every job-row write in this codebase
    that goes through ``update_ingest_job_for_attempt`` (``heartbeat.py``)
    already defaults to requiring ``status == "running"`` on top of the
    attempt match; this helper was the one loader missing that second half.
    The gap: a stale sweep can fail a job on heartbeat timeout while the
    worker that owns it is only paused (a GC pause, a slow syscall) rather
    than dead, WITHOUT any retry having happened yet — so the row's
    ``attempt_id`` is unchanged and an ``attempt_id``-only fence still
    matches. The paused worker resumes, its phase-2 load passes, and it
    proceeds to write whatever that phase writes to a row the sweep already
    declared terminal. For a raster tail that write is an object-storage put,
    which no database rollback can undo, so admitting the row here is the
    actual leak, not just a stale read. Pass ``require_status="running"`` at
    any phase that must not resume this way; leave it ``None`` at a phase
    that legitimately runs before the row reaches ``running`` (phase 1, ahead
    of the claim) or one that must record something regardless of status
    (``error_write``).

    fix(#1778 audit r12): the round-11 check above closed the case where the
    sweep had ALREADY failed the row before this SELECT ran, but a plain
    SELECT is not a lock — the sweep can still fail the row in the window
    BETWEEN this read and the phase's own first irreversible write (a storage
    put), which is the same leak by a narrower door. When ``require_status``
    is given the SELECT below takes ``FOR NO KEY UPDATE``, so it holds a row
    lock for as long as this phase's session stays open, which every current
    ``require_status`` caller does across its own puts and up to its first
    ``commit()``. The sweep's own transition query is the one that must
    contend with this lock; see ``fail_stale_jobs`` in ``sweep.py`` and the
    startup recovery pass in ``worker.py``, both rewritten to a `SELECT ...
    FOR UPDATE SKIP LOCKED` candidate subquery so a row this lock protects is
    excluded from that pass rather than blocking (or, worse, aborting) the
    whole bulk transition. ``NO KEY UPDATE`` rather than plain ``UPDATE``: it
    still conflicts with anything that needs to exclude a concurrent writer,
    but not with a hypothetical ``FOR KEY SHARE`` reader this row's primary
    key might someday gain a foreign-key referrer against, which ``ingest_
    jobs`` does not have today but costs nothing to leave room for.
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
            # fix(#1778 audit r12): held through this phase's own first
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
            except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak
                await session.rollback()
                raise
            return
        try:
            yield session, job
        except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak
            await session.rollback()
            raise


def _bind_task_log_context(*, task_name: str, job_id: str, **extra: object) -> None:
    """Bind structlog contextvars for a worker task entry point (N1/R-18/R-24).

    The HTTP middleware uses ``structlog.contextvars.bind_contextvars`` to
    attach a ``request_id`` to every log line emitted during a request.
    Procrastinate tasks run outside the request loop, so they need their own
    correlation key — the ``job_id`` is the natural fit: concurrent ingests
    all log into the same stream and ``job_id`` lets operators filter to one
    upload's worth of events. Each task call clears any stale vars first so
    re-used workers cannot leak state from a prior job.
    """

    structlog.contextvars.clear_contextvars()
    # fix(#1770 round 43 P2): resets the credential-secret registry
    # (`core/service_tokens.register_credential_secret`) at the same
    # boundary, for the same reason -- a worker process runs many jobs in
    # sequence, and without a reset here a prior job's registered secret
    # would linger and scrub (or a stale entry would fail to scrub) a later,
    # unrelated job's log lines.
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
# ingest_file and reupload_file (fix(#541 review): reupload lacked the gate).
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

    fix(#430 BA-09): the task pulls the source to a private local copy (the
    caller unlinks that separately) but the `staging/{job_id}/` key it came
    from otherwise lives forever, and a failed run leaks it with no dataset
    ever created.

    fix(#1213 review r2): after a presigned completion `original_file_path` is
    the FROZEN copy, not the client-writable original — the completion door
    binds the job to the snapshot. So this is the block that reaps the frozen
    object, and `reap_presigned_staging_object` is the one that reaps the
    client's key. Both are needed; neither substitutes for the other. Shared
    between the vector and reupload tails so the two cannot drift, which is
    what let the reupload tail ship without it.

    fix(#1213 review r4): the storage-key signal is the `staging/` PREFIX, not
    a path rewrite. This used to require `file_path != original_file_path` on
    the theory that `resolve_file_path` rewrites the path when it downloads —
    true, but it conflates "was downloaded" with "came from storage", and a
    download that RAISES is exactly where the two come apart. On that path the
    rewrite never happened, the equality held, and the reaper skipped: an S3
    timeout left the frozen snapshot, possibly multi-GB, behind on a job that
    is terminally failed and (for reupload) not even retryable.

    The prefix is a sound discriminator on its own. A `staging/`-shaped
    `file_path` can only come from a presigned completion, and both presign
    endpoints refuse any backend but S3; every local-mode path is the absolute
    one `save_upload_file` returns, and service jobs carry a URL, so neither
    can match. Fan-out children are still skipped because siblings share the
    original; a retention policy reaps those. Reupload has no fan-out, so its
    caller leaves the default.

    fix(#1213 review r6): whether a FAILED job may be reaped depends on the
    caller, which is what `failed_source_replayable` states. The r4 version of
    this docstring claimed no later attempt could need the bytes because "the
    retry endpoint refuses reupload jobs" — true of reupload, and wrong of
    everything else. `_retry_capability` (platform/jobs/router.py) refuses only
    reupload, service-auth and analysis jobs; an ordinary failed import with a
    `staging/` file_path is retryable EXACTLY WHEN the object still exists, so
    deleting it here is what makes the advertised retry impossible. The stale
    purge is the designed eventual owner — its own comment says "failed keeps
    it for /jobs/{id}/retry (a failed-only endpoint)".

    So: ordinary-import callers pass True and retain on failure, reaping only
    on success; the reupload caller passes False, because `_retry_capability`
    refuses its jobs outright and nothing else will ever reap them. It is
    required rather than defaulted so #1210's raster adoption has to state
    which surface it is — raster is an ordinary-import surface and retains.

    Never raises — a failed sweep leaves an orphan, which beats failing a job
    whose work is already committed.
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

    fix(#1202 review r5): a completed presigned upload points ``file_path`` at
    the frozen copy, so every reaper that keys off ``file_path`` misses the
    staging key — the one the client's PUT URL can still recreate, outside
    size and quota accounting. Each terminal task tail calls this.

    Pass the result of ``owned_presigned_staging_key``, which is what decides
    there is anything to delete: it declines a fan-out child's inherited
    parent key, so a child can never reap the original its siblings read.

    Never raises. A failed sweep leaves an orphan, which is strictly better
    than failing a job whose work is already done and committed.
    """
    # fix(#1207): the terminal-status guard lives HERE, not in each tail. All
    # three ingest paths applied the identical condition, and a non-terminal
    # exit (job or dataset missing, heartbeat claim lost) must not sweep — the
    # attempt may be re-claimed and still needs the staging bytes.
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
    )
    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

    # validate_file_content wants a non-None filename for extension parsing;
    # fall back to the file's own basename so the content-check still runs.
    effective_filename = source_filename or Path(file_path).name
    validate_file_content(file_path, effective_filename)
    validate_file_size(file_path, max_size_mb * 1024 * 1024)
    validate_archive_safety(file_path, effective_filename)


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

    Returns True when the archive landed. fix(#1290 review): the raster tails
    call this to satisfy ADR-002 Decision 7 when a conversion was lossy, and
    they must not delete the staged upload unless the durable copy exists — so
    for them the outcome is a decision input, not just a breadcrumb. The vector
    callers ignore the return and are unaffected.

    Archive failures must NOT fail the ingest — the dataset is already
    committed at this point. Instead, record the failure on
    ``job.user_metadata`` so the UI and operators can audit (R-2).
    K1/KISS-3 extraction from ``ingest_file``; CLEANUP-4 extended it to
    support ``reupload_file`` by letting the caller override the log
    message and suppress the inline commit (reupload's caller commits
    the metadata mutation alongside the ``job.status = "complete"``
    transition so the flag is durable without a second round trip).

    When ``commit`` is True the metadata-update ``session.commit()`` is
    wrapped in its own try/except so that a transient DB error
    (deadlock, pooler drop) during the archive-failed flag persistence
    cannot flip the already-successful ingest into a ``failed`` job. If
    the commit fails, we log and give up — the dataset is still
    queryable, the operator just loses the ``archive_failed``
    breadcrumb for this attempt.
    """

    logger = structlog.get_logger()
    # fix(#1290 review): `file_path` is a temp download on any object-store
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

    fix(#1675): shared by initial import and the refresh/reupload executor so
    both replacement paths distrust driver-side paging the same way. Each
    page must grow the staging row count; a page that makes no progress
    aborts the fetch instead of looping or silently stopping short (the
    import path's original guard, extracted verbatim).

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
            # fix(#1675 codex r2): a server that returns SOME rows but fewer
            # than the requested page while the offset still advances by
            # page_size would silently skip records — positive growth is not
            # enough, the growth must be exact or a truncated copy swaps in
            # cleanly. A mid-fetch source mutation trips this too, which is
            # the safe direction: fail and retry against fresh counts.
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

    fix(#1018 review): the only production caller is ``reupload_file``
    (``tasks_reupload.py:337``). ``_ingest_vector_into_staging`` also calls it
    but is test-only, and NEW vector ingest does not: ``_finalize_ingest``
    (:1069) reruns these same steps inline at :1114-1177. This docstring used
    to read "shared by _ingest_vector_into_staging (new ingests)", which named
    the wrong path for the wrong reason.

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

    Two writers, one record each, the same split ``reupload_service`` uses:
    this owns the dataset-side verdict, ``record_refresh_failure`` owns the
    run row, and the caller passes ``contacted_origin=False`` there so the run
    finalizer does not write the dataset a second, weaker way.

    Guarded on the ``(origin_uri, origin_ref, source_format)`` triple the
    failing attempt read. A refresh that failed against an origin the dataset
    is no longer bound to must not mark the NEW binding missing — and for a
    rebind to an upload, nothing would ever correct it, because uploads have
    no probe and no refresh. Losing the race is a silent skip; there is
    nobody to tell from a background task, and the rebind's own commit
    already stated what is true now.

    ``health=None`` writes nothing at all. A failure that established nothing
    about the origin — a statement timeout, a search that could not be
    carried out — must leave the last conclusive verdict standing rather than
    replacing it with a guess.

    feat(#1266): lives here rather than in one strategy because the second
    strategy needs precisely this write. It arrived with #1313's registered-
    PostGIS refresh as a private helper; a copy in the STAC strategy would be
    a third spelling of the guard beside ``_record_failed_origin_contact``,
    and a guard with three spellings is a guard one of whose spellings is
    eventually wrong.
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

    Shared by ``reupload_file`` and ``reupload_service`` which have
    structurally identical exception handlers, and — fix(#1778) — by the
    import tasks that used to paste a narrower copy of the terminal write.
    What the copies were missing is what makes this the one place to fail a
    job: the
    ``redact_url_credentials`` backstop on the persisted message, the
    ``pending``-inclusive attempt fence (fix #1274 review: a worker-time
    refusal that raises before the claim must still finalize the job it owns,
    rather than leave it pending until the stale sweep), and the
    ``ingest_failed`` notification an operator has switched on.

    fix(#1778): ``staging_table`` is "" for the paths that have none (the VRT
    tail, whose artifacts are object keys its own ``finally`` reaps). An empty
    name skips the DROP outright, because interpolating it raises inside the
    best-effort guard below, which would log a cleanup failure on every VRT
    build failure and say nothing true.

    fix(#1778 codex r2): the ORDER is the contract. The failure row is
    written and committed BEFORE the drop is attempted, because a statement
    error aborts the whole PostgreSQL transaction and every later statement
    on that session raises until it is rolled back. With the drop first, a
    lock or statement timeout on it took the failure write down with it and
    the job sat `running` with no reason recorded. Anything added here that
    can fail belongs after the commit, in its own guarded block, with a
    rollback of its own wreckage.
    """
    from sqlalchemy import text
    from sqlalchemy import update as sa_update

    from app.processing.ingest.metadata import _qtable

    job_id = job.id
    completed_at = datetime.now(timezone.utc)
    # fix(#1277 review): the last boundary before this text becomes durable.
    # It fans out to three sinks below — the persisted error_message, the log
    # record, and the notification reason — so redacting here covers all of
    # them once, for every caller and every exception type, instead of three
    # times per path. Pattern-based, so it also covers the re-upload commit
    # door's token, which the worker never handles as a distinct value and so
    # cannot scrub by exact value. The exception is left unmodified: callers
    # that dispatch on its type or re-raise it are unaffected.
    error_message = redact_url_credentials(str(exc))
    await session.rollback()

    failure_update = sa_update(type(job)).where(type(job).id == job_id)
    if attempt_id is not None:
        # The fence is the attempt-id equality — a superseded attempt carries
        # a different token and can never match. `pending` is included
        # because a failure BEFORE the claim (fix #1274 review: the worker-
        # time SSRF refusal) must still finalize the job it owns; requiring
        # `running` made the legitimate attempt's pre-claim failures
        # invisible, leaving the job pending until the stale sweep.
        failure_update = failure_update.where(
            type(job).attempt_id == attempt_id,
            type(job).status.in_(("pending", "running")),
        )
    result = await session.execute(
        failure_update.values(
            status="failed",
            error_message=error_message,
            completed_at=completed_at,
        )
    )
    await session.commit()

    # fix(#1778 codex r2): the DROP runs AFTER the failure row is committed,
    # not before it. PostgreSQL aborts the whole transaction on any statement
    # error, so a drop that hit a lock or statement timeout left this session
    # unusable and the failure UPDATE that followed it raised
    # `current transaction is aborted` — the job stayed `running` until the
    # stale sweep and the reason nobody recorded was the one the user needed.
    # A best-effort cleanup must never be able to swallow the write it
    # precedes, so it goes last and rolls back its own wreckage.
    #
    # Placed before the rowcount return so this attempt's table is dropped
    # even when a newer attempt already owns the job row: the name is
    # attempt-scoped, so it is ours to clean up either way.
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

    if attempt_id is not None and not result.rowcount:
        return
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

    TEST-ONLY (#1018). Nothing in ``app/`` calls this. Every caller is a test:
    ``tests/test_staging_pipeline.py`` and
    ``tests/test_staging_pipeline_integration.py``. It exists to give those
    tests a callable seam over vector ingest's pre-staging half, which
    production runs inline inside its own job lifecycle.

    What it mirrors, and what it shares (fix(#1018 review)). Deliberately no
    line numbers: this docstring's own growth moved them twice while it was
    being written, so it names FUNCTIONS, which do not drift.

    - Pre-staging. ``run_ogr2ogr``, ``rename_reserved_columns``, the
      DBF-truncation check, then ``_detect_and_override_geometry`` under
      ``user_wants_geom``. ``tasks_vector.ingest_file`` runs the same four —
      it is the only production path with the override, so this helper's
      ``user_wants_geom`` branch has exactly one counterpart.
      ``tasks_reupload.reupload_file`` runs the first three and passes its
      detected geometry type straight to ``run_ogr2ogr`` instead
      (fix(#1018 review): an earlier draft claimed all four).
    - Staging. This helper calls the real ``_run_staging_pipeline``, so it does
      not fork those steps — but little else calls it either. The sequence
      exists in three independent places:

        1. ``_run_staging_pipeline`` — the full eight steps
           (ensure_geom_column, clip_to_mercator_bounds, add_4326_column,
           grant_reader_access, extract_metadata, detect_3d_metadata,
           promote_z_to_elev, get_sample_values). Reached in production only by
           ``tasks_reupload.reupload_file``, and by this helper.
        2. ``_finalize_ingest`` in this module — the same eight, inlined. New
           vector ingest, via ``tasks_vector.ingest_file``.
        3. ``tasks_reupload.reupload_service`` — a SHORTER copy: no 3D
           detection and no elevation promotion. Do not "fix" that by symmetry
           with the other two; find out why first.

      So a change to the shared six has three sites, and the tests here cover
      the one production reaches least.

    It intentionally performs no commits.
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
    The inner try/except splits "generation/upload failed" from
    "commit failed" so operators can tell which phase died when
    reading logs.

    INGEST-01 / Phase 1091-02: the caller MUST pass a FRESH session
    isolated from the outer ``_finalize_ingest`` session (use
    ``_job_phase_session(job_uuid, phase="quicklook")``). The
    ``asyncio.wait_for`` timeout in ``generate_vector_quicklook_with_timeout``
    cancels the inner ``await db.execute`` mid-flight on pathological
    geometry shapes (6018-multipolygon ``urban_areas_landscan_10m`` was
    the live trigger). The cancellation poisons the asyncpg cursor,
    and the defensive ``session.rollback()`` below expires every loaded
    ORM attribute (``expire_on_rollback`` defaults to True). If this
    rollback fires on the same session that holds the outer
    ``dataset.record`` relationship, the next access (e.g.,
    ``defer_embedding`` in ``app/processing/embeddings/helpers.py``)
    trips ``MissingGreenlet`` on the lazy-refresh. Passing a fresh
    session keeps that surface isolated. See
    ``.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md``.

    Internal phase ordering (INGEST-01 iter-2):

    1. **Generate phase:** call ``generate_vector_quicklook_with_timeout``
       AND upload the resulting bytes to storage. This phase reads from
       ``session`` (the bounds + geom queries inside
       ``quicklook.generate_vector_quicklook``); ``asyncio.wait_for``
       inside the wrapper may cancel the geom query mid-flight on
       pathological geometry, leaving the asyncpg cursor in an
       invalid-transaction state ("Can't reconnect until invalid
       transaction is rolled back" — sqlalchemy.org/e/20/8s2b). The
       wrapper catches the ``asyncio.TimeoutError`` and returns
       ``_blank_canvas(size)`` bytes per quicklook.py:235-236, so the
       upload still succeeds.

    2. **Recovery rollback:** ``await session.rollback()`` AFTER the
       upload AND BEFORE the URI write. This is a no-op on the clean
       path (no open transaction) and is the documented recovery for
       the poisoned-cursor state on the timeout path. Without this
       step, the subsequent ``session.commit()`` for the URI write
       fails with the "Can't reconnect" error and the URI is never
       persisted (INGEST-01 iter-1 live verification gap: blank canvas
       uploaded to storage but ``quicklook_256_uri`` stayed NULL on
       ``urban_areas_landscan_10m`` because the cursor was still
       poisoned at commit time).

    3. **URI write:** re-``merge`` the dataset (the pre-generation
       merge entry was discarded by the rollback in step 2) and set
       ``merged_dataset.quicklook_256_uri = ql_key`` so the write
       lands in the fresh session's identity-map entry.

    4. **Commit phase:** ``await session.commit()`` persists the URI.
       The defensive try/except handles any residual commit failure
       (e.g., DB pool drop, deadlock) — log a phase=commit warning
       and rollback. The dataset row itself is already committed by
       the outer ``_finalize_ingest``'s terminal commit so a failed
       quicklook commit only loses the URI breadcrumb.

    The outer session's view of the dataset is stale w.r.t.
    ``quicklook_256_uri`` after this returns — callers that need the
    URI must ``session.refresh(dataset)`` on the outer session, or
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

    # INGEST-01 iter-2: explicit recovery from any asyncio.wait_for
    # cancellation that left the asyncpg cursor in an invalid-transaction
    # state during the geom query. This is a no-op on the clean path and
    # the documented recovery for the "Can't reconnect until invalid
    # transaction is rolled back" error (sqlalchemy.org/e/20/8s2b). Without
    # this rollback, the post-upload commit below fails on the timeout
    # path and the URI never persists.
    #
    # WR-01 (post-1091 review): the rollback() and merge() calls are
    # themselves asyncpg IO and may raise OperationalError (or similar)
    # if the connection died between upload and recovery — the exact
    # poisoning scenario we are defending against. Without the wrapper,
    # an escape here propagates through `_job_phase_session`'s rollback-
    # on-exception handler → out of `_finalize_ingest` → into the outer
    # task-entry-point `except Exception`, which writes `status="failed"`
    # on the job row. Because the dataset row was already committed by
    # the outer `_finalize_ingest`, that produces dataset-published +
    # job-failed — the exact disagreement OPS-01 surfaces. Wrap the
    # recovery block to preserve the documented "non-fatal" contract:
    # log a `phase=recovery` warning and return; the URI breadcrumb is
    # lost but the dataset stays published.
    try:
        await session.rollback()

        # Re-merge `dataset` into the now-clean session — the pre-generation
        # merge entry (if any) was discarded by the rollback above. Write the
        # URI on the merged copy so the commit below persists it.
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

    Steps:
    - Normalize geometry column, clip to valid bounds, add 4326 column
    - Grant reader access
    - Extract column info and sample values
    - Create dataset record
    - Compute quality score
    - Commit job + dataset atomically
    - Generate quicklook thumbnail (non-fatal)
    - Invalidate caches and backfill embedding

    Args:
        ctx: IngestContext bundle of finalize parameters. See the dataclass
            docstring for field descriptions (K7 refactor).

    Returns:
        The created Dataset ORM instance.
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
    # fix(#430 codex r16): create_dataset defaults the record to 'published',
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
    # fix(#1271 review): a first service or STAC ingest fetched its bytes
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
    #
    # INGEST-01 / Phase 1091-02: the quicklook block opens its OWN
    # session via `_job_phase_session(job_uuid, phase="quicklook")` so
    # the `asyncio.wait_for` cancellation inside
    # `generate_vector_quicklook_with_timeout` cannot poison the outer
    # `session`. Without this isolation, the cancellation wedges the
    # asyncpg cursor on `session`, the defensive `session.rollback()`
    # inside `_generate_quicklook` expires every ORM attribute on
    # `dataset` (including the eagerly-loaded `dataset.record`
    # relationship — `expire_on_rollback` defaults to True), and the
    # next outer `defer_embedding` call at line ~840 trips
    # `MissingGreenlet` on the lazy-refresh of `dataset.record.id`.
    # The fresh session keeps that failure mode entirely off `session`.
    # See `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md`.
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

    fix(#394) B-019/VT-01: reupload swaps the entire table under the same
    ``table_name`` but was the one write path that never purged the Valkey
    tile cache — the cache key has no content-version dimension and the ETag
    is computed over the cached bytes, so stale geometry/attributes kept
    being 304-served for up to ``tile_cache_ttl`` after every reupload.
    Mirrors the feature-edit path (``features/router.py``): called AFTER the
    owning transaction commits so a concurrent tile request cannot re-cache
    pre-swap rows, and never raises (the provider swallows backend errors).
    """
    from app.platform.cache.provider import get_tile_cache

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(table_name)


async def bump_tile_cache_version_atomic(
    session: "AsyncSession", Dataset: Any, dataset_id: uuid.UUID
) -> int | None:
    """Roll the ``_v=`` cache-buster from a writer that holds no row lock.

    fix(#1738 round 1): the sibling of ``Dataset.bump_tile_cache_version``,
    for the one case that helper cannot serve. That helper reads the counter
    off a loaded instance and writes back an absolute value, which is correct
    only while the caller holds the datasets row — the way
    ``refresh_postgis``'s phase 3 does, under the ``FOR UPDATE`` it takes for
    its superseded guard.

    A writer without that lock cannot use it, and taking the lock would not
    help: the feature-edit routers (``features/router.py``) bump through a
    plain read-modify-write and never lock the row, so an absolute write
    computed from a read they took earlier lands on top of anything committed
    in between. One side locking does not serialize a race the other side is
    not playing. ``tile_cache_version = tile_cache_version + 1`` in the
    database does, because the increment is evaluated against the row as it
    is at write time.

    Returns the new value, so the caller reports and logs the version it
    actually published rather than the one it hoped for. Still called in the
    same transaction as the tile-content change it describes, which is the
    contract on both spellings.
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy import update as sa_update

    return await session.scalar(
        sa_update(Dataset)
        .where(Dataset.id == dataset_id)
        .values(tile_cache_version=sa_func.coalesce(Dataset.tile_cache_version, 1) + 1)
        .returning(Dataset.tile_cache_version)
        .execution_options(synchronize_session=False)
    )


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

    fix(#1313 review round 5): ``extract_metadata`` derives the geometry type
    by sampling a row (``GeometryType(geom) ... LIMIT 1``), so a spatial table
    that has been emptied reports None — indistinguishable, from the
    measurement alone, from a table that never had geometry at all. Writing
    that None reclassified the dataset as tabular, and the consequences are
    not cosmetic: ``_require_feature_table`` refuses feature writes to a
    dataset whose ``geometry_type`` is None, so a refresh of an emptied table
    would lock the API out of ever repopulating it, and the builder drops its
    layers as unsupported.

    ``geometry_columns`` answers the question the rows cannot: it describes
    the COLUMN. A row here means the relation is spatial whatever it
    currently holds; no row means it genuinely is not.

    fix(#1373): lives here rather than in ``tasks_postgis_refresh`` because the
    reupload swap reaches the identical trap from the other direction — an
    empty spatial FILE stages a relation whose geom column is right there — and
    two spellings of this question are how the two paths end up disagreeing
    about the same dataset.
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

    One rule in one place: the write applies it and the quality score is
    computed under it, and a second spelling of this precedence is how those
    two end up describing different datasets.

    - a sampled row is what the data actually is;
    - no rows but a specific declared column type is what the column accepts;
    - no rows and a generic ``geometry`` column establishes only that the
      relation is spatial, so the catalog keeps what it last measured, and
      falls back to the generic sentinel when it has measured nothing;
    - no ``geom`` column at all is genuinely not spatial, and the only case
      that yields None.

    fix(#1382 review r1): that fallback is the difference between the rule and
    its own first sentence. Returning ``stored`` unconditionally meant a
    generic empty column over a dataset the catalog had never measured (an
    empty mixed-geometry file over a tabular dataset, or a retry against a row
    the old bug had already NULLed) resolved to None and stayed classified
    ``table`` — locked out of feature writes, against a relation that plainly
    has a geometry column. ``GEOMETRY`` is how this codebase already spells
    "spatial, subtype unknown": ``chk_datasets_geometry_type`` admits it,
    ``_validate_geometry_type`` accepts every subtype under it (#430 BA-32),
    and the builder routes it to the mixed adapter (#430 r23).
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

    ``refresh_attribute_metadata`` touches that row only when it is handed a
    non-null ``geometry_type``, and excludes ``geom`` from its removed-column
    sweep by name. That is right for a caller that replaces a table's contents
    while keeping its shape, and wrong for the two callers whose relation can
    lose its geometry column while keeping its identity: the
    registered-PostGIS refresh, whose owner can drop the column out from under
    the catalog, and the reupload swap, which installs a CSV over a shapefile.
    Left current, the attributes API and the validation service go on
    advertising a geometry field the relation no longer has.

    fix(#1313 review round 7) established the retirement on the refresh path;
    fix(#1380) gives the reupload swap the same behaviour from this one
    function rather than a second copy of it. Feed it the EFFECTIVE geometry
    type — the same value handed to ``refresh_attribute_metadata`` — and call
    it unconditionally: the null check lives in here so that a caller cannot
    hold one half of the pair and forget the other, which is exactly how the
    two paths came to disagree.
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

    _FIRST_TIMEOUT = "5s"
    _RETRY_TIMEOUT = "15s"
    _RETRY_SLEEP_MS = 200

    try:
        async with session.begin_nested():
            await _swap_with_timeout(_FIRST_TIMEOUT)
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
            sleep_ms=_RETRY_SLEEP_MS,
            hint=(
                "AccessExclusiveLock contention on first swap attempt — "
                "likely autovacuum collision; retrying once with longer "
                "timeout. Correlate with pg_stat_activity / pg_stat_user_tables."
            ),
        )
        await asyncio.sleep(_RETRY_SLEEP_MS / 1000.0)

        # Retry inside its own SAVEPOINT so a second failure surfaces cleanly.
        async with session.begin_nested():
            await _swap_with_timeout(_RETRY_TIMEOUT)

        structlog.get_logger().info(
            "reupload_swap_retry_succeeded",
            dataset_id=str(dataset.id),
            table_name=table_name,
            attempt=2,
            retry_timeout_seconds=15,
        )

    # fix(#1373): resolve the geometry type ONCE, from the relation the swap
    # just installed, and use that one value everywhere below.
    #
    # `extract_metadata` samples a row (`GeometryType(geom) ... LIMIT 1`), so a
    # spatial file carrying zero features — or only NULL geometries — measures
    # None while the relation it staged still has its geometry column. Writing
    # that None reclassified the dataset as tabular: `_require_feature_table`
    # then refuses feature writes, so the API could never repopulate the table
    # through GeoLens, and the builder drops its layers as unsupported.
    # `_declared_geometry_type` supplies the evidence the rows cannot, and the
    # precedence is the refresh path's — the same helpers, imported, not a
    # second spelling of the rule (#1313 fell into this trap first).
    #
    # Read before the write below, because `stored` is the PRE-swap value: a
    # generic `geometry` column with no rows establishes only that the relation
    # is spatial, so the honest answer is what the catalog last measured.
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

    # Update dataset metadata in the same transaction as swap
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

    # fix(#1314): a reupload can replace a spatial dataset with a non-spatial
    # one (or the reverse), and the auto-generated `record_distributions` rows
    # are as stale afterwards as they are on the refresh path — same one-shot
    # generation at creation, same never re-derived. Gated on the modality FLIP
    # for the same reason as there: reconcile normalizes `is_primary`, and a
    # reupload that kept the modality has no business rewriting it.
    #
    # fix(#1373): the flip is read off the EFFECTIVE type, which is also the
    # value written to `geometry_type` and `record_type` above — so the three
    # cannot disagree about one swap. #1314 review round 2 reached the same
    # answer for the demote alone by asking `_table_has_geometry` whether the
    # relation still had its geom column, because reconciling on the sampled
    # None would DELETE the GeoPackage, GeoJSON, Shapefile, GeoParquet and
    # vector-tile rows of a still-spatial dataset. That question is now
    # subsumed: `_declared_geometry_type` returns None exactly when there is no
    # geom column, which is the only case the precedence resolves to None.
    #
    # The promote widens accordingly, and deliberately: #1314 let a TABULAR
    # dataset reuploaded from an empty spatial file fall through, on the
    # grounds that nothing measured a type so `dataset.geometry_type` stayed
    # None too. It no longer does — a specific declared column type is now
    # written — so the distributions follow it.
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
    # fix(#525 B-038): tile_version now reads tile_cache_version (not
    # current_version), so reupload must roll it too or the _v= tile-URL
    # cache-buster stops changing on the largest content mutation of all.
    dataset.bump_tile_cache_version()
    dataset.record.updated_by = actor_id
    if source_url is not None:
        dataset.source_url = source_url

    # fix(#1218 review): restamp the binding, which must describe where the
    # CURRENT bytes came from. Without this a file reupload of a
    # registered-postgis or service dataset leaves the old pointer in place,
    # so the API serves a computed origin of `upload` beside a stored ref
    # still claiming `postgis` — and a later refresh would follow the stale
    # pointer. The kind is derived from the NEW source_format exactly as first
    # ingest derives it, so a service reupload stays a service origin instead
    # of being flattened to an upload, and a file reupload correctly clears
    # origin_uri (an upload has no remote pointer) while leaving the
    # user-editable source_url alone.
    #
    # #1220's shared refresh executor takes over both writes below for
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
    # fix(#1271 review): set_dataset_origin just cleared the probe state, and
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
