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
table, inspects each handler's source (plus one level of directly-called
``app.*`` helper functions), and asserts that any handler whose effective
source fetches a guarded model (``Record``, ``Dataset``, ``Map``,
``RecordEmbedding``) also references one of the sanctioned guards. Handlers
that are unguarded by design live in ``ALLOWLIST`` with a per-entry
justification; the allowlist is asserted exact in both directions so entries
cannot go stale.

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
- A guard reference anywhere in the effective source satisfies the check.
  That is handler-scoped (much tighter than the hook's file scope) but a
  handler doing two fetches, one guarded and one not, would still pass.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from functools import lru_cache
from typing import Any, NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Fetch shapes for the four guarded models. ``select(Model`` also matches
# column selects like ``select(Map.id, ...)`` via the word boundary.
_FETCH_RE = re.compile(
    r"\bget_dataset\("
    r"|\b(?:db|session)\.get\(\s*(?:Dataset|Record|Map|RecordEmbedding)\b"
    r"|\bselect\(\s*(?:Dataset|Record|Map|RecordEmbedding)\b"
)

# Core guards from app/modules/catalog/authorization.py (AGENTS.md Rule 1).
_CORE_GUARDS = (
    "check_dataset_access_or_anonymous",
    "check_dataset_access",
    "check_dataset_write_access",
    "apply_visibility_filter",
)

# Domain guard helpers that wrap the core checks (or implement the
# equivalent RBAC logic for their model). Their integrity is pinned by
# test_delegated_guards_still_enforce_access below.
_DELEGATED_GUARDS = (
    # maps: app/modules/catalog/maps/{_router_helpers,service_crud,service_shared}.py
    "check_map_ownership",
    "_check_map_read_access",
    "_apply_map_visibility_filter",
    # records: app/modules/catalog/records/router.py
    "_check_record_read_access",
    "_check_record_ownership",
)

_GUARD_RE = re.compile("|".join(re.escape(g) for g in _CORE_GUARDS + _DELEGATED_GUARDS))

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


def _called_names(source: str) -> list[tuple[str, ...]]:
    """Plain and single-dotted names invoked as calls in the source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append((func.id,))
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                names.append((func.value.id, func.attr))
    return names


def _one_level_expansion(fn: Any, source: str) -> dict[str, str]:
    """Sources of app.* plain functions called directly from the handler.

    Exactly one level deep, and only plain functions (classes and bound
    methods are skipped — expanding a class would pull every method of e.g.
    AdminService into scope and recreate the file-scope blind spot at class
    scope).
    """
    module_globals = getattr(fn, "__globals__", {})
    expansion: dict[str, str] = {}
    for parts in _called_names(source):
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
        key = f"{module}.{target.__qualname__}"
        if key not in expansion:
            expansion[key] = _source_of(target)
    return expansion


def _fetch_evidence(label: str, source: str) -> list[str]:
    return [
        f"{label}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(source.splitlines(), start=1)
        if _FETCH_RE.search(line)
    ]


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
        expansion = _one_level_expansion(fn, source)
        fetch_lines: list[str] = _fetch_evidence("handler", source)
        for helper_key, helper_source in expansion.items():
            fetch_lines.extend(_fetch_evidence(helper_key, helper_source))
        effective = "\n".join([source, *expansion.values()])
        reports[key] = _HandlerReport(
            key=key,
            path=ctx.path or route.path,
            methods=tuple(sorted(route.methods or ())),
            fetch_lines=tuple(fetch_lines),
            guarded=bool(_GUARD_RE.search(effective)),
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
        ">=60). Either the fetch regex or the guard list no longer matches the "
        "codebase — update _FETCH_RE / guard names in this module."
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
    app.* helpers) fetches Record/Dataset/Map/RecordEmbedding must reference
    one of the sanctioned guards. Anything else must be a reviewed ALLOWLIST
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
            "(Record/Dataset/Map/RecordEmbedding) without a sanctioned access "
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

    read_access = _source_of(records_router._check_record_read_access)
    assert "check_dataset_access_or_anonymous" in read_access, (
        "records _check_record_read_access no longer delegates to "
        "check_dataset_access_or_anonymous"
    )
    ownership = _source_of(records_router._check_record_ownership)
    assert "_check_record_read_access" in ownership, (
        "records _check_record_ownership no longer calls _check_record_read_access"
    )

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
