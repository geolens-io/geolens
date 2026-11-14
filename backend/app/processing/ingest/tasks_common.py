"""Shared helpers, dataclasses, and app configuration for ingest tasks.

Contains the Procrastinate App instance, the ``IngestContext`` dataclass, job
lifecycle helpers, metadata extraction utilities, and the finalize pipeline
used across vector, raster, VRT, and reupload workflows. The staging
acquisition and cleanup half lives in ``tasks_staging``, the ArcGIS paged
fetch in ``tasks_arcgis`` and the quicklook draw in ``tasks_quicklook``.
"""

import asyncio
import functools
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from procrastinate import App

from app.platform.dataset_origin import (
    CONTACTED_ORIGIN_KINDS,
    KEEP,
    SourceBinding,
    restamp,
)
from app.core.service_tokens import reset_registered_credential_secrets
from app.core.url_redaction import redact_exception_text
from app.platform.jobs.queue_connector import make_queue_connector

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.processing.ingest.catalog_projection import Measurement
    from app.processing.ingest.warnings import IngestJobWarning
    from app.platform.jobs.models import IngestJob


def _current_tenant_schema() -> str:
    """Return the data schema for the current tenant (or 'data' in single_tenant).

    Raises RuntimeError in multi-tenant mode when no tenant context is bound.
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
    which is what QGIS/pgAdmin/DBeaver users see on a direct connection.
    Call it inside the publish transaction, which already holds the table's
    AccessExclusiveLock from the rename, so this cannot block. Failure is
    cosmetic and must never fail the ingest, so it is swallowed under a
    SAVEPOINT and logged.
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

    Raises RuntimeError in multi-tenant mode when no tenant context is bound.
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
) -> bool:
    """Dispatch a billable usage event to registered BillingExtensions.

    Imports only ``get_billing_extensions`` from ``app.platform.extensions``,
    so no billing symbol enters core; a no-op in OSS/single_tenant since
    ``DefaultBillingExtension`` has no ``on_usage_event``. A failing billing
    extension is logged and skipped: it must never fail an ingest task.
    ``tenant_id`` comes from the worker's ``current_tenant_var`` (set by
    middleware), never client input, which could be spoofed.

    Args:
        tenant_id: None (single_tenant, or context unset) returns immediately.
        dimension: e.g. ``'ingest_jobs'``, ``'raster_egress_bytes'``.
        value: event magnitude; use byte count for egress dimensions.
        event_id: dedup key — pass the Procrastinate job_id so retries stay
            idempotent at the DB layer.
        table_name: workers leave this None; the tile/OGC request path
            passes it to drive the last_accessed_at signal.

    Returns False when an extension raised, and True otherwise.
    """
    if not tenant_id:
        return True  # single_tenant no-op: no ledger, no billing (byte-identical OSS)

    from app.platform.extensions import get_billing_extensions

    _log = structlog.get_logger()
    emitted = True
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
            _log.warning(
                "billing_emit_error",
                dimension=dimension,
                tenant_id=tenant_id,
                ext=type(ext).__name__,
                exc_info=True,
            )
            emitted = False
    return emitted


@dataclass
class IngestContext:
    """Bundle of parameters shared across the post-ogr2ogr finalize pipeline.

    ``_finalize_ingest`` takes many inputs; collecting them in a dataclass
    keeps the call sites terse.
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
    # Typed origin_ref for the created dataset, minus `kind` (derived from
    # source_format). Keys are validated against the per-kind allowlist in
    # app/platform/dataset_origin.py, so nothing unexpected, a credential most
    # of all, reaches the column. Callers pass their own payload rather than
    # one being inferred here.
    origin_ref: dict[str, Any] | None = None
    # The origin pointer when it isn't ``source_url``: a database import has a
    # pointer but no URL.
    origin_uri: str | None = None
    # The local copy of the upload the task archives after the commit that
    # completes the job; that commit owes the archive in a follow-up record.
    archive_from: str | None = None
    source_columns: list[dict] | None = None


task_app = App(
    connector=make_queue_connector(),
    import_paths=[
        "app.processing.ingest.tasks_vector",
        "app.processing.ingest.tasks_raster",
        "app.processing.ingest.tasks_crs_facts",
        "app.processing.ingest.tasks_tileset",
        "app.processing.ingest.tasks_pointcloud",
        "app.processing.ingest.tasks_vrt",
        "app.processing.ingest.tasks_reupload",
        "app.processing.embeddings.tasks",
        "app.processing.analysis.tasks",
        # The embedding backfill, dataset retention and image sweeps.
        # They live under modules/admin/: processing/ may not import the
        # audit or catalog code they run. This list is how the worker finds them.
        "app.modules.admin.backfill_jobs",
        "app.modules.admin.retention_jobs",
        "app.modules.admin.story_asset_jobs",
    ],
)


# Without a credential store, service tasks are dispatched with the raw token
# in job kwargs; the worker only deletes successful rows, so a terminal failure
# leaves it in `procrastinate_jobs.args->>'token'` indefinitely.
#
# `url` is purged too. A submitted file URL can be a presigned S3 or SAS link,
# which is bearer-equivalent, and it sits in the row for the whole transfer
# plus forever after any non-successful delivery. The statement itself lives
# in platform/jobs/sweep.py.
async def purge_queued_job_arg(job_context: Any, *, arg_key: str = "token") -> None:
    """Best-effort: drop one credential-bearing key from this job's queue row.

    Takes the Procrastinate ``JobContext`` (not a bare id) so a direct call
    passing ``None`` is a no-op instead of an error.

    Never raises: a failure caller runs this while a real exception is being
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

    Applied under ``@tenant_task`` so the purge runs with the job's tenant
    context still bound. Absorbs the ``JobContext`` Procrastinate passes
    positionally, keeping the task's own keyword-only call shape unchanged;
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

    A `finally`-block cleanup step must never replace the exception the
    block is already propagating, and must not skip the steps after it, so
    wrap one step per `async with`: isolation is per block, not per
    `finally`.

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

    Mutates ``job.user_metadata`` in place, creating the list if absent; the
    caller commits. Build ``warning`` with the producer helpers in
    ``app.processing.ingest.warnings``, whose TypedDicts match the Pydantic
    ``JobStatusResponse``.
    """
    warnings_list = list((job.user_metadata or {}).get("warnings", []))
    warnings_list.append(warning)
    job.user_metadata = {
        **(job.user_metadata or {}),
        "warnings": warnings_list,
    }


def _append_mercator_clip_warning(job, clip: dict | None) -> None:
    """Warn when the Web Mercator clamp destroyed geometry.

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
    persist it to ``job.user_metadata.temporal_parse_errors`` for the UI.
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

    A re-apply reaches the reupload swap with the same list, and
    ``uq_record_keyword`` is a unique index, so an unconditional insert would
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
    # The keyword class off the relationship of the record class the port
    # already exposes: a new port accessor would be a required method that every
    # overlay would have to re-pin for, and processing/ cannot import this ORM.
    keywords_rel = sa_inspect(port.get_record_orm_class()).relationships["keywords"]
    RecordKeyword = keywords_rel.mapper.class_
    # The rows `uq_record_keyword` would actually collide with, spelled as that
    # index spells them (COALESCE, because a stored '' collides with the NULL
    # written below) and case-folded like `wanted`. A record-wide read would
    # skip a manifest tag that exists under another type.
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

    The read-back for ``manifest_job_metadata``'s ``metadata.attribution``,
    ``license``, ``organization`` and ``tags`` writes, called once per ingest
    tail after the record exists and before the phase transaction commits.
    Without it those fields would be accepted and then silently dropped, and
    every manifest under ``examples/manifests/`` sets them.

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


async def apply_manifest_publication(
    session: Any, dataset: Any, user_metadata: dict | None, *, actor_id: uuid.UUID
) -> None:
    """Bring an existing record to a manifest re-apply's title, summary and publication.

    The change goes through the metadata edit path, so a visibility or status
    change keeps its workflow, shared-map and publish checks, and a refusal
    fails the replacement. A field the manifest leaves blank keeps its value,
    and a job no manifest created changes nothing. The caller holds the
    catalog rows.
    """
    if not user_metadata or "manifest_key" not in user_metadata:
        return
    fields: dict[str, Any] = {
        key: value
        for key in ("title", "summary", "visibility", "record_status")
        if (value := _manifest_text(user_metadata, key)) is not None
    }
    if fields:
        from app.platform.extensions import get_processing_port

        # The record was read before the lock, and the edit path skips a field
        # that already looks equal, so an edit made since must be seen.
        await session.refresh(dataset.record, attribute_names=[*fields, "published_at"])
        await get_processing_port().update_dataset_metadata(
            session, dataset.id, fields, actor_id=actor_id
        )


@asynccontextmanager
async def _job_phase_session(
    job_uuid: uuid.UUID,
    *,
    phase: str,
    attempt_id: uuid.UUID | None = None,
    lock_and_statement_timeout_ms: int | None = None,
    require_status: str | None = None,
) -> "AsyncGenerator[tuple[AsyncSession, IngestJob | None], None]":
    """Two-phase session bracket for ingest workers.

    Yields ``(session, job)``; ``job`` is ``None`` if the IngestJob row
    vanished between phases (caller should early-return; this logs and
    continues rather than raising). ``phase`` labels that warning. Caller
    owns commits. Session lifetime is scoped to the ``async with`` block;
    CPU/subprocess work must happen outside it (the greenlet rule; see the
    ``ingest_file`` / ``ingest_raster`` docstrings).

    ``lock_and_statement_timeout_ms``, if given, issues ``SET LOCAL
    lock_timeout``/``statement_timeout`` before the SELECT.

    Pass ``require_status="running"`` at any phase that must not resume
    after a stale-job sweep has failed the row: a worker that was only
    paused (not dead) can still hold a matching ``attempt_id`` and
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
            # Held through this phase's own first irreversible write and up
            # to its next commit; see the docstring above.
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
    """Bind structlog contextvars for a worker task entry point.

    Procrastinate tasks run outside the request loop and so lack the
    ``request_id`` the HTTP middleware binds; ``job_id`` is the correlation
    key instead, letting operators filter concurrent ingests to one job's
    events. Clears stale vars first so a re-used worker can't leak a prior
    job's context.
    """

    structlog.contextvars.clear_contextvars()
    # The credential-secret registry
    # (`core/service_tokens.register_credential_secret`) is reset too, or a
    # prior job's registered secret lingers and mis-scrubs a later job's log
    # lines.
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
# ingest_file and reupload_file, so a reupload cannot skip the gate.
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
    otherwise 4326 (safe default for GeoJSON/CSV). Only for a caller that
    has already decided a geometry column will exist.
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
    renamed_columns: list[dict] | None = None,
) -> str | None:
    """Apply user x/y or WKT geometry overrides to a freshly-loaded table.

    Runs ``construct_point_geometry`` or ``construct_wkt_geometry`` when the
    user supplied ``x_column + y_column`` or ``geom_column`` in the commit
    metadata. Returns the geometry type string the caller should use in place
    of the ogrinfo-detected value, or ``None`` if neither override is set
    (callers guard on ``user_wants_geom``, so that branch is defensive only).

    ``renamed_columns`` is what ``rename_reserved_columns`` returned: a column
    the user picked may have moved to ``src_<name>`` since the preview, and the
    override must read it under its new name.

    Callers are responsible for importing the file as non-spatial (see the
    ``ogr_geometry_type = None if user_wants_geom else ...`` branch in
    ``ingest_file``) before invoking this helper.
    """
    from app.processing.ingest.metadata import _qtable

    moved = {r["original"]: r["renamed"] for r in renamed_columns or []}

    def _chosen(key: str) -> str | None:
        name = (user_metadata.get(key) or "").lower()
        return moved.get(name, name) or None

    x_column = _chosen("x_column")
    y_column = _chosen("y_column")
    geom_column = _chosen("geom_column")

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


async def load_job_for_error_write(
    session,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID | None,
    *,
    task_name: str,
):
    """Load the job row a failure tail is about to settle, under the shared budget.

    Never raises: every caller reaches it from inside an ``except``, where
    a raise would replace the ingest failure with a lock timeout.

    Returns ``None`` when the row is gone, a newer attempt owns it, or the
    budget expired (logged as its own event); on any ``None`` the
    transaction is ended so the caller's remaining writes run unbudgeted
    on a clean session. On a hit the transaction stays open and budgeted:
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
    atomically, owing the quicklook, the catalog cache purge, the embedding,
    the completion notice and the usage event in the job's follow-up record,
    which the caller runs once its own work after the commit is done.

    ``ctx`` is an ``IngestContext`` bundle — see its dataclass docstring
    for field descriptions. Returns the created Dataset ORM instance.
    """
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.metadata_attributes import apply_source_field_labels
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
        source_columns=ctx.source_columns,
    )
    _append_mercator_clip_warning(job, staging.mercator_clip)
    has_geometry = staging.has_geometry
    metadata = staging.metadata
    three_d = staging.three_d
    sample_values = staging.sample_values

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
    await apply_source_field_labels(session, dataset.id, user_metadata)
    # create_dataset defaults the record to 'published', so the before_insert
    # hook has already stamped published_at by the time this overwrite runs.
    # A non-published final status must not keep that timestamp; the real
    # transition path (_apply_record_status_change) stamps it when the dataset
    # is actually published later.
    final_status = user_metadata.get("record_status", "published")
    dataset.record.record_status = final_status
    if final_status != "published":
        dataset.record.published_at = None

    # The manifest's catalog metadata, which create_dataset has no argument
    # for, in the same transaction as the record it annotates.
    await apply_manifest_record_metadata(session, dataset.record, user_metadata)

    # System-managed origin pointer, in the same transaction that creates the
    # dataset. Service ingest supplies the enriched URL through ctx.source_url;
    # an uploaded file has no remote origin to point at, so its origin_uri
    # stays NULL and only the ref carries the filename.
    binding = SourceBinding.from_ref(
        ctx.source_format, ctx.origin_ref, uri=ctx.origin_uri or ctx.source_url
    )
    # A first service, STAC or database ingest read its data from the origin
    # moments ago, so the import is a contact, as in the reupload swap. Otherwise a
    # freshly imported service dataset would report last_checked_at NULL until
    # someone probed it. create_dataset dated freshness.
    restamp(
        dataset,
        binding,
        contacted_at=datetime.now(timezone.utc)
        if binding.kind in CONTACTED_ORIGIN_KINDS
        else None,
        refreshed_at=KEEP,
    )

    # Compute quality score (requires Dataset to exist for metadata checks)
    quality_score = await compute_quality_score(
        session,
        table_name,
        metadata.get("column_info", []),
        dataset,
        schema=_schema,
    )
    dataset.quality_detail = quality_score

    # Complete the job and commit dataset + job atomically. The attempt
    # predicate is the worker lease fence: if a stale worker resumes after a
    # retry rotated the token, this no-op raises and the surrounding phase
    # transaction rolls back the dataset it built. The terminal progress lets
    # the polling UI see current_step=complete and progress=1.0 at once.
    # ``rows_processed`` is the feature_count ``extract_metadata`` derived;
    # raster ingests, which do not call this helper, leave the column NULL.
    from app.platform.jobs import ledger
    from app.processing.ingest.publish_followups import owed_followups

    archive = {}
    if ctx.archive_from is not None:
        from app.processing.ingest.tasks_staging import original_archive_key

        # A fan-out layer shares its upload with its siblings, so it never
        # deletes it.
        archive = {
            "reaps_staged_upload": not user_metadata.get("fan_out_parent_id"),
            "archive_key": original_archive_key(dataset.id, ctx.archive_from),
            "sweep_waits": True,
        }
    completed = {
        "dataset_id": dataset.id,
        "current_step": "complete",
        "progress": 1.0,
        "rows_processed": metadata.get("feature_count"),
        "user_metadata": owed_followups(
            ctx.attempt_id or job.attempt_id,
            "ingest_file" if ctx.archive_from is not None else "ingest_service",
            **archive,
            catalog_cache=True,
            quicklook=table_name if has_geometry else None,
            embedding=True,
            notice="ingest_complete",
            usage="ingest_jobs",
        ),
    }
    await ledger.complete(
        session, job.id, ctx.attempt_id or job.attempt_id, values=completed
    )
    await session.commit()
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
    asyncpg exception. Both shapes are checked so behavior is identical
    wherever the exception bubbles up from.

    Gates the swap's single retry in ``install_candidate_table``. Returns
    False for any other exception class or SQLSTATE so real errors (e.g.
    23505 unique violation) still propagate immediately.
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
    reupload_service. If the initial import raises
    ``IngestionError`` and the layer name has a ``ns:name`` prefix,
    retries with the unqualified name; a ``WfsCountMismatchError`` is
    final and never retried. If ``auth_error_message`` is
    provided and the token is None and the error looks like an auth
    failure, re-raises with the custom message so users get a clear
    "you probably need a token" hint instead of the raw GDAL stderr.

    ``import_fn`` must be an async callable that accepts a single
    ``layer_name: str`` argument and does the actual ogr2ogr work.
    """
    from app.processing.ingest.ogr import IngestionError, WfsCountMismatchError

    try:
        await import_fn(source_layer)
    except WfsCountMismatchError:
        raise
    except IngestionError as exc:
        if ":" in source_layer:
            unqualified = source_layer.split(":", 1)[1]
            try:
                await import_fn(unqualified)
            except WfsCountMismatchError:
                raise
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


async def invalidate_tile_cache_for_table(table_name: str) -> bool:
    """Best-effort MVT tile-cache purge after a table's contents change.

    Tile keys carry the dataset's ``tile_cache_version``, so an API process
    stops reading pre-swap entries once it re-reads the dataset row. The purge
    makes the new rows visible sooner wherever it can reach the cache: a
    process still holding the old version re-renders from the swapped table.
    Call AFTER the owning transaction commits, so a concurrent tile request
    can't re-cache pre-swap rows. Returns whether the purge landed, or True
    with no tile cache; never raises.
    """
    from app.platform.cache.provider import get_tile_cache

    tile_cache = get_tile_cache()
    if tile_cache is None:
        return True
    return await tile_cache.invalidate_table(table_name)


# The AccessExclusiveLock budget the reupload swap DDL spends: first attempt,
# the single retry, and the pause between them.
_SWAP_FIRST_TIMEOUT = "5s"
_SWAP_RETRY_TIMEOUT = "15s"
_SWAP_RETRY_SLEEP_MS = 200


async def _install_reupload_table(
    session, *, dataset, staging_table: str, measurement: "Measurement"
) -> None:
    """Rename the staging table over the dataset's live table, in the caller's transaction.

    The replaced table is kept as one of the dataset's previous versions. The caller
    takes the catalog rows next, then calls :func:`_write_reupload_catalog`.
    """
    await install_candidate_table(
        session, dataset=dataset, candidate=staging_table, measurement=measurement
    )


async def install_candidate_table(
    session,
    *,
    dataset,
    candidate: str,
    measurement: "Measurement",
    restoring: int | None = None,
) -> None:
    """Make ``candidate`` the dataset's live table and keep the live one as a previous version.

    ``restoring`` is the kept version ``candidate`` holds when the swap
    publishes it again. Past ``PREVIOUS_VERSIONS_KEPT`` kept versions, the
    oldest are dropped. The renames run on their own lock budget in the
    caller's transaction, which keeps its ``lock_timeout`` afterwards.
    """
    from sqlalchemy import text

    from app.platform.jobs.heartbeat import previous_version_table
    from app.processing.ingest.metadata import _qtable
    from app.processing.ingest.previous_version import (
        kept_tables_to_drop,
        refuse_dependent_relations,
        require_free_previous_version_name,
        require_unclaimed_previous_version_name,
    )

    table_name = dataset.table_name
    keep = previous_version_table(table_name, dataset.id, dataset.current_version)

    # Tenant schema for this ingest: same schema for every table renamed
    # (the RENAMEs must stay intra-schema so they are atomic DDL).
    _tenant_schema = _current_tenant_schema()

    def _q(name: str) -> str:
        return _qtable(name, schema=_tenant_schema)

    if restoring is not None:
        await require_unclaimed_previous_version_name(session, dataset, candidate)

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
    live_partitioned = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :tn AND c.relkind = 'p')"
        ),
        {"schema": _tenant_schema, "tn": table_name},
    )
    # A partitioned table's partitions would keep their own names under the
    # renamed parent, where discovery lists them and registration accepts
    # them, so a replacement drops it rather than keeping it.
    keeps_live = live_exists and not (live_partitioned and restoring is None)
    if keeps_live:
        await require_free_previous_version_name(
            session, dataset, keep, schema=_tenant_schema
        )

    dropped = await kept_tables_to_drop(
        session, dataset, keeping=keeps_live, restoring=restoring
    )
    locked = (table_name, *([candidate] if restoring is not None else []), *dropped)

    # The swap DDL runs in SAVEPOINTs with a single retry on lock_timeout.
    # Autovacuum can hold AccessExclusiveLock long enough to collide with the
    # 5s default; 15s on retry plus a 200ms sleep gives it a chance to clear
    # without surfacing the failure to the user. Beyond the single retry the
    # error surfaces so ops can investigate.

    async def _swap_with_timeout(timeout_str: str) -> None:
        """Run SET LOCAL lock_timeout and the swap's DDL.

        The ``SET LOCAL`` outlives a released savepoint, so the caller restores
        the previous value once the swap is done. Each table's primary key is
        renamed as the table is, since the next rename needs the name it held.
        """
        await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_str}'"))
        await refuse_dependent_relations(session, locked, schema=_tenant_schema)
        for table in dropped:
            await session.execute(text(f"DROP TABLE IF EXISTS {_q(table)}"))
        if keeps_live:
            await session.execute(
                text(f'ALTER TABLE {_q(table_name)} RENAME TO "{keep}"')
            )
            await rename_pkey_to_match_table(session, keep)
        elif live_exists:
            await session.execute(text(f"DROP TABLE {_q(table_name)}"))
        await session.execute(
            text(f'ALTER TABLE {_q(candidate)} RENAME TO "{table_name}"')
        )
        await rename_pkey_to_match_table(session, table_name)

    # A `SET LOCAL` survives RELEASE SAVEPOINT, so the DDL budget below
    # outlives its savepoint and would clamp every later wait in this
    # transaction. What is in effect now is put back after the swap.
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

    # The DDL budget ends here. `set_config(..., true)` is `SET LOCAL` taking a
    # bind parameter.
    await session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": pre_swap_lock_timeout},
    )

    # Belt-and-braces after the swap: the staging pipeline is responsible for
    # the GIST index, but a re-ingest of a table that already lost its index
    # must self-heal here rather than serve full-scan tiles.
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
    origin_uri: str | None = None,
    field_labels: dict | None,
    job_id: uuid.UUID | None = None,
) -> tuple[Any, dict]:
    """Write what the installed table holds onto the catalog rows the caller holds.

    ``measurement`` is ``catalog_projection.measure`` of the staging table,
    taken in this transaction.

    ``origin_ref`` carries the typed per-origin payload for the bytes this
    swap installs, minus the ``kind`` discriminator (derived from
    ``source_format``), and ``origin_uri`` the pointer when it isn't
    ``source_url``. Same contract as ``IngestContext.origin_ref``: keys go
    through the per-kind allowlist, and callers supply their own rather than
    one being inferred here.

    ``job_id`` names the job that records ``origin_link_loss`` when the swap
    moves a service dataset to a host its portal link no longer matches.

    Returns the ``DatasetVersion`` this swap produced, flushed so the run row
    can link to its id, and the schema diff the projection computed under the
    lock, which is the diff the run stores. The tile-cache bump is the
    caller's.
    """
    from app.modules.audit.service import (
        AuditEvent,
        audit_emit,
    )
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.catalog_projection import project
    from app.processing.ingest.previous_version import (
        record_live_version,
        stamp_kept_versions,
    )

    DatasetVersion = get_processing_port().get_dataset_version_orm_class()
    actor_id = uuid.UUID(user_id)
    new_version = dataset.current_version + 1

    await record_live_version(session, dataset)
    schema_diff = await project(
        session, dataset, measurement, field_labels=field_labels
    )
    await stamp_kept_versions(session, dataset, dataset.current_version)

    dataset.source_filename = source_filename
    dataset.original_srid = original_srid
    dataset.current_version = new_version
    dataset.record.updated_by = actor_id
    if source_url is not None:
        dataset.source_url = source_url

    # Restamp the binding to describe where the current bytes came from.
    # Otherwise a file reupload of a registered-postgis or service dataset
    # leaves the old pointer in place (computed origin `upload` beside a
    # stored ref still claiming `postgis`), and a later refresh follows the
    # stale pointer. Kind is derived from the new source_format, as on first
    # ingest, so a service reupload stays a service origin and a file
    # reupload clears `origin_uri`.
    binding = SourceBinding.from_ref(
        source_format, origin_ref, uri=origin_uri or source_url
    )
    # The swap commit time, which is what migration 0036's backfill reads off
    # max(dataset_versions.uploaded_at) for a pre-existing dataset. A Python
    # datetime rather than func.now(): a SQL expression leaves the attribute
    # expired after flush, and the next read of dataset.last_refreshed_at then
    # lazy-loads against a session that may already be closed.
    swap_time = datetime.now(timezone.utc)
    # For a service, STAC or database origin this swap is a contact: the bytes
    # were read from that origin moments ago. Leaving last_checked_at NULL
    # would make the API claim the origin was never contacted, and a NULL
    # source_health would read as "unknown". A file upload or registered
    # table stamps nothing.
    contacted = binding.kind in CONTACTED_ORIGIN_KINDS
    link_losses = restamp(
        dataset,
        binding,
        contacted_at=swap_time if contacted else None,
        refreshed_at=swap_time,
        health=("healthy", None) if contacted else None,
    )
    if link_losses and job_id is not None:
        from app.platform.jobs.models import IngestJob

        job = await session.get(IngestJob, job_id)
        if job is not None:
            job.user_metadata = {
                **(job.user_metadata or {}),
                "origin_link_loss": link_losses,
            }

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=new_version,
        source_filename=source_filename,
        source_format=source_format,
        feature_count=measurement.metadata.get("feature_count"),
        srid=measurement.metadata.get("srid"),
        # The effective type, so the version history and the dataset row it
        # describes never disagree about what this swap installed.
        geometry_type=measurement.geometry_type,
        file_hash=file_hash,
        original_srid=original_srid,
        column_info=dataset.column_info,
        is_3d=measurement.three_d.get("is_3d"),
        n_dims=measurement.three_d.get("n_dims"),
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
                "source_type": "service_url"
                if source_url
                else ("database" if binding.kind == "database" else "file"),
                "source_format": source_format,
                "source_filename": source_filename,
            },
        ),
    )
    return version, schema_diff
