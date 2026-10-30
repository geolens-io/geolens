"""Every route an embed token can authorize keeps to the column allowlist.

A handler that reaches embed-token authorization, directly or through any
function it calls, must also reach ``readable_columns``. Calls resolve by
function name across ``backend/app``, so a shared name can over-credit; the
module backstop below catches a new wrapper module either way.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

APP = Path(__file__).resolve().parents[1] / "app"
_ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}
_EMBED_NAMES = {
    "validate_embed_token_access",
    "resolve_embed_scope_for_map",
    "get_map_embed_scope",
    "EmbedToken",
}
# A string, or a parameter name as FastAPI's Header() converts it.
_EMBED_HEADER = "x-embed-token"

# Shrink-only: handlers that reach embed authorization without reading columns
# through readable_columns.
EXEMPT_HANDLERS = {
    ("processing/tiles/router.py", "tile_endpoint"): (
        "vector tiles apply tile_columns to every caller"
    ),
    ("processing/tiles/router.py", "cluster_tile_endpoint"): (
        "cluster tiles apply tile_columns to every caller"
    ),
    ("processing/tiles/router.py", "raster_tile_proxy"): "raster pixels, no columns",
    ("processing/tiles/router.py", "raster_auth_check"): "raster pixels, no columns",
    ("processing/tiles/router.py", "get_tile_tokens_batch"): "signed URLs only",
    ("modules/embed_tokens/admin_router.py", "bulk_revoke"): "revokes tokens",
    ("modules/embed_tokens/public_router.py", "embed_frame_policy"): (
        "returns a frame policy, no dataset reads"
    ),
}

# Shrink-only: functions that create, list, update, revoke or count tokens and
# authorize no read, so reaching one does not make a handler embed-authorized.
TOKEN_LIFECYCLE = {
    "_bump_embed_token_usage",
    "active_embed_count_subquery",
    "bulk_revoke_embed_tokens",
    "create_embed_token",
    "get_active_allowed_origins",
    "get_active_embed_token",
    "list_admin_embed_tokens",
    "list_embed_tokens",
    "revoke_embed_token",
    "revoke_embed_tokens_by_map",
    "revoke_embed_tokens_for_dropped_datasets",
    "revoke_share_token_with_cascade",
    "update_embed_token",
}

# Shrink-only: modules that name embed-token authorization or its header.
EMBED_MODULES = {
    "api/main.py",
    "api/middleware/cors.py",
    "modules/admin/service.py",
    "modules/catalog/datasets/api/router_aggregate.py",
    "modules/catalog/features/router.py",
    "modules/catalog/maps/router_sharing.py",
    "modules/catalog/maps/schemas.py",
    "modules/catalog/maps/service_public.py",
    "modules/catalog/maps/sharing.py",
    "modules/embed_tokens/admin_router.py",
    "modules/embed_tokens/models.py",
    "modules/embed_tokens/public_router.py",
    "modules/embed_tokens/router.py",
    "modules/embed_tokens/schemas.py",
    "modules/embed_tokens/service.py",
    "modules/embed_tokens/sharing.py",
    "platform/cache/redis.py",
    "processing/tiles/responses.py",
    "processing/tiles/router.py",
    "standards/ogc/errors.py",
}


class _Used(NamedTuple):
    names: set[str]
    strings: set[str]
    calls: set[str]


def _used(node: ast.AST) -> _Used:
    used = _Used(set(), set(), set())
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.names.add(child.id)
        elif isinstance(child, ast.Attribute):
            used.names.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            used.strings.add(child.value.lower())
        elif isinstance(child, ast.arg):
            used.strings.add(child.arg.lower().replace("_", "-"))
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                used.calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                used.calls.add(func.attr)
    return used


def _merge(into: _Used, other: _Used) -> None:
    into.names.update(other.names)
    into.strings.update(other.strings)
    into.calls.update(other.calls)


def _router_dependencies(tree: ast.Module) -> _Used:
    """What the module's ``APIRouter(dependencies=[...])`` calls name."""
    used = _Used(set(), set(), set())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "APIRouter"
        ):
            for keyword in node.keywords:
                if keyword.arg == "dependencies":
                    _merge(used, _used(keyword.value))
    return used


def _is_route(node: ast.AST) -> bool:
    return any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr in _ROUTE_VERBS
        for d in node.decorator_list
    )


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, _Used], list[tuple[str, str, _Used]]]:
    """What each function name uses, and each route handler with what it uses.

    A handler's decorators, parameters and defaults are part of its node, so
    route ``dependencies=`` and ``Depends``/``Header`` parameters count.
    """
    functions: dict[str, _Used] = {}
    handlers: list[tuple[str, str, _Used]] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        router_deps = _router_dependencies(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            used = _used(node)
            _merge(functions.setdefault(node.name, _Used(set(), set(), set())), used)
            if _is_route(node):
                _merge(used, router_deps)
                handlers.append((rel, node.name, used))
    return functions, handlers


def _embed_authorized(used: _Used) -> bool:
    return bool(used.names & _EMBED_NAMES) or _EMBED_HEADER in used.strings


def _narrowed(used: _Used) -> bool:
    return "readable_columns" in used.calls


@lru_cache(maxsize=2)
def _reaching(predicate, edge: str) -> frozenset[str]:
    """Function names that satisfy ``predicate`` or use one that does.

    ``edge`` picks what counts as use: any reference, or only a call.
    """
    functions, _ = _index()
    stop = TOKEN_LIFECYCLE if predicate is _embed_authorized else set()
    found = {
        name for name, used in functions.items() if name not in stop and predicate(used)
    }
    while True:
        more = {
            name
            for name, used in functions.items()
            if name not in found and name not in stop and getattr(used, edge) & found
        }
        if not more:
            return frozenset(found)
        found |= more


def _reaches_embed(used: _Used) -> bool:
    return _embed_authorized(used) or bool(
        used.calls & _reaching(_embed_authorized, "calls")
    )


def _reaches_narrowing(used: _Used) -> bool:
    return _narrowed(used) or bool(used.calls & _reaching(_narrowed, "calls"))


def _embed_handlers() -> dict[tuple[str, str], _Used]:
    _, handlers = _index()
    return {(rel, name): used for rel, name, used in handlers if _reaches_embed(used)}


def test_embed_authorized_handlers_read_through_readable_columns() -> None:
    missing = sorted(
        f"{rel}::{name}"
        for (rel, name), used in _embed_handlers().items()
        if (rel, name) not in EXEMPT_HANDLERS and not _reaches_narrowing(used)
    )
    assert not missing, (
        "These handlers accept an embed token but never reach readable_columns, "
        "so an embed caller could read columns outside the dataset's "
        f"tile_columns allowlist: {missing}"
    )


def test_exemptions_are_still_needed() -> None:
    functions, _ = _index()
    stale = sorted(set(EXEMPT_HANDLERS) - set(_embed_handlers()))
    stale += sorted(
        name
        for name in TOKEN_LIFECYCLE
        if name not in functions or not _embed_authorized(functions[name])
    )
    assert not stale, f"Remove these stale exemptions: {stale}"


def test_only_known_modules_name_embed_authorization() -> None:
    mentions = set()
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if (
            _EMBED_HEADER in lowered
            or _EMBED_HEADER.replace("-", "_") in lowered
            or any(name in text for name in _EMBED_NAMES)
        ):
            mentions.add(path.relative_to(APP).as_posix())

    assert mentions == EMBED_MODULES, (
        "A module that names embed-token authorization must be reviewed for "
        "the column allowlist; update EMBED_MODULES after checking "
        f"new={sorted(mentions - EMBED_MODULES)} "
        f"gone={sorted(EMBED_MODULES - mentions)}"
    )
