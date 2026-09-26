"""Shared helpers, dataclasses, and app configuration for ingest tasks.

Contains the Procrastinate App instance, the ``IngestContext`` dataclass, job
lifecycle helpers, metadata extraction utilities, and the finalize pipeline
used across vector, raster, VRT, and reupload workflows. The staging
acquisition and cleanup half lives in ``tasks_staging``.
"""

import asyncio
import functools
import hashlib
import json
import re
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from procrastinate import App, PsycopgConnector

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import classify_origin, set_dataset_origin
from app.core.config import settings
from app.core.service_tokens import reset_registered_credential_secrets
from app.core.url_redaction import redact_exception_text
from app.processing.embeddings.helpers import defer_embedding
from app.platform.storage import get_storage

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.processing.ingest.catalog_projection import Measurement
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
        "app.processing.ingest.tasks_tileset",
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
#
# fix(#1710): `url` joins `token` as a key worth purging. A submitted file URL
# can be a presigned S3 or SAS link, which is bearer-equivalent, and it sits in
# the row for the whole transfer plus forever after any non-successful
# delivery. The statement itself stays in platform/jobs/sweep.py (#1755 item
# 12), so there is still one home for it.
async def purge_queued_job_arg(job_context: Any, *, arg_key: str = "token") -> None:
    """Best-effort: drop one credential-bearing key from this job's queue row.

    Takes the Procrastinate ``JobContext`` (not a bare id) so a direct call
    passing ``None`` is a no-op instead of an error.

    Never raises — a failure caller runs this while a real exception is being
    handled, and displacing that would cost the diagnosis. The warning logs
    only the row id and the key name, never the value it failed to remove.
    """
    row_id = getattr(getattr(job_context, "job", None), "id", None)
    if row_id is None:
        return
    from app.core.db import async_session
    from app.platform.jobs.sweep import purge_queue_row_args

    try:
        async with async_session() as session:
            await purge_queue_row_args(session, [row_id], arg_key=arg_key)
    except Exception:  # broad: a purge failure must not replace the real one
        structlog.get_logger().warning(
            "queued_job_arg_purge_failed",
            procrastinate_job_id=row_id,
            arg_key=arg_key,
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
            await purge_queued_job_arg(job_context)
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


def _manifest_text(user_metadata: dict, key: str) -> str | None:
    """A manifest-namespaced string value, or None when it has nothing in it."""
    value = user_metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _apply_manifest_tags(session: Any, record: Any, tags: Any) -> None:
    """Add ``metadata.tags`` as theme keywords the record does not already have.

    fix(#2039): a re-apply reaches the reupload swap with the same list, and
    ``uq_record_keyword`` is a unique index — an unconditional insert would
    fail the whole swap transaction on the second apply of one manifest.
    """
    if not isinstance(tags, list):
        return
    wanted = {t.strip().lower() for t in tags if isinstance(t, str) and t.strip()}
    if not wanted:
        return

    from sqlalchemy import func, inspect as sa_inspect, select

    from app.platform.extensions import get_processing_port

    port = get_processing_port()
    # fix(#2039): the keyword class off the relationship of the record class the
    # port already exposes — a new port accessor would be a required method, so
    # every overlay would have to re-pin, and processing/ cannot import this ORM.
    keywords_rel = sa_inspect(port.get_record_orm_class()).relationships["keywords"]
    RecordKeyword = keywords_rel.mapper.class_
    # fix(#2039 review): the rows `uq_record_keyword` would actually collide
    # with, spelled as that index spells them — COALESCE, because a stored ''
    # collides with the NULL written below — and case-folded like `wanted`. A
    # record-wide read skipped a manifest tag that existed under another type.
    existing = {
        k.lower()
        for k in await session.scalars(
            select(RecordKeyword.keyword).where(
                RecordKeyword.record_id == record.id,
                RecordKeyword.keyword_type == "theme",
                func.coalesce(RecordKeyword.vocabulary_uri, "") == "",
            )
        )
    }
    for keyword in sorted(wanted - existing):
        session.add(
            RecordKeyword(record_id=record.id, keyword=keyword, keyword_type="theme")
        )


async def apply_manifest_record_metadata(
    session: Any, record: Any, user_metadata: dict | None
) -> None:
    """Copy manifest-supplied catalog metadata onto a freshly created record.

    ``record`` is duck-typed rather than annotated ``Record``: importing the
    catalog ORM class here would add a ``processing`` -> ``modules.catalog``
    edge, which ``ProcessingPort`` exists to keep out.

    feat(#1472): the read-back for ``manifest_job_metadata``'s
    ``metadata.attribution`` write, called once per ingest tail after the
    record exists and before the phase transaction commits — without it an
    operator-supplied attribution credit was accepted then silently dropped.

    fix(#2039): ``license``, ``organization`` and ``tags`` are the same
    shape of accepted-then-dropped field, and every manifest under
    ``examples/manifests/`` sets them.

    Only manifest-namespaced keys are copied; un-namespaced ``title``/
    ``summary``/``visibility`` go through ``create_dataset``'s own
    arguments, since non-manifest ingests set those too and this helper
    must be a no-op for them.
    """
    if not user_metadata:
        return
    attribution = _manifest_text(user_metadata, "manifest_attribution")
    if attribution is not None:
        record.attribution = attribution
    license_name = _manifest_text(user_metadata, "manifest_license")
    if license_name is not None:
        record.license = license_name
    organization = _manifest_text(user_metadata, "manifest_organization")
    if organization is not None:
        record.source_organization = organization
    await _apply_manifest_tags(session, record, user_metadata.get("manifest_tags"))


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
        if require_status is not None:
            from app.processing.ingest.tasks_raster_common import note_publishing_xid

            # Read before the row lock; a phase whose commit publishes probes by it.
            await note_publishing_xid(session)
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
    planned_ids: tuple[int, ...] | None = None,
) -> None:
    """Guarded ArcGIS paging shared by initial import and refresh/reupload.

    Both doors distrust driver-side paging: a page that makes no row-count
    progress aborts rather than looping or silently stopping short.

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
    imported_rows, append = 0, False
    force_arcgis_geojson = bool(planned_ids and max(planned_ids) > (1 << 31) - 1)
    if planned_ids is not None:
        planned_chunk_size = min(page_size, _ARCGIS_OBJECT_ID_FETCH_CHUNK_SIZE)

        def _fits_gdal_get_url(object_ids: tuple[int, ...]) -> bool:
            # Use the same builder as the actual import so this includes the
            # ArcGIS options and a query-form credential without exposing the
            # resulting URL in an error or log.
            page_source, _ = port.build_gdal_source(
                service_type_raw,
                source_url,
                layer_name,
                layer_id,
                token=token,
                order_field=order_field,
                result_limit=None,
                result_offset=None,
                object_ids=object_ids,
                force_arcgis_geojson=force_arcgis_geojson,
            )
            return len(page_source.encode("utf-8")) <= _ARCGIS_GDAL_GET_URL_MAX_BYTES

        page_specs: list[tuple[int | None, tuple[int, ...] | None]] = []
        start = 0
        while start < len(planned_ids):
            remaining = min(planned_chunk_size, len(planned_ids) - start)
            candidate = planned_ids[start : start + remaining]
            if _fits_gdal_get_url(candidate):
                page_specs.append((None, candidate))
                start += remaining
                continue

            # A count-only chunk can exceed the URL limits of proxies when
            # object IDs are long signed 64-bit values. Find the largest
            # prefix that the actual GDAL GET request can transport.
            lower, upper = 1, remaining - 1
            largest_fitting = 0
            while lower <= upper:
                midpoint = (lower + upper) // 2
                if _fits_gdal_get_url(planned_ids[start : start + midpoint]):
                    largest_fitting = midpoint
                    lower = midpoint + 1
                else:
                    upper = midpoint - 1
            if largest_fitting == 0:
                raise ogr.IngestionError(
                    "ArcGIS object-ID request exceeds the safe URL transport budget."
                )
            page_specs.append((None, planned_ids[start : start + largest_fitting]))
            start += largest_fitting
    else:
        page_specs = [(offset, None) for offset in range(0, feature_count, page_size)]
    for offset, object_ids in page_specs:
        page_source, page_layer = port.build_gdal_source(
            service_type_raw,
            source_url,
            layer_name,
            layer_id,
            token=token,
            order_field=order_field,
            result_limit=None if object_ids is not None else page_size,
            result_offset=offset,
            object_ids=object_ids,
            force_arcgis_geojson=force_arcgis_geojson,
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
                f"at offset {offset if offset is not None else 'ID chunk'}; upstream pagination may be "
                "unsupported or returned an empty page."
            )
        expected = (
            len(object_ids)
            if object_ids is not None
            else min(page_size, feature_count - offset)
        )
        if grew != expected:
            # fix(#1675): positive growth alone isn't enough — a server
            # returning fewer rows than requested while offset advances by
            # page_size would silently skip records. A mid-fetch source
            # mutation trips this too; failing is the safe direction.
            raise ogr.IngestionError(
                f"ArcGIS page at offset {offset if offset is not None else 'ID chunk'} returned {grew} rows where "
                f"{expected} were expected; the server may cap responses "
                "below its advertised page size or the source changed "
                "mid-fetch. Refusing to continue with a potentially "
                "incomplete copy."
            )
        imported_rows = next_imported_rows
        if on_page is not None:
            await on_page(imported_rows, feature_count)
        append = True


_ARCGIS_SAFE_OID_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_ARCGIS_MAX_OID = (1 << 63) - 1
# ``build_gdal_source`` bounds the query-form objectIds request to this size.
# The normal service page limit can be larger, so planned-ID fetches must not
# reuse it unchecked.
_ARCGIS_OBJECT_ID_FETCH_CHUNK_SIZE = 1_000
# Keep GET requests below common proxy limits. The source builder includes the
# driver prefix, endpoint, ArcGIS query parameters, and any query-form token.
_ARCGIS_GDAL_GET_URL_MAX_BYTES = 8 * 1024


def _arcgis_staged_oid_digest(oid_field: str, ids: list[int]) -> str:
    payload = json.dumps(
        {"oid_field": oid_field, "ids": sorted(ids)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


async def verify_arcgis_staged_oid_coverage(
    session: Any,
    *,
    schema: str,
    table_name: str,
    oid_field: str,
    planned_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Compare staged source OIDs with one bounded, preplanned ArcGIS set.

    The `gid` primary key is GeoLens-local (`-lco FID=gid`) and must never be
    treated as upstream identity. This returns compact evidence; raw source
    IDs remain only in worker memory.
    """
    from sqlalchemy import text

    from app.processing.ingest.metadata import _qtable, get_column_info

    if not _ARCGIS_SAFE_OID_FIELD.fullmatch(oid_field):
        return {
            "status": "unavailable",
            "reason": "unsupported_oid_field",
            "oid_field": oid_field,
        }
    columns = await get_column_info(session, table_name, schema=schema)
    matching_columns = [
        column["name"]
        for column in columns
        if isinstance(column.get("name"), str)
        and column["name"].casefold() == oid_field.casefold()
    ]
    if len(matching_columns) != 1:
        return {
            "status": "unavailable",
            "reason": "source_oid_not_preserved",
            "oid_field": oid_field,
        }

    # The identifier is constrained above; table/schema use the existing
    # catalog table validator. The limit detects an ignored objectIds filter
    # without materializing an unbounded source response in worker memory.
    safe_oid_field = matching_columns[0]
    query = (
        f'SELECT "{safe_oid_field}", COUNT(*) '
        f"FROM {_qtable(table_name, schema=schema)} "
        f'GROUP BY "{safe_oid_field}" '
        f"LIMIT {len(planned_ids) + 1}"
    )
    result = await session.execute(
        # codeql[py/sql-injection]
        text(query)
    )
    rows = result.all()
    if len(rows) > len(planned_ids):
        return {
            "status": "mismatched",
            "reason": "unexpected_source_oid_cardinality",
            "oid_field": oid_field,
            "planned_count": len(planned_ids),
            "staged_distinct_count": len(rows),
        }

    staged_ids: list[int] = []
    duplicate_count = 0
    invalid_count = 0
    for source_id, occurrences in rows:
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id < 0
            or source_id > _ARCGIS_MAX_OID
        ):
            invalid_count += int(occurrences)
            continue
        staged_ids.append(source_id)
        if occurrences > 1:
            duplicate_count += int(occurrences) - 1

    planned = set(planned_ids)
    staged = set(staged_ids)
    missing_count = len(planned - staged)
    unexpected_count = len(staged - planned)
    status = (
        "matched"
        if not invalid_count
        and not duplicate_count
        and not missing_count
        and not unexpected_count
        else "mismatched"
    )
    return {
        "status": status,
        "oid_field": oid_field,
        "planned_count": len(planned_ids),
        "staged_distinct_count": len(staged),
        "missing_count": missing_count,
        "unexpected_count": unexpected_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "staged_id_set_digest": _arcgis_staged_oid_digest(oid_field, staged_ids),
    }


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


async def _detect_3d_and_promote_elev(
    session, table_name: str, metadata: dict, *, schema: str
) -> dict:
    """Return the table's 3D facts and give a 3D point table its ``elev`` column.

    Re-reads ``metadata["column_info"]`` when ``elev`` is added.
    """
    from app.processing.ingest.metadata import (
        detect_3d_metadata,
        get_column_info,
        promote_z_to_elev,
    )

    three_d = await detect_3d_metadata(session, table_name, schema=schema)
    if three_d.get("is_3d") and await promote_z_to_elev(
        session, table_name, metadata.get("geometry_type"), schema=schema
    ):
        metadata["column_info"] = await get_column_info(
            session, table_name, schema=schema
        )
    return three_d


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
    from app.processing.ingest.metadata import compute_quality_score
    from app.processing.ingest.tasks_staging import _run_staging_pipeline

    port = get_processing_port()

    session = ctx.session
    job = ctx.job
    table_name = ctx.table_name
    user_metadata = ctx.user_metadata
    source_filename = ctx.source_filename

    _schema = _current_tenant_schema()
    staging = await _run_staging_pipeline(
        session,
        table_name=table_name,
        has_geometry=ctx.has_geometry,
        effective_srid=ctx.effective_srid,
    )
    _append_mercator_clip_warning(job, staging.mercator_clip)
    has_geometry = staging.has_geometry
    metadata = staging.metadata
    three_d = staging.three_d
    sample_values = staging.sample_values

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
    await apply_manifest_record_metadata(session, dataset.record, user_metadata)

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
    from app.platform.jobs import ledger

    await ledger.complete(
        session,
        job.id,
        ctx.attempt_id or job.attempt_id,
        values={
            "dataset_id": dataset.id,
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


class SourceURLRefused(RuntimeError):
    """The fetch-time safety check refused a service URL."""


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

    ING-06 / P2-08: used by ``_install_reupload_table`` to gate its single
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

    Tile keys carry the dataset's ``tile_cache_version``, so an API process
    stops reading pre-swap entries once it re-reads the dataset row. The purge
    makes the new rows visible sooner wherever it can reach the cache: a
    process still holding the old version re-renders from the swapped table.
    Call AFTER the owning transaction commits, so a concurrent tile request
    can't re-cache pre-swap rows. Never raises.
    """
    from app.platform.cache.provider import get_tile_cache

    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(table_name)


# The AccessExclusiveLock budget the reupload swap DDL spends: first attempt,
# the single retry, and the pause between them (#1917).
_SWAP_FIRST_TIMEOUT = "5s"
_SWAP_RETRY_TIMEOUT = "15s"
_SWAP_RETRY_SLEEP_MS = 200


async def _install_reupload_table(
    session, *, dataset, staging_table: str, measurement: "Measurement"
) -> None:
    """Rename the staging table over the dataset's live table, in the caller's transaction.

    The renames run on their own lock budget and the transaction's
    ``lock_timeout`` is restored afterwards. The caller takes the catalog rows
    next, then calls :func:`_write_reupload_catalog`.
    """
    from sqlalchemy import text

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

    # fix(#448): belt-and-braces after the swap — the staging pipeline is
    # responsible for the GIST index, but a re-ingest of a table that already
    # lost its index (the IF-NOT-EXISTS name-collision regression) must
    # self-heal here rather than serve full-scan tiles until the next audit.
    if measurement.geometry_type is not None:
        from app.processing.ingest.metadata import ensure_geom_4326_gist_index

        await ensure_geom_4326_gist_index(session, table_name, schema=_tenant_schema)


async def _write_reupload_catalog(
    session,
    *,
    dataset,
    measurement: "Measurement",
    user_id: str,
    source_filename: str | None,
    source_format: str | None,
    original_srid: int | None,
    source_url: str | None = None,
    file_hash: str | None = None,
    origin_ref: dict[str, Any] | None = None,
) -> tuple[Any, dict]:
    """Write what the installed table holds onto the catalog rows the caller holds.

    ``measurement`` is ``catalog_projection.measure`` of the staging table,
    taken in this transaction.

    ``origin_ref`` carries the typed per-origin payload for the bytes this
    swap installs, minus the ``kind`` discriminator (derived from
    ``source_format``). Same contract as ``IngestContext.origin_ref``: keys go
    through the per-kind allowlist, and callers supply their own rather than
    one being inferred here.

    Returns the ``DatasetVersion`` this swap produced, flushed so the run row
    can link to its id, and the schema diff the projection computed under the
    lock, which is the diff the run stores. The tile-cache bump is the
    caller's.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )  # LAZY — preserved per D-17
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.catalog_projection import project

    DatasetVersion = get_processing_port().get_dataset_version_orm_class()
    actor_id = uuid.UUID(user_id)
    new_version = dataset.current_version + 1

    schema_diff = await project(session, dataset, measurement)

    dataset.source_format = source_format
    dataset.source_filename = source_filename
    dataset.original_srid = original_srid
    dataset.current_version = new_version
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

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=new_version,
        source_filename=source_filename,
        source_format=source_format,
        feature_count=measurement.metadata.get("feature_count"),
        srid=measurement.metadata.get("srid"),
        # The effective type, so the version history and the dataset row it
        # describes never disagree about what this swap installed (#1373).
        geometry_type=measurement.geometry_type,
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
    return version, schema_diff
