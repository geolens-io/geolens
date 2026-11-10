"""No export route accepts or resolves an embed token, directly or through what it uses."""

from __future__ import annotations

import ast

from tests.test_embed_column_allowlist_structural import (
    APP,
    _embed_authorized,
    _index,
    _is_route,
    _reaching,
)


def _route_paths(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        d.args[0].value
        for d in node.decorator_list
        if isinstance(d, ast.Call)
        and d.args
        and isinstance(d.args[0], ast.Constant)
        and isinstance(d.args[0].value, str)
    }


def _export_handlers() -> set[tuple[str, str]]:
    """Handlers in an export module, or serving a path that names export."""
    found = set()
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) or not _is_route(node):
                continue
            if "export" in rel or any("export" in p for p in _route_paths(node)):
                found.add((rel, node.name))
    return found


def test_export_routes_read_no_embed_token() -> None:
    exports = _export_handlers()
    assert ("processing/export/router.py", "export_dataset_endpoint") in exports

    # Any reference counts, not only a call, so a Depends() that resolves a
    # token is caught as well as a direct call.
    reaching = _reaching(_embed_authorized, "names")
    _, handlers = _index()
    embed_reading = sorted(
        f"{rel}::{name}"
        for rel, name, used in handlers
        if (rel, name) in exports
        and (_embed_authorized(used) or (used.names | used.calls) & reaching)
    )
    assert not embed_reading, (
        "An export route must not read an embed token: a token scoped to a map "
        f"would then download whole datasets. Found: {embed_reading}"
    )
