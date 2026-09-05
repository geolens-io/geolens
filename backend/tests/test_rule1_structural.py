"""Rule-1 structural guard: every route handler that fetches a guarded model
must call a sanctioned access check (fix(#822)).

The pre-commit Rule-1 hook (.pre-commit-config.yaml, visibility-filter-coverage)
is a cheap commit-time grep with three blind spots flagged by the 1.6.0
pre-tag audit:

- fetch paths that do not go through ``get_dataset(`` (``db.get(Dataset, ...)``,
  raw ``select(Record)``, service-layer loads);
- file scope — a guard anywhere in the file satisfies the grep even when a
  specific handler lacks one;
- ``processing/`` is excluded from the hook's ``files:`` pattern.

This module closes those gaps structurally. It walks the real FastAPI route
table, parses each handler's source (plus one level of directly-called
``app.*`` helper functions) into an AST, and asserts that any handler whose
effective source fetches a guarded model (``Record``, ``Dataset``, ``Map``,
``RecordEmbedding``, ``IngestJob``) also CALLS one of the sanctioned guards. Model names are
resolved by class identity through the function's module globals and its
function-local imports, so aliases like ``Dataset as DatasetModel`` or
``Map as MapORM`` are covered, and multi-line ``select(\n    Model``
expressions match because detection works on call nodes, not source lines
(codex review on #863). Service accessors (``get_dataset`` / ``get_record``
/ ``get_map`` and the ProcessingPort method forms) count as fetches, and
guard calls are credited only when they resolve to the sanctioned guard
objects by identity. Filter-returning guards (``apply_visibility_filter``
and friends) count only when their result is consumed — a bare call leaves
the original statement unfiltered. Handlers that are unguarded by design
live in ``ALLOWLIST`` with a per-entry justification; the allowlist is
asserted exact in both directions so entries cannot go stale.

fastapi 0.140 trap: ``include_router`` is lazy, so ``app.routes`` holds only
the top-level entries (~89) and a plain ``isinstance(route, APIRoute)`` scan
silently sees a fraction of the API. ``fastapi.routing.iter_route_contexts``
yields the flattened table; the effective full path comes from ``ctx.path``
(``ctx.route.path`` lacks parent prefixes for nested includes). The
route-count floor below turns any future lazy-scan regression into a loud
failure instead of a silent no-op.

Known limits (accepted trade-offs, mirrored in the PR for #822):

- Detection follows exactly ONE level of directly-called plain functions
  resolvable through the handler's module globals. Fetches hidden behind
  method calls on locals (``svc = SomeService(db); await svc.get(...)``) or
  deeper call chains are invisible; domain guard helpers that themselves
  delegate (``_check_record_ownership``) are sanctioned by name instead and
  integrity-checked by ``test_delegated_guards_still_enforce_access``.
- Model aliases created through ``sqlalchemy.orm.aliased(Model)`` or fully
  dynamic factories are not resolved.
- A sanctioned guard CALL anywhere in the effective source satisfies the
  check. That is handler-scoped (much tighter than the hook's file scope)
  but a handler doing two fetches, one guarded and one not, would still
  pass.
- Dataflow completeness is bounded, not full taint analysis. An assigned
  value-guard result must be LOADED again afterwards (so
  ``filtered = apply_visibility_filter(stmt, ...)`` with ``filtered``
  never read fails), but the analysis does not verify the loaded value is
  what actually reaches ``execute()`` — assigned-and-reloaded while the
  raw statement is executed still passes. Deeper dataflow findings in
  this family are documented limits, not bugs in this test.
- Execution-path credit is an approximation, not a control-flow graph.
  Two known residual shapes: a SYNC ``app.*`` helper whose only call site
  sits inside a never-invoked nested def or lambda is still expanded and
  may over-credit its internal guard (the executed-call-site restriction
  applies to direct guard calls, not to sync helper expansion); and the
  awaited-argument execution proof accepts a coroutine passed as a direct
  argument of ANY awaited call, not only known schedulers like
  ``asyncio.gather`` — ``await store(helper())`` could retain the
  coroutine without running it. Neither shape occurs in the codebase;
  both are accepted trade-offs of staying deterministic and CFG-free.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
import typing
from functools import lru_cache
from typing import Any, NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Core guards from app/modules/catalog/authorization.py (AGENTS.md Rule 1).
_CORE_GUARDS = (
    "check_dataset_access_or_anonymous",
    "check_dataset_access",
    "check_dataset_write_access",
    "apply_visibility_filter",
    # fix(#1298): batch sibling of check_dataset_access — same fail-closed
    # 404, one query for the whole set instead of one per id.
    "check_datasets_access_bulk",
)

# Domain guard helpers that wrap the core checks (or implement the
# equivalent RBAC logic for their model). Their integrity is pinned by
# test_delegated_guards_still_enforce_access below.
_DELEGATED_GUARDS = (
    # maps: app/modules/catalog/maps/{_router_helpers,service_crud,service_shared}.py
    "check_map_ownership",
    "_check_map_read_access",
    "_apply_map_visibility_filter",
    # maps: app/modules/catalog/maps/service_layers.py — bulk variant of
    # check_dataset_access, kept in sync with can_access_dataset.
    "bulk_check_dataset_access",
    # records: app/modules/catalog/records/router.py
    "_check_record_read_access",
    "_check_record_ownership",
    # tiles: app/processing/tiles/router.py — the vector-tile access model
    # (embed token, HMAC signature for non-public, published-status gating).
    "_authorize_vector_tile_request",
    # tiles: app/processing/tiles/router.py — the SEC-01 status-aware gate
    # for the tile-token minting endpoints; delegates non-public RBAC to
    # port.check_dataset_access and 404s unpublished-public for non-owners.
    "_enforce_tile_token_access",
)

# Guards that deny by RAISING (404/403) — a bare ``await guard(...)``
# statement is the correct usage, so the call alone counts.
_RAISING_GUARDS = frozenset(
    {
        "check_dataset_access_or_anonymous",
        "check_dataset_access",
        "check_dataset_write_access",
        "check_datasets_access_bulk",
        "check_map_ownership",
        "_check_map_read_access",
        "_check_record_read_access",
        "_check_record_ownership",
        "_authorize_vector_tile_request",
        "_enforce_tile_token_access",
    }
)

# Guards whose RETURN VALUE is the protection (a filtered Select, or the
# accessible-id set). SQLAlchemy Selects are immutable: a bare
# ``apply_visibility_filter(stmt, ...)`` statement discards the filtered
# statement and protects nothing. These count only when the result is
# consumed — assigned, returned, or passed on (codex P1 on #863, round 3).
_VALUE_GUARDS = frozenset(
    {
        "apply_visibility_filter",
        "_apply_map_visibility_filter",
        "bulk_check_dataset_access",
    }
)

# The raising/value split must stay in sync with the documented guard lists.
assert _RAISING_GUARDS | _VALUE_GUARDS == frozenset(_CORE_GUARDS + _DELEGATED_GUARDS)
assert not (_RAISING_GUARDS & _VALUE_GUARDS)


@lru_cache(maxsize=1)
def _guard_objects() -> dict[str, Any]:
    """The sanctioned guard FUNCTION OBJECTS, keyed by canonical name.

    Guard calls are credited only when the called name resolves to one of
    these objects by identity (codex P2 on #863, round 5) — a handler
    defining its own ``check_dataset_access`` or calling
    ``some_service.check_dataset_access(...)`` on an unrelated object does
    not count. Fails loudly here if a sanctioned guard is renamed or moved.
    """
    from app.modules.catalog import authorization
    from app.modules.catalog.maps import (
        _router_helpers,
        service_crud,
        service_layers,
        service_shared,
    )
    from app.modules.catalog.records import router as records_router
    from app.processing.tiles import router as tiles_router

    guard_objects = {
        "check_dataset_access_or_anonymous": (
            authorization.check_dataset_access_or_anonymous
        ),
        "check_dataset_access": authorization.check_dataset_access,
        "check_dataset_write_access": authorization.check_dataset_write_access,
        "check_datasets_access_bulk": authorization.check_datasets_access_bulk,
        "apply_visibility_filter": authorization.apply_visibility_filter,
        "check_map_ownership": service_crud.check_map_ownership,
        "_check_map_read_access": _router_helpers._check_map_read_access,
        "_apply_map_visibility_filter": service_shared._apply_map_visibility_filter,
        "bulk_check_dataset_access": service_layers.bulk_check_dataset_access,
        "_check_record_read_access": records_router._check_record_read_access,
        "_check_record_ownership": records_router._check_record_ownership,
        "_authorize_vector_tile_request": tiles_router._authorize_vector_tile_request,
        "_enforce_tile_token_access": tiles_router._enforce_tile_token_access,
    }
    assert set(guard_objects) == _RAISING_GUARDS | _VALUE_GUARDS
    return guard_objects


@lru_cache(maxsize=1)
def _guards_requiring_await() -> frozenset[str]:
    """Sanctioned guards that are coroutine functions.

    Calling a coroutine guard WITHOUT ``await`` only creates a coroutine —
    no authorization runs and no denial ever raises — so for these the call
    must sit under an ``ast.Await`` to count (codex P1 on #863, round 4).
    Keyed on ``inspect.iscoroutinefunction`` of the real guard objects
    rather than a hardcoded list, so a guard changing between sync and
    async updates the requirement automatically.
    """
    return frozenset(
        name
        for name, obj in _guard_objects().items()
        if inspect.iscoroutinefunction(obj)
    )


# ProcessingPort guard wrappers: processing/ code cannot import catalog
# authorization at module level (test_layering), so it calls the guards as
# methods on a ProcessingPort — ``await port.check_dataset_access(...)``.
# Those attribute calls cannot be identity-resolved (the port is a local),
# so they are credited by method name ONLY when the receiver is provably a
# port: a parameter annotated ProcessingPort or a get_processing_port()
# result. The default implementation's delegation to the real guards is
# pinned by test_delegated_guards_still_enforce_access.
_PORT_GUARD_METHODS = frozenset(
    {"check_dataset_access", "check_dataset_write_access", "apply_visibility_filter"}
)


# ---------------------------------------------------------------------------
# Allowlist — handlers that touch a guarded model without a sanctioned guard,
# each unguarded BY DESIGN. Keyed by the unwrapped endpoint's
# ``module.qualname``. Asserted exact: an entry that becomes guarded (or a
# handler that gets renamed) fails the test until the list is updated.
# ---------------------------------------------------------------------------

ALLOWLIST: dict[str, str] = {
    # Admin audit feed; gated by require_permission("manage_settings"). The
    # flagged fetch is resolve_resource_names() selecting Dataset.id/Record.title
    # only to label audit rows for the admin UI.
    "app.modules.audit.router.list_audit_logs": (
        "admin-gated (manage_settings); Dataset/Record select only labels audit rows"
    ),
    # Share-token capability route (crawler HTML card). Validates the token,
    # then explicitly requires map.visibility == "public" before rendering any
    # map details; non-public/expired links get an empty SPA-redirect shell.
    "app.modules.catalog.maps.router_sharing.shared_map_card_endpoint": (
        "share-token capability route; hard-requires map.visibility == 'public'"
    ),
    # Duplicate-source existence check before creating an IngestJob. The
    # select is scoped ``Record.created_by == user.id`` — the caller can only
    # ever see their own datasets in the 409 payload.
    "app.modules.catalog.sources.router.preview_service_layer": (
        "duplicate-source check scoped to the caller's own records "
        "(Record.created_by == user.id)"
    ),
    # Batch duplicate check on Dataset.source_url for STAC imports; gated by
    # create_layers. Reveals only that an href (which the caller supplied) is
    # already registered — no record content is returned.
    "app.modules.catalog.sources.stac_router.stac_import": (
        "global source_url existence check for dedupe; returns no record content"
    ),
    # Registers an existing physical DB table as a dataset; gated by the
    # upload capability. select(Dataset.table_name ...) is an
    # already-registered existence check on the physical table, not a
    # per-record data read.
    "app.processing.ingest.router.register_table": (
        "upload-gated physical-table registration; select is a dedupe existence check"
    ),
    # Same service path (register_existing_table) as register_table.
    "app.processing.ingest.router.bulk_register_tables": (
        "upload-gated physical-table registration; select is a dedupe existence check"
    ),
    # ---------------------------------------------------------------------
    # fix(#1860): the IngestJob sweep. These seven handlers fetch a job
    # row and none of them calls a CATALOG guard, because a job is owned by
    # the user who created it rather than reached through a dataset's
    # visibility. Each names the check it does apply instead.
    # ---------------------------------------------------------------------
    # Ops-only stale-job reaper; gated by require_mode_permission
    # (manage_users single-tenant, manage_tenants multi-tenant). It acts on
    # the whole stale set on a clock, never on a caller-named row, and its
    # response is counts.
    "app.platform.jobs.router.cleanup_stale_jobs": (
        "ops-gated (manage_users / manage_tenants); acts on the stale set, "
        "returns counts and no job content"
    ),
    # Owner-or-policy: creator passes, everyone else goes through
    # _can_access_another_users_job (the effective permission matrix), and a
    # refusal is a 403 recorded as a permission denial.
    "app.platform.jobs.router.get_job_status": (
        "owner-or-policy via _can_access_another_users_job; 403 on denial"
    ),
    "app.platform.jobs.router.retry_job": (
        "owner-or-policy via _can_access_another_users_job; 403 on denial"
    ),
    # All four ingest doors load the job through get_job_or_404, which is
    # creator-or-admin and raises 404/403 before the handler sees the row.
    "app.processing.ingest.router.commit_import": (
        "creator-or-admin via get_job_or_404 (404 unknown, 403 not yours)"
    ),
    "app.processing.ingest.router.commit_fan_out": (
        "creator-or-admin via get_job_or_404 (404 unknown, 403 not yours)"
    ),
    "app.processing.ingest.router.complete_presigned_upload": (
        "creator-or-admin via get_job_or_404 before lock_presigned_job"
    ),
    "app.processing.ingest.router.preview_file": (
        "creator-or-admin via get_job_or_404 (404 unknown, 403 not yours)"
    ),
}

# ---------------------------------------------------------------------------
# Route walking + source analysis
# ---------------------------------------------------------------------------


class _HandlerReport(NamedTuple):
    key: str  # module.qualname of the unwrapped endpoint
    path: str  # effective full path (ctx.path — includes parent prefixes)
    methods: tuple[str, ...]
    fetch_lines: tuple[str, ...]  # evidence lines for guarded-model fetches
    guarded: bool


def _unwrap(fn: Any) -> Any:
    seen: set[int] = set()
    while hasattr(fn, "__wrapped__") and id(fn) not in seen:
        seen.add(id(fn))
        fn = fn.__wrapped__
    return fn


def _source_of(fn: Any) -> str:
    try:
        return textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return ""


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


@lru_cache(maxsize=1)
def _guarded_model_classes() -> tuple[type, ...]:
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.modules.catalog.maps.models import Map
    from app.platform.jobs.models import IngestJob
    from app.processing.embeddings.models import RecordEmbedding

    # fix(#1860): IngestJob joined the set because a job row carries the
    # uploader's filename and the failure text of their run, and every
    # job-row endpoint reported "no fetch detected" while it was outside.
    # A whole class of read was invisible to this gate rather than clean.
    return (Dataset, Record, Map, RecordEmbedding, IngestJob)


# ProcessingPort accessors that hand a guarded ORM class to processing/ code
# (test_layering forbids module-level catalog imports there). An assignment
# like ``Dataset = get_processing_port().get_dataset_orm_class()`` binds the
# guarded class under a local name.
_PORT_MODEL_ACCESSORS = frozenset({"get_dataset_orm_class", "get_record_orm_class"})


def _bound_objects(
    fn: Any, tree: ast.Module, targets: tuple[Any, ...]
) -> dict[str, Any]:
    """Local names bound to any of ``targets``, resolved by OBJECT IDENTITY.

    Covers module-level bindings (which land in the function's module
    globals) and function-local ``from X import Y as Z`` statements
    (resolved through ``sys.modules``, including relative imports).
    Returns name -> matched target object.
    """
    bound: dict[str, Any] = {}
    for name, value in getattr(fn, "__globals__", {}).items():
        if any(value is target for target in targets):
            bound[name] = value
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module_name = node.module or ""
        if node.level:  # relative import — resolve against the function's module
            try:
                base = fn.__module__.rsplit(".", node.level)[0]
            except (AttributeError, IndexError):
                continue
            module_name = f"{base}.{module_name}" if module_name else base
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for alias in node.names:
            value = getattr(module, alias.name, None)
            if any(value is target for target in targets):
                bound[alias.asname or alias.name] = value
    return bound


def _bound_names(fn: Any, tree: ast.Module, targets: tuple[Any, ...]) -> set[str]:
    return set(_bound_objects(fn, tree, targets))


def _model_aliases(fn: Any, tree: ast.Module) -> frozenset[str]:
    """Names bound to a guarded model class, resolved by CLASS IDENTITY.

    Covers module-level bindings (``from ...models import Dataset as
    DatasetModel`` lands in the module globals), function-local imports
    (``from app...models import Map as MapORM`` inside the body), and
    ProcessingPort ORM-class accessor assignments, so aliased fetches are
    detected structurally instead of by literal class name (codex P1 on
    #863). ``sqlalchemy.orm.aliased(Model)`` constructs remain invisible.
    """
    names = _bound_names(fn, tree, _guarded_model_classes())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, (ast.Name, ast.Attribute))
            and (value.func.id if isinstance(value.func, ast.Name) else value.func.attr)
            in _PORT_MODEL_ACCESSORS
        ):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return frozenset(names)


@lru_cache(maxsize=1)
def _select_functions() -> tuple[Any, ...]:
    import sqlalchemy

    return (sqlalchemy.select,)


def _select_aliases(fn: Any, tree: ast.Module) -> frozenset[str]:
    """Names bound to ``sqlalchemy.select``, so aliased imports like
    ``from sqlalchemy import select as sel`` still register as fetches
    (codex P1 on #863, round 3). The literal names ``select`` /
    ``select_from`` are always recognized in addition to these.
    """
    return frozenset(_bound_names(fn, tree, _select_functions()))


@lru_cache(maxsize=1)
def _accessor_functions() -> tuple[Any, ...]:
    """Domain service accessors that fetch-and-return a guarded model.

    Calls to these (resolved by identity, so function-local imports and
    aliases count) are fetch evidence just like a raw select — they are the
    normal by-ID service paths Rule 1 exists for (codex P1 on #863, round 5).
    """
    from app.modules.catalog.datasets.domain.service import get_dataset
    from app.modules.catalog.maps.service_crud import get_map, get_map_with_layers
    from app.modules.catalog.records.service import get_record

    return (get_dataset, get_map, get_map_with_layers, get_record)


# Accessor METHOD names for attribute calls whose receiver cannot be
# identity-resolved (the ProcessingPort protocol, service facades bound to
# locals). Name-based and fail-closed: a same-named method on an unrelated
# object at worst adds fetch evidence, never a guard.
_ACCESSOR_METHOD_NAMES = frozenset(
    {
        "get_dataset",
        "get_record",
        "get_dataset_with_attributes",
        "get_map",
        "get_map_with_layers",
    }
)


def _port_base_names(tree: ast.Module) -> set[str]:
    """Names that provably hold a ProcessingPort in this source.

    Two shapes: a parameter annotated ``ProcessingPort`` (Name or string
    annotation) and an assignment from ``get_processing_port()``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                ann = arg.annotation
                if isinstance(ann, ast.Name) and ann.id == "ProcessingPort":
                    names.add(arg.arg)
                elif (
                    isinstance(ann, ast.Constant)
                    and isinstance(ann.value, str)
                    and "ProcessingPort" in ann.value
                ):
                    names.add(arg.arg)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if fname == "get_processing_port":
                names.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
    return names


def _is_port_base(expr: ast.expr, port_names: set[str]) -> bool:
    """True when ``expr`` is provably a ProcessingPort receiver."""
    if isinstance(expr, ast.Name):
        return expr.id in port_names
    if isinstance(expr, ast.Call):
        func = expr.func
        fname = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else None)
        )
        return fname == "get_processing_port"
    return False


def _attr_chain_object(fn: Any, func: ast.Attribute) -> Any:
    """Resolve ``mod.attr1.attr2`` through the function's module globals."""
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    obj = getattr(fn, "__globals__", {}).get(node.id)
    for attr in reversed(parts):
        if obj is None:
            return None
        obj = getattr(obj, attr, None)
    return obj


def _root_name(expr: ast.expr) -> str | None:
    """The base Name of an expression: ``Map`` for ``Map``, ``Map.id``, etc."""
    while isinstance(expr, ast.Attribute):
        expr = expr.value
    if isinstance(expr, ast.Name):
        return expr.id
    return None


def _discarded_call_ids(tree: ast.Module) -> set[int]:
    """Ids of Call nodes whose result is discarded.

    A call is discarded when it is the value of a bare expression statement
    (unwrapping ``await``) — nothing assigns, returns, or forwards it.
    """
    discarded: set[int] = set()
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Expr):
            value = stmt.value
            if isinstance(value, ast.Await):
                value = value.value
            if isinstance(value, ast.Call):
                discarded.add(id(value))
    return discarded


def _awaited_call_ids(tree: ast.Module) -> set[int]:
    """Ids of Call nodes that sit directly under an ``ast.Await``."""
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
    }


def _assigned_call_targets(tree: ast.Module) -> dict[int, tuple[frozenset[str], int]]:
    """Call ids that are the value of an assignment (unwrapping ``await``).

    Maps call id -> (assigned Name targets, assignment end line). Used to
    require that an assigned value-guard result is actually loaded again
    afterwards (codex P1, round 8).
    """
    out: dict[int, tuple[frozenset[str], int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            continue
        names: set[str] = set()
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                names.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
        out[id(value)] = (frozenset(names), node.end_lineno or node.lineno)
    return out


def _name_load_lines(tree: ast.Module) -> dict[str, tuple[int, ...]]:
    """Line numbers at which each name is read (``ast.Load`` context)."""
    loads: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.setdefault(node.id, []).append(node.lineno)
    return {name: tuple(lines) for name, lines in loads.items()}


def _awaited_argument_call_ids(tree: ast.Module) -> set[int]:
    """Ids of Call nodes passed as direct arguments of an awaited call.

    Covers ``await asyncio.gather(_fetch_a(), _fetch_b())``: the inner
    invocations are not directly under an ``ast.Await``, but the awaited
    outer call schedules and runs them, so a coroutine invoked this way
    provably executes. ``create_task`` without an awaited outer call, or a
    coroutine stashed in a list, is NOT covered — conservative.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)):
            continue
        outer = node.value
        for arg in [*outer.args, *(kw.value for kw in outer.keywords)]:
            if isinstance(arg, ast.Call):
                ids.add(id(arg))
    return ids


def _direct_calls_and_nested_defs(
    nodes: list[ast.AST],
) -> tuple[list[ast.Call], list[ast.AST]]:
    """Calls in the given statements' own scope, stopping at nested defs/lambdas."""
    calls: list[ast.Call] = []
    nested: list[ast.AST] = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            nested.append(node)
            continue
        if isinstance(node, ast.Call):
            calls.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return calls, nested


def _guard_creditable_call_ids(tree: ast.Module) -> set[int]:
    """Call ids on the analyzed function's own EXECUTION PATH (guard scope).

    ``ast.walk`` visits nested function bodies, so a guard awaited inside a
    nested def that may never run credited the enclosing handler (codex P2,
    round 7). Guard credit is restricted to:

    - calls in the analyzed function's own body (and at module level), and
    - calls in a FIRST-LEVEL nested def that the outer body provably
      invokes by simple name — the ``list_maps`` closure pattern
      (``_apply_vis_filter`` wrapping ``_apply_map_visibility_filter``).
      An async nested def's invocation must provably RUN the coroutine:
      directly awaited, or a direct argument of an awaited call (the STAC
      ``await asyncio.gather(_fetch_extents(), ...)`` idiom).

    Lambdas, deeper nesting, and callbacks passed without a direct call
    never contribute guard credit (conservative). Fetch evidence is
    unaffected — counting a maybe-run fetch is fail-closed.
    """
    awaited = _awaited_call_ids(tree)
    awaited_args = _awaited_argument_call_ids(tree)
    creditable: set[int] = set()
    module_calls, top_defs = _direct_calls_and_nested_defs(list(tree.body))
    creditable.update(id(call) for call in module_calls)
    for outer in top_defs:
        if isinstance(outer, ast.Lambda):
            continue
        own_calls, nested = _direct_calls_and_nested_defs(
            list(ast.iter_child_nodes(outer))
        )
        creditable.update(id(call) for call in own_calls)
        nested_by_name = {
            node.name: node
            for node in nested
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for call in own_calls:
            if not isinstance(call.func, ast.Name):
                continue
            nested_def = nested_by_name.get(call.func.id)
            if nested_def is None:
                continue
            if (
                isinstance(nested_def, ast.AsyncFunctionDef)
                and id(call) not in awaited
                and id(call) not in awaited_args
            ):
                continue
            inner_calls, _ = _direct_calls_and_nested_defs(
                list(ast.iter_child_nodes(nested_def))
            )
            creditable.update(id(inner) for inner in inner_calls)
    return creditable


def _analyze_source(fn: Any, source: str, label: str) -> tuple[list[str], bool]:
    """AST-scan one function's source for model fetches and guard CALLS.

    Fetch shapes (all matched on call nodes, so formatting across multiple
    lines is irrelevant — codex P2 on #863). ``select`` matches both the
    plain name and qualified forms like ``sa.select``; model classes are
    recognized in positional and keyword argument position, so
    ``db.get(entity=Dataset, ident=...)`` counts (codex P2, round 3):
    - ``select(<model or model attribute>, ...)`` / ``sa.select(...)``
    - ``<anything>.select_from(<model>)``
    - ``<anything>.get(<model>, ...)`` / ``.get_one(<model>, ...)``
      (AsyncSession.get / get_one, incl. keyword form)
    - ``get_dataset(...)`` / ``<module>.get_dataset(...)``

    Accessor calls count as fetches too: domain service accessors resolved
    by identity (``get_dataset`` / ``get_record`` / ``get_map`` /
    ``get_map_with_layers``, including function-local imports) and the
    matching method names on any receiver (``port.get_record(db, id)``)
    (codex P1, round 5).

    A guard counts only when it is actually INVOKED and the called name
    RESOLVES to a sanctioned guard object by identity (codex P2 on #863,
    rounds 2 and 5) — imports, docstrings, comments, shadowing local
    definitions, and same-named methods on unrelated objects do not count.
    The one non-identity path is a ``_PORT_GUARD_METHODS`` call on a
    provable ProcessingPort receiver. Value-returning guards
    (``_VALUE_GUARDS``) additionally require the call result to be
    CONSUMED — a bare expression statement discards the filtered Select and
    is not a guard (codex P1, round 3). Coroutine guards additionally
    require the call to be AWAITED — an un-awaited call only creates a
    coroutine and never runs the check (codex P1, round 4).
    """
    tree = _parse(source)
    if tree is None:
        return [], False
    ctx = _AnalysisContext(
        fn=fn,
        aliases=_model_aliases(fn, tree),
        select_names=_select_aliases(fn, tree),
        accessor_names=frozenset(_bound_names(fn, tree, _accessor_functions())),
        guard_bound=_bound_objects(fn, tree, tuple(_guard_objects().values())),
        port_names=frozenset(_port_base_names(tree)),
        discarded=frozenset(_discarded_call_ids(tree)),
        awaited=frozenset(_awaited_call_ids(tree)),
        creditable=frozenset(_guard_creditable_call_ids(tree)),
        assigned=_assigned_call_targets(tree),
        load_lines=_name_load_lines(tree),
    )
    lines = source.splitlines()
    evidence: list[str] = []
    guard_called = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_effective_guard(ctx, node):
            guard_called = True
        if _is_fetch(ctx, node):
            line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            evidence.append(f"{label}:{node.lineno}: {line}")

    return evidence, guard_called


class _AnalysisContext(NamedTuple):
    """Per-source resolution state shared by the call-node predicates."""

    fn: Any
    aliases: frozenset[str]
    select_names: frozenset[str]
    accessor_names: frozenset[str]
    guard_bound: dict[str, Any]
    port_names: frozenset[str]
    discarded: frozenset[int]
    awaited: frozenset[int]
    creditable: frozenset[int]  # calls on the execution path (guard scope)
    assigned: dict[int, tuple[frozenset[str], int]]  # call id -> (targets, end line)
    load_lines: dict[str, tuple[int, ...]]  # name -> Load line numbers


def _resolve_guard(ctx: _AnalysisContext, node: ast.Call) -> tuple[str, Any] | None:
    """(canonical name, guard object or None for port wrappers)."""
    guard_by_id = {id(obj): name for name, obj in _guard_objects().items()}
    func = node.func
    if isinstance(func, ast.Name):
        obj = ctx.guard_bound.get(func.id)
        return (guard_by_id[id(obj)], obj) if obj is not None else None
    if isinstance(func, ast.Attribute):
        obj = _attr_chain_object(ctx.fn, func)
        if obj is not None and id(obj) in guard_by_id:
            return guard_by_id[id(obj)], obj
        if func.attr in _PORT_GUARD_METHODS and _is_port_base(
            func.value, ctx.port_names
        ):
            return func.attr, None
    return None


def _is_effective_guard(ctx: _AnalysisContext, node: ast.Call) -> bool:
    if id(node) not in ctx.creditable:
        return False  # nested def/lambda that may never run (codex P2, round 7)
    resolved = _resolve_guard(ctx, node)
    if resolved is None:
        return False
    name, obj = resolved
    is_coro = (
        inspect.iscoroutinefunction(obj)
        if obj is not None
        else name in _guards_requiring_await()
    )
    if is_coro and id(node) not in ctx.awaited:
        return False  # un-awaited coroutine: the check never runs
    if name in _VALUE_GUARDS:
        if id(node) in ctx.discarded:
            return False  # filtered statement / id set discarded
        assigned = ctx.assigned.get(id(node))
        if assigned is not None:
            target_names, end_lineno = assigned
            if target_names and not any(
                line > end_lineno
                for target in target_names
                for line in ctx.load_lines.get(target, ())
            ):
                # ``filtered = apply_visibility_filter(stmt, ...)`` with
                # ``filtered`` never read again: the protection is inert
                # (codex P1, round 8). Bounded check — see the module
                # docstring's documented-limits entry on dataflow.
                return False
    return True


def _is_fetch(ctx: _AnalysisContext, node: ast.Call) -> bool:
    func = node.func
    called = func.id if isinstance(func, ast.Name) else None
    attr = func.attr if isinstance(func, ast.Attribute) else None
    name = called or attr

    def _any_model_arg(candidates: list[ast.expr]) -> bool:
        return any(_root_name(candidate) in ctx.aliases for candidate in candidates)

    keyword_values = [kw.value for kw in node.keywords]
    if name in _ACCESSOR_METHOD_NAMES or called in ctx.accessor_names:
        return True
    if name in ("select", "select_from") or called in ctx.select_names:
        return _any_model_arg([*node.args, *keyword_values])
    if attr in ("get", "get_one"):
        return _any_model_arg([*node.args[:1], *keyword_values])
    return False


def _called_names(tree: ast.Module) -> list[tuple[str, ...]]:
    """Plain and single-dotted names invoked as calls in the tree."""
    names: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append((func.id,))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                names.append((func.value.id, func.attr))
    return names


def _one_level_expansion(fn: Any, source: str) -> dict[str, tuple[Any, str, bool]]:
    """app.* plain functions called directly from the handler, with sources.

    Exactly one level deep, and only plain functions (classes and bound
    methods are skipped — expanding a class would pull every method of e.g.
    AdminService into scope and recreate the file-scope blind spot at class
    scope). Each helper is returned WITH its function object so it can be
    analyzed against its own module globals and local imports, plus a
    ``guard_creditable`` flag.

    Every helper call is expanded for FETCH evidence — a coroutine passed
    to ``await asyncio.gather(...)`` or ``create_task`` does execute, so
    skipping it would hide its fetches (codex P1, round 6; fail-closed).
    GUARD credit from a helper is asymmetric: it flows to the handler only
    when the helper provably executes at the call site — the call is
    directly awaited, a direct argument of an awaited call (the awaited
    ``asyncio.gather(helper())`` idiom), or the helper is a plain sync
    function. Without that restriction an un-awaited
    ``record = _check_record_ownership(...)`` would be credited with the
    helper's internal awaited guard call (the codex P1, round 4 hole).
    """
    tree = _parse(source)
    if tree is None:
        return {}
    awaited = _awaited_call_ids(tree)
    awaited_args = _awaited_argument_call_ids(tree)
    module_globals = getattr(fn, "__globals__", {})
    expansion: dict[str, tuple[Any, str, bool]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            parts: tuple[str, ...] = (func.id,)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            parts = (func.value.id, func.attr)
        else:
            continue
        obj = module_globals.get(parts[0])
        for attr in parts[1:]:
            obj = getattr(obj, attr, None) if obj is not None else None
        if obj is None:
            continue
        target = _unwrap(obj)
        if not inspect.isfunction(target):
            continue
        module = getattr(target, "__module__", "") or ""
        if not module.startswith("app."):
            continue
        creditable = (
            not inspect.iscoroutinefunction(target)
            or id(node) in awaited
            or id(node) in awaited_args
        )
        key = f"{module}.{target.__qualname__}"
        previous = expansion.get(key)
        if previous is None:
            expansion[key] = (target, _source_of(target), creditable)
        elif creditable and not previous[2]:
            expansion[key] = (previous[0], previous[1], True)
    return expansion


def _analyze_effective(fn: Any, source: str) -> tuple[list[str], bool]:
    """Handler analysis plus one-level helper expansion (the main-test view).

    Fetch evidence accumulates from the handler and every expanded helper;
    guard credit accumulates from the handler and only the helpers whose
    call sites provably execute (see ``_one_level_expansion``).
    """
    fetch_lines, guarded = _analyze_source(fn, source, "handler")
    for helper_key, (helper_fn, helper_source, creditable) in _one_level_expansion(
        fn, source
    ).items():
        helper_evidence, helper_guard = _analyze_source(
            helper_fn, helper_source, helper_key
        )
        fetch_lines.extend(helper_evidence)
        guarded = guarded or (helper_guard and creditable)
    return fetch_lines, guarded


@lru_cache(maxsize=1)
def _analyze_routes() -> tuple[int, tuple[_HandlerReport, ...]]:
    """Walk the flattened route table and analyze every unique handler.

    Returns (api_route_context_count, reports). Cached so the individual
    tests below share one walk. The app import stays function-local: importing
    it at module scope would run FastAPI app assembly during collection even
    when this file is deselected.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    context_count = 0
    reports: dict[str, _HandlerReport] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        context_count += 1
        fn = _unwrap(route.endpoint)
        key = f"{fn.__module__}.{fn.__qualname__}"
        if key in reports:
            # Dual-shape slash aliases (ROUTE-01) register the same endpoint
            # twice; analyze it once.
            continue
        source = _source_of(fn)
        fetch_lines, guarded = _analyze_effective(fn, source)
        reports[key] = _HandlerReport(
            key=key,
            path=ctx.path or route.path,
            methods=tuple(sorted(route.methods or ())),
            fetch_lines=tuple(fetch_lines),
            guarded=guarded,
        )
    return context_count, tuple(reports.values())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.architecture
def test_route_walk_sees_the_full_route_table() -> None:
    """The walk must see the flattened table, not the lazy top level.

    On fastapi 0.140 ``app.routes`` alone holds ~89 entries while the real
    table has ~430 APIRoute contexts (~260 unique handlers). If a future
    fastapi change makes iter_route_contexts stop flattening, this floor
    fails loudly instead of letting every assertion below pass vacuously.
    """
    context_count, reports = _analyze_routes()
    assert context_count > 200, (
        f"route walk saw only {context_count} APIRoute contexts — expected the "
        "flattened table (>200). fastapi's lazy include_router behavior has "
        "likely changed; fix the walk before trusting any test in this module."
    )
    assert len(reports) > 150, (
        f"route walk resolved only {len(reports)} unique handlers (expected >150)"
    )


@pytest.mark.architecture
def test_fetch_and_guard_detection_are_alive() -> None:
    """Detection self-check: the patterns must still match real code.

    If a refactor renames the guard helpers or the fetch idioms drift, the
    main test below could pass vacuously (nothing flagged because nothing
    matched). Pin a floor for guarded fetching handlers and anchor two
    reference implementations from AGENTS.md Rule 1.
    """
    _, reports = _analyze_routes()
    guarded = [r for r in reports if r.fetch_lines and r.guarded]
    assert len(guarded) >= 60, (
        f"only {len(guarded)} handlers matched fetch+guard patterns (expected "
        ">=60). Either the fetch detection or the guard list no longer matches "
        "the codebase — update _analyze_source / guard names in this module."
    )
    guarded_modules = {r.key.rsplit(".", 1)[0] for r in guarded}
    for anchor in ("app.standards.ogc.router", "app.standards.stac.router"):
        assert anchor in guarded_modules, (
            f"reference implementation {anchor} (AGENTS.md Rule 1) no longer "
            "shows up as a guarded model-fetching module — detection is broken."
        )


@pytest.mark.architecture
def test_every_model_fetching_handler_is_guarded_or_allowlisted() -> None:
    """AGENTS.md Rule 1, enforced per handler across the whole route table.

    A handler whose effective source (own body + one level of directly-called
    app.* helpers) fetches Record/Dataset/Map/RecordEmbedding/IngestJob must
    CALL one
    of the sanctioned guards. Anything else must be a reviewed ALLOWLIST
    entry — and the allowlist must stay exact, so guarded-later or renamed
    handlers cannot leave stale entries behind.
    """
    _, reports = _analyze_routes()
    unguarded = {r.key: r for r in reports if r.fetch_lines and not r.guarded}

    missing = sorted(set(unguarded) - set(ALLOWLIST))
    if missing:
        details = []
        for key in missing:
            report = unguarded[key]
            evidence = "\n".join(f"      {line}" for line in report.fetch_lines[:5])
            details.append(
                f"  {' '.join(report.methods)} {report.path}\n    {key}\n{evidence}"
            )
        pytest.fail(
            "Rule 1 violation: route handler(s) fetch a guarded model "
            "(Record/Dataset/Map/RecordEmbedding/IngestJob) without a "
            "sanctioned access "
            "check. Add check_dataset_access_or_anonymous / "
            "check_dataset_access / check_dataset_write_access / "
            "apply_visibility_filter (or the maps/records domain guards) to "
            "the handler, or — only for endpoints unguarded by design — add "
            "an ALLOWLIST entry in this file with a one-line justification. "
            "See AGENTS.md, Security pre-commit checklist Rule 1.\n"
            + "\n".join(details)
        )

    stale = sorted(set(ALLOWLIST) - set(unguarded))
    assert not stale, (
        "Stale ALLOWLIST entries — these handlers are now guarded, renamed, "
        "or gone. Remove them from ALLOWLIST in this file so the list stays "
        "exact:\n" + "\n".join(f"  {key}: {ALLOWLIST[key]}" for key in stale)
    )


@lru_cache(maxsize=1)
def _disclosure_deciders() -> tuple[Any, ...]:
    """The two predicates that settle how much of a run's record a caller sees.

    ``_can_access_another_users_job`` is the owner-or-policy answer: the
    caller gets the whole row or a 403. ``can_view_dataset_provenance`` is
    the graded answer ``list_dataset_refresh_runs`` uses: the full payload
    for the dataset's owner or an admin, a redacted one for everybody else.
    Either is a decision. Neither being present is the defect.
    """
    from app.modules.catalog.authorization import can_view_dataset_provenance
    from app.platform.jobs.router import _can_access_another_users_job

    return (_can_access_another_users_job, can_view_dataset_provenance)


# The three field names the provenance projection already decided are not for
# a reader who merely passed a visibility check. ``DatasetRefreshRunResponse``
# nulls all three, and its schema docstring is the rationale: a public
# dataset's history otherwise enumerates who edits it, and failure text leaks
# internal origin detail.
#
# ``source_filename`` is deliberately NOT here. ``dataset_to_response`` and
# ``list_dataset_versions`` publish it to the same audience on purpose, so a
# gate demanding a predicate wherever it appears would be asserting a rule the
# codebase has decided against. ``_redacted_job_status`` is stricter than those
# two siblings for a reason its own docstring gives, which is a local choice
# rather than a tree-wide one.
_PROVENANCE_DETAIL_FIELDS = frozenset({"error_message", "triggered_by", "error_code"})

# Routes that publish a provenance-detail field with no per-caller predicate,
# each unguarded BY DESIGN. Same exactness discipline as ALLOWLIST above.
PROVENANCE_ALLOWLIST: dict[str, str] = {
    # The operator's cross-user job console. Gated by a route-level
    # require_permission("manage_users") dependency rather than a call in the
    # handler body, and its whole purpose is the fleet-wide view: it filters by
    # user_id and searches across owners.
    "app.modules.admin.router.list_admin_jobs": (
        "manage_users-gated operator console; the cross-user view is the feature"
    ),
}


def _response_models(annotation: Any, depth: int = 0, seen: set[Any] | None = None):
    """Every pydantic model reachable from a response annotation.

    Walks into ``list[...]``, ``X | None`` and nested model fields, so a field
    on an ITEM model counts for the route that returns a list of them. Depth
    capped and cycle-guarded; a model graph deeper than that does not occur
    here and would be worth flattening if it did.
    """
    from pydantic import BaseModel

    if seen is None:
        seen = set()
    if depth > 3:
        return
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        yield annotation
        for field in annotation.model_fields.values():
            yield from _response_models(field.annotation, depth + 1, seen)
        return
    for arg in typing.get_args(annotation) or ():
        yield from _response_models(arg, depth + 1, seen)


@pytest.mark.architecture
def test_every_provenance_detail_route_decides_who_sees_it() -> None:
    """A run's failure text and the id of who triggered it are not visibility.

    fix(#1860): Rule 1 above cannot see this class. It asks whether a handler
    checked access at all, and both handlers this test was written for did:
    they filtered the DATASET and then served every field of the run to
    whoever that let in. Two sibling doors onto the same fields had already
    decided the question the other way, and the ones that had not were still
    credited as guarded.

    So this test asks the narrower question directly, keyed on the RESPONSE
    FIELDS rather than on a response model, because keying on the model is
    what let the second door hide behind a different one. Any route whose
    response model, or any model nested inside it, declares one of
    ``_PROVENANCE_DETAIL_FIELDS`` must invoke one of the two disclosure
    predicates. Resolution is by object identity through the handler's module
    globals and its function-local imports, the same way guard credit works
    above, so a same-named local helper earns nothing.

    Like the Rule 1 gate, this credits a call that is merely PRESENT rather
    than proving it reached the response. That is the same approximation, not
    a new one, and it is fail-loud in the direction that matters: adding a
    field to a response model is what puts a route in scope.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    scoped: dict[str, tuple[str, str, frozenset[str]]] = {}
    undecided: dict[str, tuple[str, str, frozenset[str]]] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        hits: set[str] = set()
        for model in _response_models(route.response_model):
            hits |= set(model.model_fields) & _PROVENANCE_DETAIL_FIELDS
        if not hits:
            continue
        fn = _unwrap(route.endpoint)
        key = f"{fn.__module__}.{fn.__qualname__}"
        if key in scoped:  # dual-shape slash aliases register one handler twice
            continue
        methods = " ".join(sorted(route.methods or ()))
        entry = (methods, ctx.path or route.path, frozenset(hits))
        scoped[key] = entry
        tree = _parse(_source_of(fn))
        decided = False
        if tree is not None:
            called = {parts[0] for parts in _called_names(tree) if len(parts) == 1}
            decided = bool(called & _bound_names(fn, tree, _disclosure_deciders()))
        if not decided:
            undecided[key] = entry

    assert len(scoped) >= 5, (
        f"only {len(scoped)} routes publish a provenance-detail field (expected "
        ">= 5). The response models or the route walk changed; fix this test "
        "before trusting it, because an empty walk passes vacuously."
    )

    missing = sorted(set(undecided) - set(PROVENANCE_ALLOWLIST))
    if missing:
        details = []
        for key in missing:
            methods, path, hits = undecided[key]
            details.append(
                f"  {methods} {path}\n    {key}\n      publishes {sorted(hits)}"
            )
        pytest.fail(
            "Route(s) publish a run's failure text or the id of whoever "
            "triggered it without deciding who is reading. Call "
            "can_view_dataset_provenance (graded: full payload for the "
            "dataset's owner or an admin, a redacted projection for every "
            "other reader) or _can_access_another_users_job (owner-or-policy, "
            "403 on denial). A dataset-visibility check alone is not an "
            "answer: it admits any signed-in reader of a published public or "
            "internal dataset. Only for routes unguarded by design, add a "
            "PROVENANCE_ALLOWLIST entry in this file with a one-line "
            "justification.\n" + "\n".join(details)
        )

    stale = sorted(set(PROVENANCE_ALLOWLIST) - set(undecided))
    assert not stale, (
        "Stale PROVENANCE_ALLOWLIST entries — these routes now decide, were "
        "renamed, or no longer publish a provenance-detail field. Remove them "
        "so the list stays exact:\n"
        + "\n".join(f"  {key}: {PROVENANCE_ALLOWLIST[key]}" for key in stale)
    )


@pytest.mark.architecture
def test_detection_self_checks_on_synthetic_sources() -> None:
    """Pin the detection semantics codex review probed on #863.

    Each snippet resolves ``Dataset`` through a function-local aliased
    import, exactly like the runtime code paths do. The dummy function only
    supplies module context; the snippets are never executed.
    """

    def _dummy() -> None:  # pragma: no cover - never called
        return None

    imp = "from app.modules.catalog.datasets.domain.models import Dataset as DsX\n"
    # Function-local imports of the REAL guards: guard credit requires the
    # called name to resolve to the sanctioned object by identity, and the
    # dummy function's module globals do not bind the guards.
    imp_access = "from app.modules.catalog.authorization import check_dataset_access\n"
    imp_avf = "from app.modules.catalog.authorization import apply_visibility_filter\n"
    imp_bulk = "from app.modules.catalog.maps.service_layers import bulk_check_dataset_access\n"

    # Qualified select: sa.select(Model) is a fetch (codex P2, round 3).
    evidence, guarded = _analyze_source(
        _dummy, imp + "def f(db):\n    return db.execute(sa.select(DsX))\n", "t"
    )
    assert evidence and not guarded, "sa.select(Model) must be detected as a fetch"

    # Keyword get: db.get(entity=Model, ident=...) is a fetch (codex P2, round 3).
    evidence, guarded = _analyze_source(
        _dummy, imp + "def f(db, i):\n    return db.get(entity=DsX, ident=i)\n", "t"
    )
    assert evidence and not guarded, "db.get(entity=Model) must be detected as a fetch"

    # AsyncSession.get_one is the same fetch shape (codex P1, round 6).
    evidence, guarded = _analyze_source(
        _dummy, imp + "async def f(db, i):\n    return await db.get_one(DsX, i)\n", "t"
    )
    assert evidence and not guarded, (
        "db.get_one(Model, ...) must be detected as a fetch"
    )

    # A bare value-guard statement discards the filtered Select and is NOT a
    # guard (codex P1, round 3)...
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_avf
        + "def f(db, u, r):\n"
        + "    stmt = select(DsX)\n"
        + "    apply_visibility_filter(stmt, u, r, DsX, None)\n"
        + "    return db.execute(stmt)\n",
        "t",
    )
    assert evidence and not guarded, (
        "a bare apply_visibility_filter(...) statement discards the filtered "
        "statement and must NOT count as a guard"
    )

    # ...while consuming the result IS a guard (sync guard, no await needed).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_avf
        + "def f(db, u, r):\n"
        + "    stmt = apply_visibility_filter(select(DsX), u, r, DsX, None)\n"
        + "    return db.execute(stmt)\n",
        "t",
    )
    assert evidence and guarded, (
        "an assigned-and-then-executed apply_visibility_filter(...) result "
        "must count as a guard"
    )

    # Direct pass-through is also consumption.
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_avf
        + "def f(db, u, r):\n"
        + "    return db.execute(apply_visibility_filter(select(DsX), u, r, DsX))\n",
        "t",
    )
    assert evidence and guarded, (
        "db.execute(apply_visibility_filter(...)) must count as a guard"
    )

    # Assigning the filtered statement to a name that is NEVER read again
    # leaves the protection inert — the raw statement is what gets executed
    # (codex P1, round 8).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_avf
        + "def f(db, u, r):\n"
        + "    stmt = select(DsX)\n"
        + "    filtered = apply_visibility_filter(stmt, u, r, DsX, None)\n"
        + "    return db.execute(stmt)\n",
        "t",
    )
    assert evidence and not guarded, (
        "an assigned-but-never-reloaded apply_visibility_filter(...) result "
        "must NOT count as a guard"
    )

    # Raising guards may be bare statements — that is their correct usage —
    # but they MUST be awaited (all raising guards are coroutine functions).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    await check_dataset_access(db, ds, i, u)\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and guarded, (
        "a bare await check_dataset_access(...) must count as a guard"
    )

    # An UN-AWAITED coroutine guard only creates a coroutine — the check
    # never runs, so it must not count (codex P1, round 4).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    check_dataset_access(db, ds, i, u)\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and not guarded, (
        "an un-awaited check_dataset_access(...) never runs and must NOT "
        "count as a guard"
    )

    # Same for a coroutine value guard: assigning the coroutine (no await)
    # consumes an object that never executed the check.
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_bulk
        + "async def f(db, ids, u, r):\n"
        + "    ok = bulk_check_dataset_access(db, ids, u, r)\n"
        + "    return await db.get(DsX, ids[0]), ok\n",
        "t",
    )
    assert evidence and not guarded, (
        "an un-awaited bulk_check_dataset_access(...) must NOT count as a guard"
    )

    # Aliased select import: the fetch is still detected by callable identity.
    evidence, guarded = _analyze_source(
        _dummy,
        "from sqlalchemy import select as sel\n"
        + imp
        + "def f(db):\n    return db.execute(sel(DsX))\n",
        "t",
    )
    assert evidence and not guarded, (
        "select imported under an alias must still be detected as a fetch"
    )

    # A SHADOWED guard name — locally defined, never imported — must not
    # count: guard credit requires identity resolution (codex P2, round 5).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + "async def check_dataset_access(db, ds, i, u):\n"
        + "    return None\n"
        + "async def f(db, ds, i, u):\n"
        + "    await check_dataset_access(db, ds, i, u)\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and not guarded, (
        "a locally shadowed check_dataset_access(...) has no relationship to "
        "the authorization module and must NOT count as a guard"
    )

    # ProcessingPort accessor: port.get_record(db, id) is a fetch even
    # though the receiver is a local (codex P1, round 5).
    evidence, guarded = _analyze_source(
        _dummy,
        'async def f(db, i, port: "ProcessingPort"):\n'
        + "    return await port.get_record(db, i)\n",
        "t",
    )
    assert evidence and not guarded, "port.get_record(...) must be detected as a fetch"

    # ProcessingPort guard wrapper: credited only on a provable port
    # receiver (annotated parameter / get_processing_port() result).
    evidence, guarded = _analyze_source(
        _dummy,
        'async def f(db, i, u, port: "ProcessingPort"):\n'
        + "    ds = await port.get_dataset(db, i)\n"
        + "    await port.check_dataset_access(db, ds, i, u)\n"
        + "    return ds\n",
        "t",
    )
    assert evidence and guarded, (
        "await port.check_dataset_access(...) on a ProcessingPort-annotated "
        "parameter must count as a guard"
    )

    # The same method name on an unrelated receiver must NOT count.
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + "async def f(db, i, u, svc):\n"
        + "    ds = await db.get(DsX, i)\n"
        + "    await svc.check_dataset_access(db, ds, i, u)\n"
        + "    return ds\n",
        "t",
    )
    assert evidence and not guarded, (
        "svc.check_dataset_access(...) on an unproven receiver must NOT "
        "count as a guard"
    )

    # Function-locally imported service accessor: a fetch by identity.
    evidence, guarded = _analyze_source(
        _dummy,
        "from app.modules.catalog.records.service import get_record as load\n"
        + "async def f(db, i):\n"
        + "    return await load(db, i)\n",
        "t",
    )
    assert evidence and not guarded, (
        "a function-locally imported (and aliased) get_record must be "
        "detected as a fetch"
    )

    # A guard inside a nested def the handler NEVER invokes must not credit
    # the handler — the callback may never run (codex P2, round 7).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    async def _maybe_later():\n"
        + "        await check_dataset_access(db, ds, i, u)\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and not guarded, (
        "a guard inside an uninvoked nested def must NOT count"
    )

    # A guard inside a nested def that the outer body DOES invoke counts —
    # the list_maps closure pattern (sync closure, result consumed).
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_avf
        + "def f(db, u, r):\n"
        + "    def _vis(stmt):\n"
        + "        return apply_visibility_filter(stmt, u, r, DsX, None)\n"
        + "    stmt = _vis(select(DsX))\n"
        + "    return db.execute(stmt)\n",
        "t",
    )
    assert evidence and guarded, (
        "a guard inside a nested closure invoked by the outer body must count"
    )

    # Same for an async nested def, but only when its invocation is awaited.
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    async def _check():\n"
        + "        await check_dataset_access(db, ds, i, u)\n"
        + "    await _check()\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and guarded, "a guard inside an awaited async nested def must count"
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    async def _check():\n"
        + "        await check_dataset_access(db, ds, i, u)\n"
        + "    _check()\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and not guarded, (
        "a guard inside an async nested def invoked WITHOUT await must NOT count"
    )

    # The STAC idiom: a nested async def invoked as a direct argument of an
    # awaited gather provably runs, so its guard counts.
    evidence, guarded = _analyze_source(
        _dummy,
        imp
        + imp_access
        + "async def f(db, ds, i, u):\n"
        + "    async def _check():\n"
        + "        await check_dataset_access(db, ds, i, u)\n"
        + "    await asyncio.gather(_check())\n"
        + "    return await db.get(DsX, i)\n",
        "t",
    )
    assert evidence and guarded, (
        "a guard inside a nested async def run via an awaited gather must count"
    )


@pytest.mark.architecture
def test_expansion_semantics_on_synthetic_sources() -> None:
    """Pin the helper-expansion semantics (codex P1 rounds 4 and 6).

    Dummy functions are built with controlled globals binding REAL app
    helpers, because expansion only follows ``app.*`` functions. The
    snippets are never executed.
    """
    import types

    from app.standards.ogc import router as ogc_router

    def _dummy_with(ns: dict[str, Any]) -> Any:
        return types.FunctionType((lambda: None).__code__, ns)

    # A helper scheduled through an AWAITED asyncio.gather provably
    # executes — its fetches must be visible and its internal (consumed)
    # guard is credited (codex P1 round 6 + P2 round 7).
    # _get_visible_dataset selects Dataset and applies the filter inside.
    fn = _dummy_with({"gather_helper": ogc_router._get_visible_dataset})
    evidence, guarded = _analyze_effective(
        fn,
        "async def f(db, u, i):\n"
        "    import asyncio\n"
        "    await asyncio.gather(gather_helper(db, u, i))\n",
    )
    assert evidence, "a gather-scheduled helper's model fetch must be detected"
    assert guarded, (
        "a helper inside an AWAITED gather provably executes and must "
        "contribute its guard credit"
    )

    # A coroutine merely handed to create_task (outer call not awaited) is
    # not provably run: fetch stays visible, guard credit does not flow.
    fn = _dummy_with({"task_helper": ogc_router._get_visible_dataset})
    evidence, guarded = _analyze_effective(
        fn,
        "async def f(db, u, i, tg):\n"
        "    t = tg.create_task(task_helper(db, u, i))\n"
        "    return t\n",
    )
    assert evidence and not guarded, (
        "a create_task-scheduled helper without an awaited outer call must "
        "contribute fetch evidence but no guard credit"
    )

    # Directly awaited helper: fetches AND its internal (consumed)
    # apply_visibility_filter guard both flow to the handler.
    fn = _dummy_with({"load_visible": ogc_router._get_visible_dataset})
    evidence, guarded = _analyze_effective(
        fn,
        "async def f(db, u, i):\n    return await load_visible(db, u, i)\n",
    )
    assert evidence and guarded, (
        "an awaited helper must contribute both its fetches and its guards"
    )

    # Round-4 pin at composition level: an un-awaited (assigned) coroutine
    # helper never runs, so its internal guard must NOT be credited — while
    # its fetch stays visible (fail-closed).
    fn = _dummy_with({"load_visible": ogc_router._get_visible_dataset})
    evidence, guarded = _analyze_effective(
        fn,
        "async def f(db, u, i):\n    ds = load_visible(db, u, i)\n    return ds\n",
    )
    assert evidence and not guarded, (
        "an un-awaited helper must contribute fetch evidence but no guard credit"
    )


@pytest.mark.architecture
def test_delegated_guards_still_enforce_access() -> None:
    """The sanctioned domain guard helpers must keep delegating/enforcing.

    Recognizing a helper name as a guard is only sound while the helper still
    performs (or delegates to) a real access check. Pin the delegation chain
    so hollowing out a helper fails here rather than silently weakening the
    main test.
    """
    from app.modules.catalog.maps import _router_helpers, service_crud, service_shared
    from app.modules.catalog.records import router as records_router

    def _calls_in(fn: Any) -> set[str]:
        tree = _parse(_source_of(fn))
        return {name[-1] for name in _called_names(tree)} if tree is not None else set()

    assert "check_dataset_access_or_anonymous" in _calls_in(
        records_router._check_record_read_access
    ), (
        "records _check_record_read_access no longer calls "
        "check_dataset_access_or_anonymous"
    )
    assert "_check_record_read_access" in _calls_in(
        records_router._check_record_ownership
    ), "records _check_record_ownership no longer calls _check_record_read_access"

    map_read = _source_of(_router_helpers._check_map_read_access)
    assert "visibility" in map_read and "404" in map_read, (
        "maps _check_map_read_access no longer enforces visibility with a 404"
    )
    map_own = _source_of(service_crud.check_map_ownership)
    assert "created_by" in map_own and "admin" in map_own, (
        "maps check_map_ownership no longer enforces owner-or-admin"
    )
    map_filter = _source_of(service_shared._apply_map_visibility_filter)
    assert "visibility" in map_filter and "created_by" in map_filter, (
        "maps _apply_map_visibility_filter no longer filters by visibility/ownership"
    )

    from app.modules.catalog.maps import service_layers
    from app.processing.tiles import router as tiles_router

    # fix(#929 review): the bulk check delegates to the permission extension
    # via apply_visibility_filter instead of inlining a policy mirror, so an
    # overlay that replaces the extension governs the map-attach paths too.
    bulk_calls = _calls_in(service_layers.bulk_check_dataset_access)
    assert "apply_visibility_filter" in bulk_calls, (
        "maps bulk_check_dataset_access no longer delegates to apply_visibility_filter"
    )
    bulk = _source_of(service_layers.bulk_check_dataset_access)
    assert "DatasetGrant" in bulk, (
        "maps bulk_check_dataset_access no longer passes DatasetGrant, so "
        "restricted grants would stop resolving"
    )

    tile_auth_calls = _calls_in(tiles_router._authorize_vector_tile_request)
    assert {
        "verify_tile_signature",
        "validate_embed_token_access",
    } <= tile_auth_calls, (
        "tiles _authorize_vector_tile_request no longer verifies tile "
        "signatures / embed tokens"
    )
    tile_auth = _source_of(tiles_router._authorize_vector_tile_request)
    assert "visibility" in tile_auth and "403" in tile_auth, (
        "tiles _authorize_vector_tile_request no longer gates non-public "
        "datasets with a 403"
    )

    token_gate_calls = _calls_in(tiles_router._enforce_tile_token_access)
    assert "check_dataset_access" in token_gate_calls, (
        "tiles _enforce_tile_token_access no longer delegates non-public "
        "datasets to check_dataset_access"
    )
    token_gate = _source_of(tiles_router._enforce_tile_token_access)
    assert "visibility" in token_gate and "record_status" in token_gate, (
        "tiles _enforce_tile_token_access no longer gates on visibility and "
        "published status"
    )

    # ProcessingPort guard wrappers are credited by method name on provable
    # port receivers, so the default implementation must keep delegating to
    # the real authorization functions (codex P2, round 5).
    from app.platform.extensions.defaults import DefaultProcessingPort

    for method_name in sorted(_PORT_GUARD_METHODS):
        method = getattr(DefaultProcessingPort, method_name)
        method_source = _source_of(method)
        assert method_name in _calls_in(method), (
            f"DefaultProcessingPort.{method_name} no longer calls the "
            f"authorization-module {method_name}"
        )
        assert "from app.modules.catalog.authorization import" in method_source, (
            f"DefaultProcessingPort.{method_name} no longer imports its "
            "delegate from app.modules.catalog.authorization"
        )
