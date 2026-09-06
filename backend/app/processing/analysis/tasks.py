"""Materialize a PostGIS analysis result into a new dataset.

The worker builds the output table with server-rendered SQL (shared
expression templates in ``app.platform.analysis_sql``), normalizes it to the
geom/geom_4326 convention, and registers it through the standard ingest
registration path (``register_existing_table``) so metadata extraction,
reader grants, and the atomic dataset-slot quota all apply.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Literal

import structlog
from prometheus_client import Counter
from sqlalchemy import select, text
from sqlalchemy.exc import (
    DataError,
    InternalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.analysis_sql import (
    INTERNAL_ALIAS_PREFIX,
    INTERSECT_OUTPUT_COLUMNS,
    MAX_MASK_LAYER_FEATURES,
    MAX_SOURCE_FEATURES,
    MEASURE_OUTPUT_COLUMNS,
    NON_GROUPABLE_COLUMN_TYPES,
    NOT_EMPTY_PREDICATE,
    render_clip_layer_join,
    render_geometry_expr,
    render_intersect_pairs,
    render_measure_columns,
    render_select_by_location_where,
    render_spatial_join,
    spatial_join_output_columns,
)
from app.processing.analysis.provenance import apply_analysis_provenance
from app.platform.jobs.heartbeat import (
    claim_ingest_job_attempt,
    maintain_ingest_job_heartbeat,
    resolve_ingest_job_attempt,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.processing.ingest.metadata import _sql_quote_ident
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE = re.compile(r"^[a-z0-9_]+$")
# Mirrors _POLYGONAL_TYPES in router_analysis: a mask layer must be polygonal.
_POLYGONAL = {"POLYGON", "MULTIPOLYGON"}
# The operations whose second input can be a DRAWN polygon rather than a layer,
# mirroring MASK_OPERATIONS in catalog/datasets/domain/schemas.py: processing/
# must not import app.modules.catalog (PROCESS-02). intersect takes a layer only.
_DRAWN_MASK_OPERATIONS = ("clip", "select_by_location")


# fix(#1013): the CTAS is the only unbounded statement a user can queue, and
# its budget is an operator setting. Read through a function rather than bound
# at import, so no module-level snapshot can freeze the first value seen.
def materialize_timeout() -> str:
    """The CTAS statement_timeout, as a PostgreSQL interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_materialize_timeout_seconds}s"


# fix(#692): the mid-task commit ends the transaction carrying the CTAS budget,
# so registration's full-scan metadata extraction would otherwise run with no
# statement budget at all. Larger by default, but never unbounded.
def registration_timeout() -> str:
    """The post-commit registration statement_timeout, as an interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_registration_timeout_seconds}s"


# fix(#1012): per-statement work_mem for the materialize CTAS, an operator
# setting because the database's memory ceiling and the worker replica count are
# both invisible here. 0 skips the SET LOCAL; config.py carries the arithmetic.


async def _apply_materialize_work_mem(session: AsyncSession) -> None:
    """Raise work_mem for the CTAS transaction, unless the operator opted out.

    SET LOCAL, so it reverts with the transaction and every other connection
    keeps the cluster default.
    """
    work_mem = _materialize_work_mem()
    if work_mem is None:
        return
    # Cap parallelism first: work_mem is granted to the leader AND to every
    # parallel worker, so config.py's budget holds only at one worker. LEAST,
    # never a plain assignment: an operator who set 0 disabled parallel query.
    await session.execute(
        text(
            "SELECT set_config('max_parallel_workers_per_gather', "
            "LEAST(current_setting('max_parallel_workers_per_gather')::int, 1)"
            "::text, true)"
        )
    )
    await session.execute(text(f"SET LOCAL work_mem = '{work_mem}'"))


def _materialize_work_mem() -> str | None:
    """Per-slot work_mem for the CTAS, or None to leave the cluster's alone."""
    from app.core.config import settings

    budget_kb = settings.analysis_materialize_work_mem_mb * 1024
    if budget_kb <= 0:
        return None
    # A share below PostgreSQL's 64kB minimum cannot happen: config.py's
    # validate_materialize_work_mem_budget refuses to boot on it.
    per_slot_kb = budget_kb // max(1, settings.worker_concurrency)
    if per_slot_kb % 1024 == 0:
        return f"{per_slot_kb // 1024}MB"
    return f"{per_slot_kb}kB"


# fix(#694): post-CTAS backstop on the built output's on-disk size. The enqueue
# gates read a cached feature_count snapshot that can be stale; this cannot be.
# Buffer motivates it: the one amplifying operation, and vectors have no quota.
MAX_OUTPUT_BYTES = 2 * 1024**3

# Served by the worker's :8001 /metrics endpoint (default registry).
# Analysis-only; generalize when another ingest job type needs it.
ANALYSIS_JOBS = Counter(
    "geolens_analysis_jobs_total",
    "Materialize-analysis job outcomes",
    ["operation", "status"],
)


def _user_error_message(exc: Exception, *, registered: bool = False) -> str:
    """Map a failure onto text safe to return from ``GET /jobs/{job_id}``.

    SQLAlchemy stringifies DB errors with the full statement appended
    (``[SQL: CREATE TABLE "data"."…" AS …]``), which would hand internal schema
    and table names to the client. Mirrors the sandbox's
    ``_handle_execution_error`` categories; raw text stays in server logs.
    """
    if isinstance(exc, SQLAlchemyError):
        exc_text = str(exc).lower()
        if "querycancelederror" in exc_text or "statement timeout" in exc_text:
            # fix(#813, #1013 review): name the budget that actually fired.
            # The CTAS transaction carries the materialize one; the commit that
            # ends it re-arms registration with its own, and both are settings.
            budget = registration_timeout() if registered else materialize_timeout()
            return (
                f"The analysis exceeded its {budget} processing "
                "time limit. Try a smaller dataset or area."
            )
        if isinstance(exc, (DataError, InternalError)):
            return "The analysis failed while processing this data"
        # fix(#766): only the SQLSTATEs meaning "this column/type combination
        # can't do this operation" -- 42883, 42803, 42804. Not the whole class
        # 42: 42501, 42P01 and 42601 are server or configuration faults.
        if isinstance(exc, ProgrammingError) and str(
            getattr(exc.orig, "sqlstate", "") or ""
        ) in ("42883", "42803", "42804"):
            return (
                "A column in this dataset can't be used for this "
                "operation. Try a different column."
            )
        return "The analysis failed due to a database error"
    return str(exc)[:2000]


async def _fail_cancelled_job(
    working_session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    schema: str,
    out_table: str | None,
    operation: str,
) -> None:
    """Bookkeeping for a materialize cancelled mid-run, on a fresh session.

    Fenced on the attempt token FIRST: a successful fence proves the row was
    still 'running', so the registration commit has not happened and any
    committed output table is an unregistered orphan — safe to drop. If the
    fence misses, the job already reached a terminal state, and the table is
    dropped only when the adoption probe proves no dataset registered it.
    """
    from app.core.db import async_session

    # fix(#700 review): release `working_session`'s job-row lock first, time-
    # bounded so a wedged connection cannot eat the shield window, or the fenced
    # update below waits on our own lock and the row strands in 'running'.
    try:
        await asyncio.wait_for(working_session.rollback(), timeout=5)
    except Exception:  # broad: cleanup must reach the fenced update regardless
        logger.warning("analysis.cancel_rollback_failed", job_id=job_id)

    async with async_session() as session:
        if not await update_ingest_job_for_attempt(
            session,
            uuid.UUID(job_id),
            attempt_id,
            values={
                "status": "failed",
                "error_message": (
                    "The worker shut down before this analysis finished. Run it again."
                ),
                # fix(#813): terminal writes stamp completed_at — without it
                # the jobs UI renders '-' and retention ages on queue time.
                "completed_at": datetime.now(timezone.utc),
            },
        ):
            await session.rollback()
            # fix(#814): a swept row leaves an unregistered orphan. Probe for
            # an adopting dataset row; no row means the DROP is safe, and a
            # probe that errors leaks the table rather than dropping storage.
            await drop_unadopted_analysis_output(
                session,
                out_table=out_table,
                schema=schema,
                job_id=job_id,
                owner_job_uuid=uuid.UUID(job_id),
            )
            return
        await session.commit()
        if out_table is not None:
            try:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
                )
                await session.commit()
            except Exception:  # broad: best-effort cleanup of the partial table
                await session.rollback()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


async def _count_features_bounded(
    session: AsyncSession, table_ref: str, cap: int
) -> int:
    """Live row count, stopping at ``cap + 1`` so the probe stays bounded."""
    result = await session.execute(
        text(
            f"SELECT count(*) FROM (SELECT 1 FROM {table_ref} LIMIT :lim) AS _n"  # noqa: S608
        ).bindparams(lim=cap + 1)
    )
    return int(result.scalar_one())


def _generated_columns(
    operation: str, join_fields: list[str] | None
) -> tuple[str, ...]:
    """Columns an operation adds to the output beside the carried source ones."""
    if operation == "measure":
        return MEASURE_OUTPUT_COLUMNS
    if operation == "spatial_join":
        return tuple(spatial_join_output_columns(join_fields))
    if operation == "intersect":
        return INTERSECT_OUTPUT_COLUMNS
    return ()


def _reject_output_column_collision(
    carry_cols: list[str], generated: tuple[str, ...]
) -> None:
    """Worker-side half of the router's enqueue guard.

    The router validates against ``column_info``, a catalog snapshot, and the
    queue wait sits between that and the live column list held here — so the
    check runs again against the real columns. Without it the CTAS fails on an
    opaque "column specified more than once" after the whole wait.
    """
    clashes = sorted(set(carry_cols) & set(generated))
    if clashes:
        raise ValueError(
            "The source dataset already has a column named "
            f"{clashes[0]!r}, which this operation would overwrite. "
            "Rename it, or choose a different operation."
        )


async def _resolve_and_validate_columns(
    session: AsyncSession,
    *,
    schema: str,
    operation: str,
    src_table_name: str,
    mask_table_name: str | None,
    join_table_name: str | None,
    join_fields: list[str] | None,
) -> tuple[list[str], list[str]]:
    """The live-schema rechecks, run together after the queue wait.

    Every guard in here has an enqueue-time twin in the router that reads
    ``column_info``, a catalog SNAPSHOT. The queue wait sits between the two and
    a re-upload can replace either layer in that window, so each one runs again
    against the real columns. Returns the carried column lists the CTAS is
    built from, because resolving them is how most of these are checked.
    """
    carry_cols = (
        await _list_carry_columns(session, schema, src_table_name)
        if operation != "dissolve"
        else []
    )
    _reject_output_column_collision(
        carry_cols, _generated_columns(operation, join_fields)
    )
    if operation == "intersect":
        _reject_reserved_alias_columns(carry_cols)
    if operation == "spatial_join" and join_table_name is not None:
        await _reject_missing_join_fields(session, schema, join_table_name, join_fields)
    # fix(#956): an overlay carries columns from BOTH inputs, so it is the
    # only operation that also needs the second layer's live column list.
    mask_carry_cols: list[str] = []
    if operation == "intersect" and mask_table_name is not None:
        mask_carry_cols = await _list_carry_columns(session, schema, mask_table_name)
        _reject_output_column_collision(
            carry_cols, (*mask_carry_cols, *INTERSECT_OUTPUT_COLUMNS)
        )
        _reject_output_column_collision(mask_carry_cols, INTERSECT_OUTPUT_COLUMNS)
        _reject_reserved_alias_columns(mask_carry_cols)
    return carry_cols, mask_carry_cols


def _reject_reserved_alias_columns(carry_cols: list[str]) -> None:
    """Worker-side half of the reserved-alias guard.

    The router checked a catalog snapshot; a re-upload can introduce a column
    in the alias namespace before the job runs.
    """
    reserved = sorted(c for c in carry_cols if c.startswith(INTERNAL_ALIAS_PREFIX))
    if reserved:
        raise ValueError(
            f"Column {reserved[0]!r} uses the {INTERNAL_ALIAS_PREFIX!r} prefix, "
            "which this operation reserves for its own internal columns. "
            "Rename it, or choose a different layer."
        )


async def _reject_missing_join_fields(
    session: AsyncSession, schema: str, table_name: str, join_fields: list[str] | None
) -> None:
    """The transferred fields must still exist on the join layer.

    The router validated them against ``column_info`` at enqueue. A re-upload
    that drops or renames a requested field would otherwise leave
    ``render_spatial_join`` referencing a column that is no longer there, so
    the CTAS fails after the whole queue wait, naming a column the user
    legitimately selected when they asked.
    """
    if not join_fields:
        return
    live = set(
        (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table_name"
                ).bindparams(schema=schema, table_name=table_name)
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(set(join_fields) - live)
    if missing:
        raise ValueError(
            f"The join layer no longer has a column named {missing[0]!r}. It "
            "may have been re-uploaded since this analysis was queued. Choose "
            "the fields again."
        )


def _ungroupable_type_name(data_type: str | None, udt_name: str | None) -> str | None:
    """The display name of a non-groupable column type, or None if groupable.

    information_schema reports EVERY array column's data_type as 'ARRAY'; the
    element type only surfaces in udt_name, with a leading underscore ('_json'
    for json[]). Elements, not arrays: int[]/text[] have equality and group
    fine, so rejecting 'ARRAY' wholesale would refuse layers that work.
    """
    dt = str(data_type or "").lower()
    if dt in NON_GROUPABLE_COLUMN_TYPES:
        return dt
    udt = str(udt_name or "").lower()
    if udt.startswith("_") and udt[1:] in NON_GROUPABLE_COLUMN_TYPES:
        return f"{udt[1:]}[]"
    return None


async def _reject_ungroupable_by_field(
    session: AsyncSession, schema: str, table_name: str, by_field: str
) -> None:
    """Dissolve's GROUP BY column must be groupable on the LIVE schema.

    The router checked ``by_field`` against the catalog snapshot, which cannot
    see a json[] element type. One query answers both failure modes: a column
    the re-upload dropped, and one whose live type has no equality operator.
    Dissolve is the only caller — intersect joins its overlay attributes back
    outside the aggregate.
    """
    row = (
        await session.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table_name "
                "AND column_name = :column_name"
            ).bindparams(schema=schema, table_name=table_name, column_name=by_field)
        )
    ).first()
    if row is None:
        raise ValueError(
            f"Column {by_field!r} no longer exists on the source layer. It "
            "may have been re-uploaded since this analysis was queued."
        )
    bad = _ungroupable_type_name(row[0], row[1])
    if bad is not None:
        raise ValueError(
            f"Column {by_field!r} has type {bad!r} and can't be used to "
            "group features. Choose a column with comparable values."
        )


async def _resolve_layer_table_ref(
    session: AsyncSession,
    dataset_cls: Any,
    dataset_id: str,
    schema: str,
    *,
    label: str,
    require_geometry: str | None = None,
) -> tuple[str, str]:
    """Re-resolve a secondary layer at run time: ``(table_ref, table_name)``.

    Both two-layer operations need this — clip against a mask layer, and
    spatial_join against a join layer — with the same trust model: access was
    checked at enqueue by the router, and the table name is re-matched against
    ``_SAFE_TABLE`` here because the queue wait sits between the two. The bare
    name is returned beside the quoted ref for the ``information_schema``
    lookups, which take a plain name.

    ``dataset_cls`` is passed in rather than imported: ``processing/`` must not
    import from ``app.modules.catalog.*`` (PROCESS-02), so the caller hands
    over what it got from ``ProcessingPort.get_dataset_orm_class()``.
    """
    result = await session.execute(
        select(dataset_cls).where(dataset_cls.id == uuid.UUID(dataset_id))
    )
    layer = result.scalar_one_or_none()
    if layer is None or not layer.table_name:
        raise ValueError(f"{label.capitalize()} dataset not found")
    if not _SAFE_TABLE.match(layer.table_name):
        raise ValueError(f"Invalid {label} table name")
    # fix(#1097 review): re-applied here, not just at enqueue, because a
    # re-upload changes `Dataset.geometry_type` while the job waits. Polygonal
    # for the mask; "any" for the join layer, where only absence is fatal.
    geometry_type = (layer.geometry_type or "").upper()
    if require_geometry == "polygonal" and geometry_type not in _POLYGONAL:
        raise ValueError(
            f"The {label} layer is no longer a polygon layer. It may have been "
            "re-uploaded since this analysis was queued."
        )
    if require_geometry == "any" and not geometry_type:
        raise ValueError(
            f"The {label} layer no longer has geometry. It may have been "
            "re-uploaded since this analysis was queued."
        )
    return f'"{schema}"."{layer.table_name}"', layer.table_name


async def _recheck_size_caps(
    session: AsyncSession,
    *,
    operation: str,
    src_ref: str,
    mask_table_ref: str | None,
) -> None:
    """Re-validate the enqueue-time size gates against the live tables.

    The queue wait can be long enough for a source or mask dataset to be
    re-uploaded past its cap, and the post-CTAS output check is too late to
    protect the dissolve/mask union itself from OOM — so the bounded counts run
    again here, immediately before the SQL is built.
    """
    cap = MAX_SOURCE_FEATURES.get(operation)
    if cap is not None and await _count_features_bounded(session, src_ref, cap) > cap:
        raise ValueError(
            f"This dataset is too large for {operation} (the limit is "
            f"{cap:,} features). Filter it to a smaller dataset first."
        )
    if (
        mask_table_ref is not None
        and await _count_features_bounded(
            session, mask_table_ref, MAX_MASK_LAYER_FEATURES
        )
        > MAX_MASK_LAYER_FEATURES
    ):
        raise ValueError(
            "The mask layer has too many features to clip with (limit "
            f"{MAX_MASK_LAYER_FEATURES:,}). Choose a smaller mask layer or "
            "draw the mask on the map."
        )


async def _enforce_output_size(
    session: AsyncSession, schema: str, table_name: str, *, operation: str
) -> None:
    """Fail the build when the output relation is over MAX_OUTPUT_BYTES.

    ``pg_total_relation_size`` counts heap, TOAST, and indexes, so the
    post-rewrite call measures what the registered dataset will actually
    occupy. Resolved via pg_class with the ``:schema`` bind rather than a
    ``regclass`` cast: the tenant statement hook only recognizes schema
    references in SQL text or schema-named binds, and it masks string literals,
    so a schema hidden inside a generic bind would skip the tenant role setup
    and fail the lookup in multi-tenant.
    """
    result = await session.execute(
        text(
            "SELECT pg_total_relation_size(c.oid) FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = :schema AND c.relname = :table_name"
        ).bindparams(schema=schema, table_name=table_name)
    )
    size_bytes = result.scalar_one_or_none()
    if size_bytes is not None and size_bytes > MAX_OUTPUT_BYTES:
        # fix(#813): only buffer has a distance to reduce, so the others get
        # advice they can act on.
        advice = (
            "Reduce the buffer distance or run it on a smaller dataset."
            if operation == "buffer"
            else "Run it on a smaller dataset or area."
        )
        raise ValueError(
            f"The analysis output exceeded the "
            f"{MAX_OUTPUT_BYTES // 1024**3} GB size limit. {advice}"
        )


async def _complete_job_for_attempt(
    session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    dataset_id: uuid.UUID,
    schema: str,
    out_table: str,
    operation: str,
) -> None:
    """Commit registration together with the fenced terminal 'complete' write.

    The terminal write is fenced on the attempt token, like the claim and
    ``_fail_cancelled_job``: a plain ``job.status = "complete"`` would overwrite
    a row the stale-job sweep already failed and hand the user a dataset for a
    job they were told failed. The fence shares the registration transaction,
    so a miss rolls the Dataset row back with it.
    """
    if await update_ingest_job_for_attempt(
        session,
        uuid.UUID(job_id),
        attempt_id,
        values={
            "status": "complete",
            "dataset_id": dataset_id,
            # fix(#813): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.commit()
        ANALYSIS_JOBS.labels(operation=operation, status="complete").inc()
        return
    await session.rollback()
    logger.warning("analysis.complete_write_superseded", job_id=job_id)
    # fix(#814): the output table is durable from the build commit and this
    # attempt's registration is rolled back, so gate the drop on the adoption
    # probe and prefer leaking over dropping live storage.
    adopted = True
    try:
        adopted = await _output_table_adopted(session, out_table)
    except Exception:  # broad: prefer leak over loss
        logger.warning("analysis.adoption_probe_failed", job_id=job_id)
        await session.rollback()
    if not adopted:
        try:
            await session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
            )
            await session.commit()
        except Exception:  # broad: best-effort cleanup of the orphaned output
            await session.rollback()


async def _output_table_adopted(session: AsyncSession, out_table: str) -> bool:
    """Whether a dataset row has adopted ``out_table``.

    Index-backed: ``catalog.datasets`` carries two partial unique indexes on
    ``table_name`` (global and per-tenant). Tenant-scoped in multi_tenant, the
    same way the ingest discover query is, because an unscoped probe could
    match another tenant's dataset of the same name and skip a legitimate drop.
    With no tenant context in multi_tenant it reports adopted, so the caller
    leaks a table rather than dropping one it cannot attribute.
    """
    tid = current_tenant_var.get() if is_multi_tenant() else None
    if is_multi_tenant():
        if tid is None:
            return True
        stmt = text(
            "SELECT 1 FROM catalog.datasets"
            " WHERE table_name = :out AND tenant_id = :tenant_id"
        ).bindparams(out=out_table, tenant_id=tid)
    else:
        stmt = text(
            "SELECT 1 FROM catalog.datasets WHERE table_name = :out"
        ).bindparams(out=out_table)
    return (await session.execute(stmt)).first() is not None


# fix(#1778): the `user_metadata` field an analysis job names its output table
# under, written in the SAME transaction that creates the table, so a row that
# has one has the other and no orphan is left with nothing able to name it.
ANALYSIS_OUTPUT_TABLE_FIELD = "analysis_out_table"


def recorded_analysis_output_tables(user_metadata: object) -> tuple[str, ...]:
    """Every output table name a job row records, in the order recorded.

    The field is a LIST that each attempt appends to. A plain string is read as
    a one-element list, and anything else yields nothing rather than raising,
    because this reads a schemaless JSONB blob.
    """
    if not isinstance(user_metadata, dict):
        return ()
    recorded = user_metadata.get(ANALYSIS_OUTPUT_TABLE_FIELD)
    if isinstance(recorded, str):
        return (recorded,) if recorded else ()
    if not isinstance(recorded, list):
        return ()
    return tuple(name for name in recorded if isinstance(name, str) and name)


def append_analysis_output_record(user_metadata: "dict | None", out_table: str) -> dict:
    """Add ``out_table`` to the record without dropping what is already there.

    ``/jobs/{id}/retry`` preserves ``user_metadata``, so overwriting the field
    would strand the previous attempt's table with nothing naming it. Every
    reaper iterates the whole list.
    """
    names = list(recorded_analysis_output_tables(user_metadata))
    if out_table not in names:
        names.append(out_table)
    return {**(user_metadata or {}), ANALYSIS_OUTPUT_TABLE_FIELD: names}


# fix(#1778 codex r10): the scope an analysis output table carries, 8 hex
# characters of the job and 8 of the attempt. A retry keeps `IngestJob.id` and
# changes only `attempt_id`, so the job half alone does not name one owner.
_ANALYSIS_SCOPE_CHARS = 8
_ANALYSIS_TABLE_MAX_CHARS = 63


def analysis_output_scope(job_uuid: uuid.UUID, attempt_uuid: uuid.UUID) -> str:
    """The suffix that says which attempt of which job owns a table."""
    return (
        f"_{job_uuid.hex[:_ANALYSIS_SCOPE_CHARS]}"
        f"{attempt_uuid.hex[:_ANALYSIS_SCOPE_CHARS]}"
    )


def analysis_output_table_name(
    base: str,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    collision_suffix: int | None = None,
) -> str:
    """The physical name ONE attempt of one job may write its output to.

    Scoped by job AND attempt: ``/jobs/{id}/retry`` keeps the id and mints a
    new attempt token, so without the attempt half a stale sweep holding
    attempt 1's name probes and drops while attempt 2 is creating that same
    name, and the ownership check passes because the name really is this job's.
    The record accumulates every attempt's name, so no attempt's table is
    stranded by that.

    ``collision_suffix`` names the ``_N`` tag ``resolve_analysis_output_table``
    walks, and it is applied HERE, on the original ``base``, which is trimmed
    to leave room for the scope AND the tag together and recomputed from
    ``base`` every call. Trimming an ALREADY-TRIMMED string a second time
    truncates the very characters that make one candidate differ from the next.
    """
    scope = analysis_output_scope(job_uuid, attempt_uuid)
    tag = f"_{collision_suffix}" if collision_suffix is not None else ""
    limit = _ANALYSIS_TABLE_MAX_CHARS - len(scope) - len(tag)
    return f"{base[:limit]}{tag}{scope}"


def analysis_output_table_belongs_to(out_table: str, job_uuid: uuid.UUID) -> bool:
    """Whether ``out_table`` carries ``job_uuid``'s scope.

    The ownership check every reaper makes before it drops anything. The name
    embeds its owner, so this needs no catalog read and no lock. The attempt
    half must be PRESENT but is not compared, because the reaper reads the name
    off the row that recorded it; what this refuses is a name belonging to a
    different job, or one with no scope at all.
    """
    return (
        re.search(
            rf"_{re.escape(job_uuid.hex[:_ANALYSIS_SCOPE_CHARS])}"
            rf"[0-9a-f]{{{_ANALYSIS_SCOPE_CHARS}}}$",
            out_table,
        )
        is not None
    )


# How many `_N` walks the scoped-name probe makes before giving up, and how
# much of the base it probes on. Same bound as `generate_table_name`'s own.
_MAX_SCOPED_COLLISION_SUFFIX = 20
_SCOPED_PROBE_CHARS = 20


async def resolve_analysis_output_table(
    session: AsyncSession,
    *,
    base: str,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    schema: str,
) -> str:
    """The scoped output name, collision-checked AS SCOPED.

    ``generate_table_name`` walks its ``_N`` suffixes against the UNSCOPED base
    while the relation on disk carries the scope, so its candidate set and the
    names that exist never intersect. The walk therefore happens here, on the
    name that will actually be created, and every candidate is derived from the
    SAME original ``base`` via ``collision_suffix``.

    One prefix probe answers every candidate, and it reads pg_class rather than
    information_schema for the reason ``generate_table_name`` gives: the
    standard filters information_schema to relations the current role has
    privileges on, and an orphan this role never granted itself is exactly the
    one this has to see.
    """
    probe_prefix = base[:_SCOPED_PROBE_CHARS]
    taken = {
        row[0]
        for row in (
            await session.execute(
                text(
                    "SELECT c.relname FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = :schema AND c.relname LIKE :pattern"
                ).bindparams(schema=schema, pattern=f"{probe_prefix}%")
            )
        ).all()
    }
    candidate = analysis_output_table_name(base, job_uuid, attempt_uuid)
    if candidate not in taken:
        return candidate
    for suffix in range(2, _MAX_SCOPED_COLLISION_SUFFIX + 1):
        candidate = analysis_output_table_name(
            base, job_uuid, attempt_uuid, collision_suffix=suffix
        )
        if candidate not in taken:
            return candidate
    raise ValueError(
        "Could not find a free analysis output table name for this attempt."
    )


# A generated analysis table name, as `generate_table_name` produces them. The
# name reaches the sweeps through a schemaless JSONB blob and is interpolated
# into DDL, so it is re-checked at every use rather than trusted once.
_ANALYSIS_TABLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


# fix(#1778 codex r6): which answers from `drop_unadopted_analysis_output` can
# never change. A caller may forget the table's name only on one of these,
# because that name is the last durable pointer to it; "failed" is retryable.
ANALYSIS_OUTPUT_FINAL_OUTCOMES = frozenset({"adopted", "dropped", "invalid", "skipped"})

AnalysisOutputOutcome = Literal["skipped", "invalid", "adopted", "dropped", "failed"]


async def drop_unadopted_analysis_output(
    session: AsyncSession,
    *,
    out_table: str | None,
    schema: str,
    job_id: str,
    owner_job_uuid: uuid.UUID,
) -> AnalysisOutputOutcome:
    """Drop an analysis output table no dataset row has adopted.

    ``owner_job_uuid`` is the job whose record is being reaped, and a name that
    is not that job's is refused. It is required, with no default, because the
    caller that most needs the check is a sweep acting on a name read off a row
    that may be older than the table now standing at it. The name is
    re-validated here too, because the sweeps read it out of ``user_metadata``,
    a JSONB blob with no schema, and it is interpolated into a DDL statement
    that takes no bind parameters.

    Returns which of ``skipped``/``invalid``/``adopted``/``dropped``/``failed``
    it established. The sweeps clear the recorded name on the strength of that,
    and the name is the last durable pointer to the table, so a probe that
    RAISES is "failed" and not "adopted": preferring a leak to destroying a
    live dataset's storage is the right call for whether to DROP, and the wrong
    one for whether the question is settled.
    """
    if out_table is None:
        return "skipped"
    if not _ANALYSIS_TABLE_NAME_RE.match(out_table):
        logger.warning("analysis.output_table_name_rejected", job_id=job_id)
        return "invalid"
    # fix(#1778 codex r7): a sweep reaping a job's record may only drop the
    # table THAT job named. "invalid" rather than "failed": a name that is not
    # this job's can never become this job's, so retrying would pin the row.
    if not analysis_output_table_belongs_to(out_table, owner_job_uuid):
        logger.warning("analysis.output_table_not_owned", job_id=job_id)
        return "invalid"
    try:
        adopted = await _output_table_adopted(session, out_table)
    except Exception:  # broad: prefer leak over loss
        logger.warning("analysis.adoption_probe_failed", job_id=job_id)
        await session.rollback()
        return "failed"
    if adopted:
        return "adopted"
    try:
        await session.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"'))
        await session.commit()
    except Exception:  # broad: best-effort cleanup of the orphan
        await session.rollback()
        return "failed"
    return "dropped"


async def _mark_job_failed(
    session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    exc: Exception,
    schema: str,
    out_table: str | None,
    operation: str,
    registered: bool = False,
) -> None:
    """Roll back, record the failure, and drop this job's own partial table.

    Fenced on the attempt token FIRST, mirroring ``_fail_cancelled_job``: a
    plain ORM write could overwrite a terminal state some other actor already
    set. A successful fence proves the row was still 'running', so the
    registration commit has not happened and any committed output table is an
    unregistered orphan — safe to drop. If the fence misses, the row is left
    alone and the table is dropped only when the adoption probe proves no
    dataset registered it.
    """
    await session.rollback()
    if not await update_ingest_job_for_attempt(
        session,
        uuid.UUID(job_id),
        attempt_id,
        values={
            "status": "failed",
            # Sanitized (fix(#692)): raw DB errors embed the generated SQL.
            "error_message": _user_error_message(exc, registered=registered),
            # fix(#813): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.rollback()
        logger.warning("analysis.failed_write_superseded", job_id=job_id)
        # fix(#813): a fence miss means another actor set a terminal state,
        # but only a completed job has adopted the table. Probe first; a probe
        # that errors leaks the table rather than dropping live storage.
        await drop_unadopted_analysis_output(
            session,
            out_table=out_table,
            schema=schema,
            job_id=job_id,
            owner_job_uuid=uuid.UUID(job_id),
        )
        return
    await session.commit()
    if out_table is not None:
        try:
            await session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
            )
            await session.commit()
        except Exception:  # broad: best-effort cleanup of the partial table
            await session.rollback()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


async def _list_carry_columns(
    session: AsyncSession, schema: str, table_name: str
) -> list[str]:
    """Attribute columns to carry into 1:1 op output (skip system/geom cols).

    Every name is carried — GDAL launders only case/`-`/`#`, so ingested
    tables legitimately hold columns like ``Área`` or ``2020_pop``. Rendering
    quotes via ``_sql_quote_ident``, whose colon escape also keeps
    Socrata-style ``:id`` columns from being parsed as bind parameters by
    ``text()``.
    """
    rows = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name "
            "AND column_name NOT IN ('gid', 'geom', 'geom_4326') "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, table_name=table_name)
    )
    return [row[0] for row in rows]


def _wrap_not_empty(select_sql: str) -> str:
    """Exclude NULL/EMPTY-geometry rows inside the CTAS itself.

    ``_enforce_output_size`` probes ``pg_total_relation_size`` right after the
    CTAS, and the post-CTAS DELETE cannot shrink what it measures — dead tuples
    keep their pages until a rewrite — so rows the cleanup removes would count
    toward the output ceiling. ``OFFSET 0`` fences subquery pull-up so the
    geometry expression (``ST_Buffer`` at worst) is evaluated once per row
    rather than re-evaluated inside the outer WHERE.
    """
    return (
        f"SELECT * FROM ({select_sql} OFFSET 0) AS _rows"
        f" WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
    )


def _build_materialize_select(
    src_ref: str,
    operation: str,
    *,
    distance_meters: float | None,
    mask: dict[str, Any] | None,
    by_field: str | None,
    carry_cols: list[str],
    mask_table_ref: str | None = None,
    join_table_ref: str | None = None,
    join_fields: list[str] | None = None,
    mask_carry_cols: list[str] | None = None,
) -> str:
    """Render the SELECT that produces the output table's rows."""
    if operation == "intersect" and mask_table_ref is not None:
        # fix(#956): the only branch whose output rows are not 1:1 with
        # source rows, so it generates its own gid — ADD PRIMARY KEY (gid)
        # below would die on duplicates. Empty geometries filtered in-renderer.
        return render_intersect_pairs(
            src_ref,
            mask_table_ref,
            src_columns=[_sql_quote_ident(c) for c in carry_cols],
            mask_columns=[_sql_quote_ident(c) for c in (mask_carry_cols or [])],
        )
    if operation == "measure":
        # fix(#954): the same renderer the preview uses, so a saved
        # measurement equals the one the user approved.
        measure_cols, measure_join = render_measure_columns(src="_src")
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return _wrap_not_empty(
            f"SELECT _src.gid, {cols}_src.geom_4326 AS geom,"
            f" {measure_cols}"
            f" FROM {src_ref} AS _src{measure_join}"
        )
    if operation == "spatial_join" and join_table_ref is not None:
        # fix(#953): the same two laterals the preview uses, so the saved
        # dataset and the approved preview agree row for row — including the
        # tie-break, without which the CTAS dies on ADD PRIMARY KEY below.
        join_cols, joins = render_spatial_join(
            join_table_ref, src="_src", join_fields=join_fields
        )
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return _wrap_not_empty(
            f"SELECT _src.gid, {cols}_src.geom_4326 AS geom,"
            f" {join_cols}"
            f" FROM {src_ref} AS _src{joins}"
        )
    if operation == "dissolve":
        # ST_MakeValid: one invalid ring would abort the whole union.
        # ST_CollectionExtract: a union over mixed geometry types returns a
        # GEOMETRYCOLLECTION, which the MVT tile path can't render.
        union_expr = "ST_Multi(ST_CollectionExtract(ST_Union(ST_MakeValid(geom_4326))))"
        if by_field:
            # fix(#836): quote via _sql_quote_ident like every other
            # identifier site here, leaving no inline-quoting divergence.
            col = _sql_quote_ident(by_field)
            return _wrap_not_empty(
                f"SELECT (row_number() OVER ())::integer AS gid, {col}, "
                f"COUNT(*)::integer AS source_count, "
                f"{union_expr} AS geom "
                f"FROM {src_ref} GROUP BY {col}"
            )
        return _wrap_not_empty(
            f"SELECT 1 AS gid, COUNT(*)::integer AS source_count, "
            f"{union_expr} AS geom FROM {src_ref}"
        )
    if operation == "select_by_location" and mask_table_ref is not None:
        # fix(#955): whole source rows, filtered. No lateral and no CTE, so
        # _wrap_not_empty applies to the source geometry directly, which is
        # what the output geometry IS. A DRAWN mask needs no branch here.
        where = render_select_by_location_where(mask_table_ref, src="_src")
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return _wrap_not_empty(
            f"SELECT _src.gid, {cols}_src.geom_4326 AS geom"
            f" FROM {src_ref} AS _src{where}"
        )
    if operation == "clip" and mask_table_ref is not None:
        # fix(#719): the same subdivided-mask join the preview uses. The
        # empty-result filter is applied HERE, before _enforce_output_size
        # measures a CTAS holding bounding-box overlaps that yield NULL.
        cte, lateral, where = render_clip_layer_join(mask_table_ref, src="_src")
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return (
            f"{cte} SELECT _src.gid, {cols}_op.geom_out AS geom"
            f" FROM {src_ref} AS _src"
            f" CROSS JOIN LATERAL {lateral} AS _op"
            f"{where} AND {NOT_EMPTY_PREDICATE}"
        )
    expr, where = render_geometry_expr(
        operation,
        distance_meters=distance_meters,
        mask=mask,
    )
    cols = "".join(f"{_sql_quote_ident(c)}, " for c in carry_cols)
    return _wrap_not_empty(f"SELECT gid, {cols}{expr} AS geom FROM {src_ref}{where}")


async def _materialize(
    *,
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
    join_dataset_id: str | None = None,
    join_fields: list[str] | None = None,
) -> None:
    """Core materialize logic; separated from the task wrapper for tests."""
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.metadata import add_4326_column
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import (
        generate_table_name,
        register_existing_table,
    )

    async with async_session() as session:
        job = await session.get(IngestJob, uuid.UUID(job_id))
        if job is None:
            logger.warning("analysis.job_not_found", job_id=job_id)
            return
        # fix(#692): fenced claim, pending → running at most once per attempt
        # token, stamping the liveness signals the sweep and the lease need.
        # Without it a row another actor already made terminal is resurrected.
        attempt_id = job.attempt_id or await resolve_ingest_job_attempt(job.id, None)
        if attempt_id is None or not await claim_ingest_job_attempt(
            session, job.id, attempt_id
        ):
            await session.rollback()
            logger.warning("analysis.attempt_not_claimed", job_id=job_id)
            return
        # current_step only, no numeric progress: one CTAS has no
        # intra-statement telemetry, and a parked bar reads as "stuck".
        job.current_step = "analyzing"
        await session.commit()

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
        # Only drop the output table on failure if THIS job created it: when
        # CREATE TABLE loses a race for the same generated name, an
        # unconditional cleanup would destroy the winner's table.
        out_table_created = False
        # fix(#1013 review): flipped once registration re-arms its own
        # statement_timeout, so a later failure quotes the budget that fired.
        registration_started = False
        # Created inside the try so the finally below always reaps it: a
        # heartbeat left running renews a lease for a job nobody is executing,
        # and the sweep can never fail a row with a fresh lease.
        heartbeat: asyncio.Task[None] | None = None
        try:
            # Renews on its own session, so it never contends with the work
            # below, and returns by itself once the row leaves 'running'.
            heartbeat = asyncio.create_task(
                maintain_ingest_job_heartbeat(job.id, attempt_id)
            )
            port = get_processing_port()
            Dataset = port.get_dataset_orm_class()
            result = await session.execute(
                select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
            )
            src = result.scalar_one_or_none()
            if src is None or not src.table_name:
                raise ValueError("Source dataset not found")
            if not _SAFE_TABLE.match(src.table_name):
                raise ValueError("Invalid source table name")
            if by_field is not None:
                if not _SAFE_IDENT.match(by_field):
                    raise ValueError("Invalid dissolve column name")
                await _reject_ungroupable_by_field(
                    session, _schema, src.table_name, by_field
                )
            src_ref = f'"{_schema}"."{src.table_name}"'

            # Layer-sourced clip mask: re-resolved at run time, same trust
            # model as the source dataset (access checked at enqueue).
            mask_table_ref: str | None = None
            mask_table_name: str | None = None
            if mask_dataset_id is not None:
                mask_table_ref, mask_table_name = await _resolve_layer_table_ref(
                    session,
                    Dataset,
                    mask_dataset_id,
                    _schema,
                    label="mask",
                    require_geometry="polygonal",
                )
            join_table_ref: str | None = None
            # fix(#1097 review): the plain name is kept for the live-column
            # recheck, which information_schema takes rather than a quoted ref.
            join_table_name: str | None = None
            if join_dataset_id is not None:
                join_table_ref, join_table_name = await _resolve_layer_table_ref(
                    session,
                    Dataset,
                    join_dataset_id,
                    _schema,
                    label="join",
                    require_geometry="any",
                )

            await _recheck_size_caps(
                session,
                operation=operation,
                src_ref=src_ref,
                mask_table_ref=mask_table_ref,
            )

            _base_table, collision_warning = await generate_table_name(title, session)
            # fix(#1778 codex r7/r10): scoped by this job AND this attempt.
            # `generate_table_name` chooses the readable half; the `_N` walk
            # that matters for the RELATION is the scoped one below.
            out_table = await resolve_analysis_output_table(
                session,
                base=_base_table,
                job_uuid=uuid.UUID(job_id),
                attempt_uuid=attempt_id,
                schema=_schema,
            )
            # fix(#1778 codex r10): the name, on the durable row, in the same
            # transaction that creates the table (the commit after ANALYZE), as
            # a LIST each attempt appends to — retry preserves `user_metadata`.
            job.user_metadata = append_analysis_output_record(
                job.user_metadata, out_table
            )
            if collision_warning:
                # fix(#786): persisted like the upload path — the job-status
                # endpoint surfaces user_metadata['collision_warning'] as
                # warning_message, so discarding it hides the renamed output.
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
            # INVARIANT: every statement from the assignments above to the
            # commit after ANALYZE stays text(). One ORM select() would autoflush
            # the dirty job row, taking its lock across the whole CTAS.
            out_ref = f'"{_schema}"."{out_table}"'

            carry_cols, mask_carry_cols = await _resolve_and_validate_columns(
                session,
                schema=_schema,
                operation=operation,
                src_table_name=src.table_name,
                mask_table_name=mask_table_name,
                join_table_name=join_table_name,
                join_fields=join_fields,
            )
            select_sql = _build_materialize_select(
                src_ref,
                operation,
                distance_meters=distance_meters,
                mask=mask,
                by_field=by_field,
                carry_cols=carry_cols,
                mask_table_ref=mask_table_ref,
                join_table_ref=join_table_ref,
                join_fields=join_fields,
                mask_carry_cols=mask_carry_cols,
            )
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{materialize_timeout()}'")
            )
            await _apply_materialize_work_mem(session)
            if operation == "dissolve":
                # fix(#694): hash aggregation holds every group's union state
                # in memory at once and can OOM-kill the shared db container;
                # sorted aggregation bounds it to one group at a time.
                await session.execute(text("SET LOCAL enable_hashagg = off"))
            await session.execute(text(f"CREATE TABLE {out_ref} AS {select_sql}"))
            out_table_created = True
            # Early exit only — a table already over the ceiling must not hold
            # the single worker slot through the rewrite phases. The
            # authoritative check runs after add_4326_column below.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # fix(#786): rows with nothing to show are excluded inside the
            # CTAS for every shape via _wrap_not_empty, matching the preview.
            # This DELETE is the backstop should a query shape miss that filter.
            await session.execute(
                text(f"DELETE FROM {out_ref} WHERE geom IS NULL OR ST_IsEmpty(geom)")
            )
            has_features = await session.scalar(
                text(f"SELECT EXISTS (SELECT 1 FROM {out_ref})")
            )
            if not has_features:
                # e.g. a clip matching nothing, or dissolving an empty dataset
                # (whose no-GROUP-BY aggregate yields one NULL-geometry row).
                raise ValueError("Analysis produced no features to save")
            # CTAS yields an untyped geometry column (typmod srid=0), which
            # metadata extraction reports as SRID 0 — stamp the 4326 typmod.
            await session.execute(
                text(
                    f"ALTER TABLE {out_ref} ALTER COLUMN geom "
                    f"TYPE geometry(Geometry, 4326) USING ST_SetSRID(geom, 4326)"
                )
            )
            await session.execute(text(f"ALTER TABLE {out_ref} ADD PRIMARY KEY (gid)"))
            await add_4326_column(session, out_table, 4326, schema=_schema)
            # fix(#701 review): the 4326 rewrite roughly doubles the geometry
            # payload and adds the GIST index, so the post-CTAS probe
            # undercounts the final footprint by a multiple.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # fix(#692): in-transaction ANALYZE. The table becomes visible to
            # autovacuum only at the commit below and the first tile queries
            # land before its pass, with no `&&` selectivity for the GIST index.
            await session.execute(text(f"ANALYZE {out_ref}"))
            job.current_step = "registering"
            await session.commit()
            registration_started = True

            # fix(#692): the commit above ends the SET LOCAL with its
            # transaction. Set here rather than inside register_existing_table,
            # which is shared with the upload path.
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{registration_timeout()}'")
            )
            # Identity is a structural Protocol; registration only reads .id.
            requester = SimpleNamespace(id=uuid.UUID(user_id))
            dataset = await register_existing_table(
                session,
                RegisterRequest(
                    table_name=out_table, title=title, visibility="private"
                ),
                requester,
                # fix(#1452): CTAS'd a few lines up, so it is GeoLens's to
                # drop when the dataset is deleted. Without it the detach that
                # protects an operator-registered table leaks one per delete.
                managed=True,
            )
            # feat(#765): provenance before the completing commit, so a
            # registered output can never be visible without its lineage.
            await apply_analysis_provenance(
                session,
                new_record_id=dataset.record_id,
                source_dataset_id=dataset_id,
                user_id=user_id,
                operation=operation,
                params={
                    "distance_meters": distance_meters,
                    "by_field": by_field,
                    # fix(#1097 review): every operation that can take a DRAWN
                    # mask, not clip alone. The drawn geometry is excluded from
                    # provenance, so this is the only trace an area shaped it.
                    "mask_source": (
                        ("layer" if mask_dataset_id else "drawn")
                        if operation in _DRAWN_MASK_OPERATIONS
                        else None
                    ),
                    "mask_dataset_id": mask_dataset_id,
                    "join_dataset_id": join_dataset_id,
                    "join_fields": join_fields or None,
                },
            )
            await _complete_job_for_attempt(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                dataset_id=dataset.id,
                schema=_schema,
                out_table=out_table,
                operation=operation,
            )
        except asyncio.CancelledError:
            # fix(#692): a graceful shutdown cancels this task and `except
            # Exception` cannot catch it, so without this branch the row strands
            # in 'running'. Shielded, so the cleanup is not cancelled too.
            try:
                await asyncio.shield(
                    asyncio.wait_for(
                        _fail_cancelled_job(
                            session,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            schema=_schema,
                            out_table=out_table if out_table_created else None,
                            operation=operation,
                        ),
                        timeout=15,
                    )
                )
            except BaseException:  # broad: best-effort cleanup during shutdown; the raise below preserves the abort
                logger.warning("analysis.cancel_cleanup_failed", job_id=job_id)
            raise
        except Exception as exc:  # broad: any failure must mark the job failed, not raise into the queue
            logger.warning(
                "analysis.materialize_failed",
                job_id=job_id,
                error=str(exc),
                exc_info=True,
            )
            await _mark_job_failed(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                exc=exc,
                schema=_schema,
                out_table=out_table if out_table_created else None,
                operation=operation,
                # True only once the CTAS transaction has committed, which is
                # exactly when the registration budget is the one in force.
                registered=registration_started,
            )
        finally:
            # Stop (cancel + await, the ingest convention) so the task neither
            # outlives the work by a heartbeat interval nor leaks a pending
            # task through worker shutdown.
            await stop_ingest_job_heartbeat(heartbeat)


@task_app.task(
    queue="ingest", retry=0, aliases=["app.analysis.tasks.materialize_analysis"]
)
@tenant_task
async def materialize_analysis(
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
    join_dataset_id: str | None = None,
    join_fields: list[str] | None = None,
) -> None:
    """Procrastinate entry point for async analysis materialization."""
    await _materialize(
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user_id,
        operation=operation,
        title=title,
        distance_meters=distance_meters,
        mask=mask,
        mask_dataset_id=mask_dataset_id,
        by_field=by_field,
        join_dataset_id=join_dataset_id,
        join_fields=join_fields,
    )
