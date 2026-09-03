"""Materialize a PostGIS analysis result into a new dataset (M4).

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
# Mirrors MASK_OPERATIONS in catalog/datasets/domain/schemas.py: the operations
# whose second input can be a DRAWN polygon rather than a layer. Duplicated
# rather than imported because processing/ must not import from
# app.modules.catalog (PROCESS-02), the same reason _POLYGONAL is duplicated.
# intersect is absent deliberately: it takes a layer only, so the discriminator
# would be a constant there.
_DRAWN_MASK_OPERATIONS = ("clip", "select_by_location")


# The preview path is bounded (10s sandbox timeout, 500-row cap); the CTAS
# here is the only unbounded statement a user can queue, so cap it.
#
# fix(#1013): the value is an operator setting now, not a hardcoded ceiling.
# Read through a function rather than bound at import: these render into SQL
# and into a user-facing message, and a module-level snapshot would freeze
# whatever the settings object held the first time this module was imported.
def materialize_timeout() -> str:
    """The CTAS statement_timeout, as a PostgreSQL interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_materialize_timeout_seconds}s"


# The mid-task commit that makes the output table durable also ends the
# transaction carrying the CTAS budget — registration then runs full-scan
# metadata extraction (COUNT + ST_Extent + the sample-values CTE) in a fresh
# transaction, which would otherwise have no statement budget at all
# (fix(#692)). Larger than the CTAS budget by default: those scans are cheap
# relative to the build, but must never be unbounded.
def registration_timeout() -> str:
    """The post-commit registration statement_timeout, as an interval literal."""
    from app.core.config import settings

    return f"{settings.analysis_registration_timeout_seconds}s"


# fix(#1012): per-statement work_mem for the materialize CTAS.
#
# The cluster-wide default is 8MB (db/postgresql.conf:93) — right for eighty
# concurrent connections doing ordinary catalog queries, far too small for one
# buffer or dissolve over hundreds of thousands of geometries, which spills to
# pgsql_tmp long before it needs to. Dissolve wants it most: #694 turned off
# hash aggregation there (it holds every group's union state in memory at once
# and could OOM the shared db container), and the sorted aggregation that
# replaces it is precisely what work_mem governs. Turning off hashagg without
# raising work_mem trades an OOM risk for a guaranteed spill.
#
# WHICH BUDGET THIS COMES OUT OF. work_mem is allocated by the PostgreSQL
# backend serving the session, so the memory lands in the `db` service, capped
# by DB_MEM_LIMIT. That budget also holds shared_buffers (512MB),
# maintenance_work_mem (128MB), and up to max_connections = 80 other backends
# each entitled to their own work_mem. The worker's own WORKER_MEM_LIMIT is not
# what constrains this; the Python side of materialize lives there, the sort
# does not.
#
# work_mem is per OPERATION and per BACKEND, so one plan can allocate several
# multiples of it: at most 2 memory-hungry nodes for these shapes (dissolve is
# one Sort feeding a GroupAggregate; buffer and centroid have none; clip has a
# join), times 2 backends. The second factor is guaranteed rather than assumed —
# the override pins max_parallel_workers_per_gather to 1 for this transaction,
# because db/postgresql.conf only governs the bundled database and says nothing
# about an external one.
#
# THE CEILING IS AN OPERATOR SETTING, not a constant, because the two things
# that decide what is safe are both invisible from here:
#
#   - DB_MEM_LIMIT is a compose `mem_limit` and is never passed into this
#     container's environment, so this process cannot read the database's
#     ceiling. It is also tunable (docker-compose.prod.yml documents 1.5g) and
#     an external PostgreSQL may be smaller again.
#   - The divisor below bounds concurrent materializes inside ONE worker
#     process. It cannot bound a deployment running several worker services
#     against the `ingest` queue; each replica would claim the budget
#     independently. Bounding that needs a deployment-wide admission mechanism,
#     which is #695's open question.
#
# So the setting defaults low enough to be safe under both unknowns rather than
# optimal under neither: 64MB is 256MB worst case per worker replica, so even
# two replicas sit inside the default 2 GB alongside shared_buffers and
# maintenance_work_mem. An operator with a bigger database container and one
# worker can raise it; one with a smaller container or more replicas must lower
# it. config.py carries the arithmetic.
#
# Measured on a 60k-polygon grouped dissolve with enable_hashagg = off, the
# leader's sort wanted 96MB: at the 8MB default it spilled 70MB to disk, and at
# 128MB it stayed in memory. 64MB does not eliminate that spill, it shrinks it —
# the conservative default trades some of the win for a ceiling that cannot OOM
# the database on a deployment this process cannot measure.
#
# There is deliberately NO floor at the bundled 8MB default: that would be an
# assumption about the connected cluster this process cannot check. An external
# PostgreSQL tuned below 8MB would be RAISED by a clamp advertised as leaving it
# alone, and an operator who wants less than 8MB per materialize could not have
# it. ANALYSIS_MATERIALIZE_WORK_MEM_MB=0 is the honest way to say "do not touch
# work_mem" — it skips the SET LOCAL entirely.
#
# The division is done in kB, not MB, so the budget is never exceeded by
# rounding: a 64MB budget across 128 slots is 512kB each, not 1MB each. A
# budget too small to divide into legal shares is rejected at boot rather than
# resolved at run time — see validate_materialize_work_mem_budget.


async def _apply_materialize_work_mem(session: AsyncSession) -> None:
    """Raise work_mem for the CTAS transaction, unless the operator opted out.

    SET LOCAL, so it applies to this statement and reverts with the
    transaction — the other seventy-nine connections keep the cluster default.
    A global bump would not be safe in the same way. Lives here rather than
    inline in _materialize so the opt-out branch does not push that function
    past its complexity cap.
    """
    work_mem = _materialize_work_mem()
    if work_mem is None:
        return
    # Cap parallelism first, so the budget arithmetic is true by construction
    # rather than by assuming the server's configuration. work_mem is granted to
    # the leader AND to every parallel worker, so a server with
    # max_parallel_workers_per_gather above 1 — a customised bundled conf, or
    # any external PostgreSQL reached through DATABASE_URL_OVERRIDE, neither of
    # which db/postgresql.conf:73 constrains — would multiply the ceiling by a
    # number this process cannot see. One leader plus one worker is what the
    # budget in config.py is sized for.
    #
    # LEAST, not a plain assignment: an operator who set 0 has DISABLED parallel
    # query, and raising them to 1 would hand this statement a worker and the
    # CPU and memory that comes with it. Only ever lower. set_config's third
    # argument is is_local, so this is transaction-scoped exactly like SET LOCAL
    # — which cannot take an expression.
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
    # validate_materialize_work_mem_budget refuses to boot on it, because
    # neither issuing the minimum (over budget) nor skipping the override
    # (cluster's larger value, further over budget) honours the ceiling.
    per_slot_kb = budget_kb // max(1, settings.worker_concurrency)
    if per_slot_kb % 1024 == 0:
        return f"{per_slot_kb // 1024}MB"
    return f"{per_slot_kb}kB"


# fix(#694): post-CTAS backstop on the built output's on-disk size. The
# enqueue gates read the cached feature_count snapshot, which can be stale;
# this is the enforcement that can't be. Buffer is the motivating case: it
# is the only amplifying operation and vector datasets carry no byte quota.
MAX_OUTPUT_BYTES = 2 * 1024**3

# Served by the worker's :8001 /metrics endpoint (default registry).
# Analysis-only counter; generalize to all ingest job types when
# another type needs it.
ANALYSIS_JOBS = Counter(
    "geolens_analysis_jobs_total",
    "Materialize-analysis job outcomes",
    ["operation", "status"],
)


def _user_error_message(exc: Exception, *, registered: bool = False) -> str:
    """Map a failure onto text safe to return from ``GET /jobs/{job_id}``.

    SQLAlchemy stringifies DB errors with the full statement appended
    (``[SQL: CREATE TABLE "data"."…" AS …]``), which would hand internal
    schema and table names to the client (fix(#692)). Mirrors the sandbox's
    ``_handle_execution_error`` categories; raw text stays in server logs.
    """
    if isinstance(exc, SQLAlchemyError):
        exc_text = str(exc).lower()
        if "querycancelederror" in exc_text or "statement timeout" in exc_text:
            # fix(v1.6.0 audit D11): name the configured limit so the user
            # knows what budget was exceeded. fix(#1013 review): WHICH limit
            # depends on the phase — the CTAS transaction carries the
            # materialize budget, and the commit that ends it re-arms
            # registration with its own (#692). Naming the wrong one was
            # harmless while both were hardcoded at 300s/600s and only the
            # first was ever quoted; now that an operator can set them
            # independently, a registration timeout quoting the materialize
            # budget sends them to tune the setting that did not fire.
            budget = registration_timeout() if registered else materialize_timeout()
            return (
                f"The analysis exceeded its {budget} processing "
                "time limit. Try a smaller dataset or area."
            )
        if isinstance(exc, (DataError, InternalError)):
            return "The analysis failed while processing this data"
        # fix(#766): only the SQLSTATEs that mean "this column/type
        # combination can't do this operation": 42883 undefined_function
        # (e.g. no equality operator for `json` in a dissolve GROUP BY),
        # 42803 grouping_error, 42804 datatype_mismatch. Deliberately NOT
        # the whole class 42 — 42501 (privilege), 42P01 (missing table),
        # and 42601 (syntax) are server or configuration faults and must
        # keep reporting as the generic database error.
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
    still 'running', so the final registration commit (which atomically
    persists the dataset and flips the row to 'complete') has not happened,
    and any committed output table is an unregistered orphan — safe to drop.
    If the fence misses, the job already reached a terminal state; the table
    is dropped only when the adoption probe proves no dataset registered it
    (fix(v1.6.0 audit B13)).
    """
    from app.core.db import async_session

    # fix(#700 review): the cancel can land while `working_session`'s open
    # transaction still holds the job-row lock (any flush since its last
    # commit, e.g. mid-commit). Release it first — time-bounded so a wedged
    # connection can't eat the whole shield window — or the fenced update
    # below waits on our own lock until the shield timeout and the row
    # strands in 'running' anyway.
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
                # fix(v1.6.0 audit B12): terminal writes must stamp
                # completed_at (the ingest tasks all do) — without it the
                # jobs UI renders '-' and retention ages on queue time.
                "completed_at": datetime.now(timezone.utc),
            },
        ):
            await session.rollback()
            # fix(v1.6.0 audit B13): mirror _mark_job_failed's fence-miss
            # cleanup — a swept row leaves an unregistered orphan that used
            # to leak permanently here. Probe for an adopting dataset row;
            # no row means the DROP is safe. If the probe itself errors,
            # prefer leaking the table to dropping a registered dataset's
            # storage.
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
    opaque "column specified more than once" after the whole wait
    (fix(#953), extended to measure by fix(#954)).
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

    Extracted in fix(#1097 review) rather than raising the C901 threshold on
    ``_materialize``: the set had grown to five checks over two layers, and
    they share a subject that the surrounding job bookkeeping does not.
    fix(#1099) retired one of them, the overlay's ungroupable-type recheck.
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
    # fix(#956): an overlay carries columns from BOTH inputs, so it is the only
    # operation that also needs the second layer's live column list — and the
    # only one where two same-named columns are likely rather than exotic.
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

    fix(#1097 review): the router checked a catalog snapshot; a re-upload can
    introduce a column in the alias namespace before the job runs. Same window
    as the two rechecks below, and cheap, because the live column list is
    already in hand here.
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

    fix(#1097 review): the router validated them against column_info at
    enqueue, and the worker re-resolved the join layer's TABLE without ever
    re-checking its COLUMNS. A re-upload that drops or renames a requested
    field left render_spatial_join referencing a column that is no longer
    there, so the CTAS failed after the whole queue wait with a database error
    naming a column the user had legitimately selected when they asked.

    The sibling rechecks beside this one exist for exactly that window; this
    one was the gap in the set.
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

    fix(#1097 review): information_schema reports EVERY array column's
    data_type as 'ARRAY'; the element type only surfaces in udt_name, with a
    leading underscore ('_json' for json[]). An exact data_type comparison
    therefore admitted json[]/xml[] columns straight into GROUP BY, where
    PostgreSQL cannot apply equality to them (SQLSTATE 42883, verified) — and
    the catalog snapshot has the same blind spot, so the failure landed after
    the queue wait. Elements, not arrays: int[]/text[] have equality and group
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

    fix(#1097 review): dissolve names ``by_field`` in its GROUP BY, the router
    checked it against the snapshot, and the snapshot cannot see a json[]
    element type ('ARRAY'). One query answers both failure modes: a column the
    re-upload dropped, and one whose live type has no equality operator.

    fix(#1099): the last caller. Intersect had a twin of this beside it, for
    the overlay columns it named in the same GROUP BY; those attributes are
    joined back outside the aggregate now, so the operation that actually
    groups by a user-chosen column is the only one left needing it.
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

    fix(#953); fix(#956) added the bare name to the return, because an overlay
    reads that layer's live columns out of ``information_schema``, which takes
    a plain name rather than the quoted ref every other caller wants.

    Both two-layer operations need this — clip against a mask layer, and
    spatial_join against a join layer — with the same trust model: access was
    checked at enqueue by the router, and the table name is re-matched against
    ``_SAFE_TABLE`` here because the queue wait sits between the two.

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
    # fix(#1097 review): the geometry requirement is re-applied here, not just
    # at enqueue. A re-upload can change what a layer IS while the job waits in
    # the queue, and the swap updates Dataset.geometry_type, so the value the
    # router checked is not the one the CTAS runs against.
    #
    # Two strengths, because the two layers want different things.
    #
    # "polygonal" is the mask's: _load_mask_dataset refuses points and lines,
    # since unioning them produces a mask that clips nothing meaningful.
    # Nothing downstream notices if that changes — the mask expression simply
    # matches no rows, and the job dies on "Analysis produced no features",
    # which sends the user to look at their own data rather than at the layer
    # that changed underneath them.
    #
    # "any" is the join layer's. A spatial join counts in any direction, so
    # points and lines stay valid and only the absence of geometry is fatal:
    # a re-upload from a non-spatial source sets geometry_type to None and
    # builds a table with no geom_4326 at all, and render_spatial_join
    # references _j.geom_4326 (fix(#1097 review)).
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
    re-uploaded past its cap (fix(#701 review)), and the post-CTAS output
    check is too late to protect the dissolve/mask union itself from OOM —
    so the bounded counts run again here, immediately before the SQL is
    built.
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
    ``regclass`` cast (fix(#701 review)): the tenant statement hook only
    recognizes schema references in SQL text or schema-named binds, and it
    masks string literals — a schema hidden inside a generic bind would
    skip the tenant role setup and fail the lookup in multi-tenant.
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
        # fix(v1.6.0 audit D11): only buffer has a distance to reduce —
        # telling a clip/centroid/dissolve user to shrink a buffer they
        # never set is a dead end.
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

    fix(#786): the terminal write is fenced on the attempt token, like the
    claim and ``_fail_cancelled_job`` — a plain ``job.status = "complete"``
    would overwrite a row the stale-job sweep already failed (a stalled
    heartbeat expires the lease), resurrecting failed → complete and handing
    the user a dataset for a job they were told failed. The fence shares the
    registration transaction, so a miss rolls the Dataset row back with it.
    """
    if await update_ingest_job_for_attempt(
        session,
        uuid.UUID(job_id),
        attempt_id,
        values={
            "status": "complete",
            "dataset_id": dataset_id,
            # fix(v1.6.0 audit B12): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.commit()
        ANALYSIS_JOBS.labels(operation=operation, status="complete").inc()
        return
    await session.rollback()
    logger.warning("analysis.complete_write_superseded", job_id=job_id)
    # The build commit made the output table durable, and the rollback above
    # discarded this attempt's registration. fix(v1.6.0 audit B13): mirror
    # _mark_job_failed's fence-miss cleanup — gate the drop on the adoption
    # probe so a dataset row committed by any other actor keeps its storage,
    # and prefer leaking the table over dropping one the probe can't clear.
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
    """Whether a dataset row has adopted ``out_table`` (fix(v1.6.0 audit B13)).

    Index-backed: ``catalog.datasets`` carries two partial unique indexes on
    ``table_name`` (global and per-tenant). Tenant-scoped in multi_tenant —
    an unscoped probe could match another tenant's dataset of the same name
    and skip a legitimate drop (the IN-01 pattern from the ingest discover
    query). With no tenant context in multi_tenant, report adopted: the
    caller then prefers leaking a table over dropping one it can't attribute.
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
# under. `out_table` is generated inside the worker and nothing durable carried
# it, so a SIGKILL after the materialize commit left `data.<out_table>` (plus
# its GIST index, up to MAX_OUTPUT_BYTES) with no catalog row, no DROP and no
# reconciler that could ever name it. The name is written in the SAME
# transaction that creates the table, so the two become durable together and a
# row that has one has the other.
ANALYSIS_OUTPUT_TABLE_FIELD = "analysis_out_table"


def recorded_analysis_output_tables(user_metadata: object) -> tuple[str, ...]:
    """Every output table name a job row records, in the order recorded.

    fix(#1778 codex r10): the field is a LIST that each attempt appends to. A
    plain string is what it held before this commit and is read as a
    one-element list, so an existing row keeps its pointer. Anything else
    yields nothing rather than raising, because this reads a schemaless JSONB
    blob.
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

    fix(#1778 codex r10): `/jobs/{id}/retry` preserves ``user_metadata``, so
    writing this attempt's name over the field dropped the previous attempt's
    and stranded its table with nothing naming it. Appending is what lets every
    reaper iterate all of them.
    """
    names = list(recorded_analysis_output_tables(user_metadata))
    if out_table not in names:
        names.append(out_table)
    return {**(user_metadata or {}), ANALYSIS_OUTPUT_TABLE_FIELD: names}


# fix(#1778 codex r10): the scope an analysis output table carries, 8 hex
# characters of the job and 8 of the attempt. Job alone was not enough: a retry
# keeps `IngestJob.id` and changes only `attempt_id`, so every attempt of one
# job derived the same name and a sweep holding attempt 1's could drop the
# table attempt 2 had just created under it.
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

    fix(#1778 codex r7) scoped this by job, which stopped two DIFFERENT jobs
    sharing a name. fix(#1778 codex r10) adds the attempt, because a retry is
    the same job: `/jobs/{id}/retry` keeps the id and mints a new attempt
    token, so every attempt derived one name. A stale sweep could capture
    attempt 1's name, settle the job `failed`, and then probe and drop while
    attempt 2 was creating that same name -- and the ownership check passed,
    because the name really was this job's.

    The objection to attempt scoping in r8 was that it strands the previous
    attempt's orphan with nothing naming it, since the row has one field. That
    is answered by making the record accumulate: it holds a LIST of names that
    each attempt appends to, exactly as `unpublished_storage_keys` does since
    r9, and every reaper iterates all of them. So the name identifies one
    attempt's table and the record remembers every attempt's.

    fix(#1778 audit r11): ``collision_suffix`` names the `_N` tag
    ``resolve_analysis_output_table``'s walk tries, and it has to be applied
    HERE, on the original ``base``, not by the caller pre-pending `_N` to
    ``base`` and calling this again. The base is trimmed to leave room for
    the scope AND the tag together, computed fresh from ``base`` every call
    -- the same idiom `generate_table_name`'s own `_with_collision_suffix`
    uses, and for the identical reason: trimming an ALREADY-TRIMMED string a
    second time truncates the very characters that make one candidate differ
    from the next. A ``base`` at or past the reserved limit (46 chars with no
    tag) used to make every walked candidate identical once trimmed, so a
    redelivery of the same attempt with an existing scoped table exhausted
    the whole `_N` walk and raised instead of self-healing.
    """
    scope = analysis_output_scope(job_uuid, attempt_uuid)
    tag = f"_{collision_suffix}" if collision_suffix is not None else ""
    limit = _ANALYSIS_TABLE_MAX_CHARS - len(scope) - len(tag)
    return f"{base[:limit]}{tag}{scope}"


def analysis_output_table_belongs_to(out_table: str, job_uuid: uuid.UUID) -> bool:
    """Whether ``out_table`` carries ``job_uuid``'s scope.

    fix(#1778 codex r7): the ownership check every reaper makes before it drops
    anything. The name embeds its owner, so this needs no catalog read, no
    comment and no lock.

    fix(#1778 codex r10): the attempt half is required to be PRESENT but is not
    compared, because the reaper reads the name off the row that recorded it
    and so already knows the attempt was one of this job's. What this refuses
    is a name belonging to a different job, or one with no scope at all.
    """
    return (
        re.search(
            rf"_{re.escape(job_uuid.hex[:_ANALYSIS_SCOPE_CHARS])}"
            rf"[0-9a-f]{{{_ANALYSIS_SCOPE_CHARS}}}$",
            out_table,
        )
        is not None
    )


# fix(#1778 codex r10): how many `_N` walks the scoped-name probe makes before
# giving up, and how much of the base it probes on. Same bound and same reason
# as `generate_table_name`'s own.
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

    fix(#1778 codex r10). ``generate_table_name`` walks its ``_N`` suffixes
    against the UNSCOPED base while the relation on disk carries the scope, so
    its candidate set and the names that actually exist never intersected: a
    base of ``parcels`` probes ``parcels%``, finds ``parcels_ab12cd34ef56ab78``
    in pg_class, asks whether ``parcels`` is taken, and hands back ``parcels``
    unsuffixed, which scopes straight back onto the occupied name and fails at
    CREATE TABLE. Attempt scoping makes that rare, because a retry gets a
    different suffix, but not unreachable: the same attempt can be delivered
    twice, and then the scoped name is identical.

    So the walk happens here, on the name that will actually be created. One
    prefix probe answers every candidate, and it reads pg_class rather than
    information_schema for the reason ``generate_table_name`` gives: the
    standard filters information_schema to relations the current role has
    privileges on, and an orphan this role never granted itself is exactly the
    one this has to see.

    fix(#1778 audit r11): every candidate below is derived from the SAME
    original ``base`` via ``collision_suffix``, never by pre-pending `_N` to
    ``base`` and trimming again. ``analysis_output_table_name`` reserves room
    for the tag itself now, so a long ``base`` still yields a genuinely
    distinct candidate per suffix instead of the same truncated string N
    times over.
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
# into DDL, so it is re-checked at every use rather than trusted for having
# been sanitized once.
_ANALYSIS_TABLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


# fix(#1778 codex r6): what `drop_unadopted_analysis_output` actually managed
# to establish. The distinction that matters to the stale-job sweeps is FINAL
# versus RETRYABLE: a caller may forget the table's name only once the answer
# can never change, because that name is the last durable pointer to it.
#
#   "adopted"  a dataset row owns the table. Final: it is not an orphan.
#   "dropped"  the DROP committed. Final: there is nothing left to name.
#   "invalid"  the recorded name is not an identifier `generate_table_name`
#              could have produced, so no table of that name was made by this
#              system and no retry can change the string. Final.
#   "skipped"  nothing was named. Final, vacuously.
#   "failed"   the probe or the DROP raised. NOT final. The table may exist and
#              be unadopted, so the record has to survive for the next sweep.
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

    fix(#1778): the probe-then-drop the two fence-miss handlers already ran,
    lifted into one function so the stale-job sweeps can apply the same policy
    to a job whose worker was killed outright. Failure direction is the one
    those handlers chose: an adoption probe that itself errors leaks a table
    rather than dropping a registered dataset's storage.

    The name is re-validated here because the sweeps read it out of
    ``user_metadata``, a JSONB blob with no schema, and it is interpolated into
    a DDL statement that takes no bind parameters.

    fix(#1778 codex r7): ``owner_job_uuid`` is the job whose record is being
    reaped, and a name that is not that job's is refused. It is required, with
    no default. The in-worker handlers would pass their own id either way, so
    an optional gate would have bought nothing but a way to forget it: the
    caller that most needs the check is a sweep acting on a name read off a row
    that may be older than the table now standing at it.

    fix(#1778 codex r6): it REPORTS, rather than returning the same ``None``
    whether it dropped the table or failed to. The two fence-miss handlers can
    ignore that -- they are inside the worker, and the job row still names the
    table afterwards -- but the sweeps cannot. They clear the recorded name on
    the strength of this call, and the name is the last durable pointer to the
    table, so a swallowed failure read as success stripped the record and left
    the table orphaned for good: exactly the leak this function exists to stop,
    reintroduced by the function itself.

    Note that a probe that RAISES is "failed" and not "adopted". Treating an
    unreadable catalog as adoption is the right call for whether to DROP -- it
    prefers a leak to destroying a live dataset's storage -- and the wrong one
    for whether the question is settled, because nothing was established.
    """
    if out_table is None:
        return "skipped"
    if not _ANALYSIS_TABLE_NAME_RE.match(out_table):
        logger.warning("analysis.output_table_name_rejected", job_id=job_id)
        return "invalid"
    # fix(#1778 codex r7): the ownership gate. A sweep reaping a job's record
    # may only drop the table THAT job named, and the name says which job that
    # is. Without this the sweep was free to drop a table a different job had
    # since created under a reused name, between the adoption probe and the
    # DROP. "invalid" rather than "failed": a name that is not this job's can
    # never become this job's, so retrying it forever would pin the row.
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

    fix(#786): fenced on the attempt token FIRST, mirroring
    ``_fail_cancelled_job`` — the previous plain ORM write could overwrite a
    terminal state some other actor already set (the stale-job sweep failing
    the row after a stalled lease, or a final commit that reached the server
    before the connection dropped, leaving the row 'complete'). A successful
    fence proves the row was still 'running', so the registration commit has
    not happened and any committed output table is an unregistered orphan —
    safe to drop. If the fence misses, the row is left alone; the table is
    dropped only when the adoption probe proves no dataset registered it
    (fix(v1.6.0 audit B13)).
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
            # fix(v1.6.0 audit B12): stamp completion time like ingest does.
            "completed_at": datetime.now(timezone.utc),
        },
    ):
        await session.rollback()
        logger.warning("analysis.failed_write_superseded", job_id=job_id)
        # fix(v1.6.0 audit B13): a fence miss means some other actor set a
        # terminal state, but only a completed job has adopted the table —
        # a swept row leaves an unregistered orphan that used to leak
        # permanently. Probe for an adopting dataset row; no row means the
        # DROP is safe. Failure direction stays safe: if the probe itself
        # errors, prefer leaking the table to dropping a registered
        # dataset's storage.
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

    fix(#763): every name is carried — GDAL launders only case/`-`/`#`, so
    ingested tables legitimately hold columns like ``Área`` or ``2020_pop``;
    filtering to identifier-shaped names silently dropped them from every
    analysis output. Rendering quotes via ``_sql_quote_ident``, whose
    colon escape also keeps Socrata-style ``:id`` columns from being parsed
    as bind parameters by ``text()``.
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

    fix(#786): ``_enforce_output_size`` probes ``pg_total_relation_size``
    right after the CTAS, and the post-CTAS DELETE cannot shrink what it
    measures — dead tuples keep their pages until a rewrite. Rows the
    cleanup removes therefore counted toward the output ceiling for
    buffer/centroid/dissolve and the drawn-mask clip, failing analyses
    whose real output is small. The clip-by-layer branch has filtered
    in-CTAS since fix(#719 review); this extends the same rule to the
    other shapes. ``OFFSET 0`` fences subquery pull-up so the geometry
    expression (``ST_Buffer`` at worst) is evaluated once per row rather
    than re-evaluated inside the outer WHERE.
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
        # fix(#956): the only branch whose output rows are not 1:1 with source
        # rows, so it is also the only one besides dissolve that generates its
        # own gid — the unconditional ADD PRIMARY KEY (gid) below would die on
        # duplicates otherwise. The empty-geometry filter is inside the
        # renderer for the same reason clip's is (fix(#719 review)):
        # _enforce_output_size measures the CTAS before the post-CTAS DELETE
        # can shrink it.
        return render_intersect_pairs(
            src_ref,
            mask_table_ref,
            src_columns=[_sql_quote_ident(c) for c in carry_cols],
            mask_columns=[_sql_quote_ident(c) for c in (mask_carry_cols or [])],
        )
    if operation == "measure":
        # fix(#954): the same renderer the preview uses, so a saved measurement
        # equals the one the user approved rather than being recomputed by a
        # second expression that could drift.
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
        # tie-break, which is the difference between one output row per source
        # feature and a duplicate-gid CTAS that dies on ADD PRIMARY KEY below.
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
        # GEOMETRYCOLLECTION, which the MVT tile path can't render — keep only
        # the highest-dimension components so the output stays typed.
        union_expr = "ST_Multi(ST_CollectionExtract(ST_Union(ST_MakeValid(geom_4326))))"
        if by_field:
            # fix(#836): quote via _sql_quote_ident like every other identifier
            # site here — _SAFE_IDENT already guards by_field, but a lone
            # inline-quoting divergence is where the next escaping bug hides.
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
        # unlike the clip branch below there is nothing for the not-empty
        # filter to catch downstream — _wrap_not_empty applies it to the source
        # geometry directly, which is what the output geometry IS.
        #
        # The DRAWN-mask half needs no branch at all: render_geometry_expr
        # returns the pass-through and its <where>, and the generic tail
        # below is already the right shape.
        where = render_select_by_location_where(mask_table_ref, src="_src")
        cols = "".join(f"_src.{_sql_quote_ident(c)}, " for c in carry_cols)
        return _wrap_not_empty(
            f"SELECT _src.gid, {cols}_src.geom_4326 AS geom"
            f" FROM {src_ref} AS _src{where}"
        )
    if operation == "clip" and mask_table_ref is not None:
        # fix(#719): the same subdivided-mask join the preview uses. This used
        # to render a single whole-layer ST_Union instead, so a clip whose
        # preview came back in under a second could exhaust the 300s CTAS
        # budget on "Create dataset" (see render_clip_layer_join for the
        # measurements).
        #
        # The empty-result filter is applied HERE, not left to the post-CTAS
        # DELETE (fix(#719 review)). The row filter admits a source row on a
        # bounding-box overlap, so a wide or concave mask lets through rows
        # whose geometries never actually intersect; their lateral yields
        # geom_out = NULL. _enforce_output_size runs against the CTAS BEFORE
        # that DELETE, so those rows could fail an analysis as oversized when
        # the dataset it would have saved is small. Clip has no source-feature
        # cap, so nothing else bounds how many of them there are.
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
        # Fenced claim (fix(#692), the ingest_file pattern): pending → running
        # succeeds at most once per attempt token, and stamps
        # started_at/heartbeat_at — the liveness signals the stale-job sweep
        # and the lease below depend on (fix(#682 review): statement_timeout
        # bounds each STATEMENT, not the task, so a large materialize can
        # legitimately run long and only the lease keeps it out of the sweep).
        # Without the claim this worker would act on rows some other actor
        # already moved to a terminal state — the pending-sweeper failing a
        # backlogged job after an hour, or the defer orphan-guard failing the
        # row after the queue INSERT committed — and resurrect them: the
        # per-user cap admits a second CTAS, and a dataset appears for a job
        # the user was told failed.
        #
        # The row's own attempt_id is the token (column-defaulted at
        # creation; retry=0, so there is no second delivery to fence against).
        # Rows predating that default are adopted atomically.
        attempt_id = job.attempt_id or await resolve_ingest_job_attempt(job.id, None)
        if attempt_id is None or not await claim_ingest_job_attempt(
            session, job.id, attempt_id
        ):
            await session.rollback()
            logger.warning("analysis.attempt_not_claimed", job_id=job_id)
            return
        # current_step only, no numeric progress: the operation is a single
        # CTAS, so there is no intra-statement telemetry to report and a bar
        # parked at 10% for five minutes reads as "stuck" rather than "busy".
        job.current_step = "analyzing"
        await session.commit()

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
        # Only drop the output table on failure if THIS job created it: when
        # CREATE TABLE itself fails because a concurrent job won the same
        # generated name, an unconditional cleanup would destroy the winner's
        # table while its dataset registration stays live.
        out_table_created = False
        # fix(#1013 review): flipped when the CTAS transaction commits and
        # registration re-arms its own statement_timeout, so a failure after
        # that point quotes the budget that actually fired.
        registration_started = False
        # Created inside the try so the finally below always reaps it: a
        # heartbeat left running after an exception here would renew a lease
        # for a job nobody is executing, and the sweep can never fail a row
        # with a fresh lease (fix(#692)).
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

            # Layer-sourced clip mask: re-resolve the table name at run time
            # (access was checked at enqueue by the router, same trust model
            # as the source dataset).
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
            # fix(#1097 review): the plain name is kept now, not discarded. The
            # transferred fields have to be re-checked against this layer's
            # LIVE columns, and information_schema takes a name rather than the
            # quoted ref.
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
            # fix(#1778 codex r7/r10): scoped by this job AND this attempt, so
            # neither another job nor another attempt of this one can be handed
            # the same physical name. `generate_table_name` still chooses the
            # readable half and still collides against the catalog and the
            # retired names, which is what the eventual dataset table_name
            # needs; the `_N` walk that matters for the RELATION is the scoped
            # one below, because the unscoped walk can never see a scoped name.
            out_table = await resolve_analysis_output_table(
                session,
                base=_base_table,
                job_uuid=uuid.UUID(job_id),
                attempt_uuid=attempt_id,
                schema=_schema,
            )
            # fix(#1778): the name, on the durable row, in the same transaction
            # that creates the table (the commit after ANALYZE below). Without
            # it a hard kill after that commit left the table unreachable: the
            # stale sweep is a plain status UPDATE, every DROP of this table
            # lives in a handler this process would never run, and no
            # reconciler can name a table nothing recorded.
            #
            # fix(#1778 codex r10): a LIST that each attempt APPENDS to, the
            # shape `unpublished_storage_keys` took in r9 and for the same
            # reason. `/jobs/{id}/retry` preserves `user_metadata`, so writing
            # this attempt's name over the field dropped the previous attempt's
            # and stranded its table with nothing naming it. A string from
            # before this commit is read as a one-element list, so an existing
            # row keeps its pointer.
            job.user_metadata = append_analysis_output_record(
                job.user_metadata, out_table
            )
            if collision_warning:
                # fix(#786): persisted like the upload path (tasks_vector) —
                # the job-status endpoint surfaces
                # user_metadata['collision_warning'] as warning_message, so
                # discarding it here silently landed an analysis output in
                # e.g. parcels_buffered_3 with no indication to the user.
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
            # INVARIANT: from the user_metadata/current_step assignments above
            # to the commit after ANALYZE, every statement must stay text() —
            # SQLAlchemy autoflushes only for ORM queries, so the dirty job
            # row is flushed (and its row lock taken) only microseconds inside
            # that commit. A single ORM select() added in this stretch would
            # autoflush the dirty row and hold the job-row lock across the
            # CTAS, blocking renew_ingest_job_heartbeat (separate session,
            # same row) for the entire build.
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
                # in memory at once, so a grouped dissolve over enough
                # polygons can OOM-kill the shared db container. Sorted
                # aggregation bounds memory to one group at a time. The
                # enqueue-time feature cap is the first line of defense;
                # this is the second.
                await session.execute(text("SET LOCAL enable_hashagg = off"))
            await session.execute(text(f"CREATE TABLE {out_ref} AS {select_sql}"))
            out_table_created = True
            # Early exit only — a table already over the ceiling must not
            # hold the single worker slot through the rewrite phases. The
            # authoritative check runs after add_4326_column below.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # Rows with nothing to show are excluded inside the CTAS for
            # EVERY shape (fix(#786), extending fix(#719 review)'s clip
            # rule via _wrap_not_empty): buffer/centroid map NULL source
            # geometries to NULL, dissolve unions an all-NULL group to NULL,
            # and boundary-grazing clips survive ST_Intersects but extract to
            # EMPTY (see analysis_sql.render_geometry_expr). The preview
            # filters the same rows in SQL (fix(#680 review)) — the saved
            # dataset must agree with the preview the user approved. This
            # DELETE stays as the backstop enforcing that invariant should a
            # future query shape miss the in-CTAS filter.
            await session.execute(
                text(f"DELETE FROM {out_ref} WHERE geom IS NULL OR ST_IsEmpty(geom)")
            )
            has_features = await session.scalar(
                text(f"SELECT EXISTS (SELECT 1 FROM {out_ref})")
            )
            if not has_features:
                # e.g. a clip matching nothing, or dissolving an empty
                # dataset (whose no-GROUP-BY aggregate still yields one
                # NULL-geometry row) — fail loud instead of registering junk.
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
            # payload, rewrites every row, and adds the GIST index — the
            # post-CTAS probe undercounts the final footprint by a multiple,
            # so the ceiling is enforced here, on the finished relation.
            await _enforce_output_size(session, _schema, out_table, operation=operation)
            # In-transaction ANALYZE (fix(#692)): the table only becomes
            # visible to autovacuum at the commit below, and the first tile
            # queries land before its pass — without statistics the planner
            # has no geometry selectivity for `&&` against the fresh GIST
            # index and can seq-scan a large output.
            await session.execute(text(f"ANALYZE {out_ref}"))
            job.current_step = "registering"
            await session.commit()
            registration_started = True

            # The commit above ended the transaction and the SET LOCAL with
            # it — give registration its own budget (fix(#692)). Set here
            # rather than inside register_existing_table, which is shared
            # with the upload path.
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
                # fix(#1452): this output table was CTAS'd a few lines up, so
                # it is GeoLens's to drop when the dataset is deleted. Without
                # this it would be indistinguishable from a table an operator
                # registered — same postgis origin, same null source_format —
                # and the detach that protects the operator's table would leak
                # one of these on every delete.
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
                    # fix(#1097 review): every operation that can take a
                    # DRAWN mask, not clip alone. The drawn geometry itself is
                    # deliberately excluded from provenance (it can be
                    # kilobytes), so for a drawn select_by_location this
                    # discriminator was the only trace that an area shaped the
                    # selection at all — without it those params serialise
                    # empty and the lineage says a selection happened by no
                    # visible means.
                    #
                    # The sibling of the job-metadata fix in the previous
                    # round. That one was the writer the review named; this is
                    # the other writer of the same fact, and fixing only the
                    # named one is what left this behind.
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
            # Graceful worker shutdown cancels this task after the drain
            # window; `except Exception` cannot catch it, and retry=0 means no
            # redelivery — without this branch the row would strand in
            # 'running', holding the user's one analysis slot, until the
            # 60-minute sweep (fix(#692)). Bookkeeping runs on a fresh session
            # (this one may be mid-statement) and is shielded so the
            # cancellation doesn't also cancel it; then re-raise so the queue
            # records the abort.
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
            # The row has left 'running' by now, so the loop would exit on its
            # own at the next renewal — stop (cancel + await, the ingest
            # convention) so the task neither outlives the work by a heartbeat
            # interval nor leaks a pending task through worker shutdown.
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
