"""Rule-2 structural guard for the GDAL/rasterio half (fix(#936)).

AGENTS.md Rule 2 has two halves. The httpx half (``make_safe_client()`` for
any ``follow_redirects=True`` client) is enforced by the ``ssrf-safe-client``
pre-commit hook. The GDAL/rasterio half had NO enforcement at all: a new
in-process ``rasterio.open()`` involves no ``httpx`` and no subprocess, so
the hook cannot see it, and a new GDAL CLI subprocess that hand-rolls its
env instead of calling ``gdal_safe_env()`` trips nothing either.

This module closes that gap structurally, in the spirit of
``test_rule1_structural.py`` (#822): it walks every module under
``backend/app/`` as an AST and asserts two properties.

1. **In-process rasterio access is wrapped or justified.** Every
   ``rasterio.open(...)`` call must sit lexically inside a
   ``with gdal_safe_open_env()...:`` block (the in-process twin of
   ``gdal_safe_env`` in ``app/processing/raster/vrt.py``), or appear in
   ``RASTERIO_OPEN_ALLOWLIST`` with a per-entry justification. Every
   ``rasterio.Env(...)`` construction must be the one inside
   ``gdal_safe_open_env`` itself — ad-hoc Env objects are how clamps drift.

2. **GDAL CLI subprocess argv is built next to the safe env or justified.**
   Any module that builds an argv list literal starting with a GDAL CLI tool
   (``gdalbuildvrt``, ``gdaladdo``, ``gdalwarp``, ``gdal_translate``,
   ``gdalinfo``, ``ogrinfo``, ``ogr2ogr``) must reference ``gdal_safe_env``
   or appear in ``GDAL_CLI_MODULE_ALLOWLIST`` with a justification.

Both allowlists are asserted EXACT in both directions, so an entry whose
site disappears (or becomes wrapped) fails loudly instead of going stale.

Known limits (accepted trade-offs, same posture as the Rule-1 guard):

- Detection matches ``rasterio.open`` / ``rasterio.Env`` attribute calls and
  common aliases of the module import. ``from rasterio import open as ropen``
  or fully dynamic access (``getattr(rasterio, "open")``) is invisible; no
  such shape exists in the codebase.
- The CLI check is module-scoped: a module referencing ``gdal_safe_env``
  anywhere passes for every argv literal it contains. That mirrors what a
  reviewer verifies (this module routes its subprocesses through the safe
  env) without full dataflow; a module calling the helper for one subprocess
  and hand-rolling another would pass. Call-site env dataflow is a
  documented limit, not a promise.
- Argv built dynamically (``cmd = [tool_var, ...]``) is not matched. Every
  GDAL CLI call in the codebase starts from a string-literal argv head.
- Wrapping is judged lexically: a ``rasterio.open`` inside a
  ``with gdal_safe_open_env():`` body passes even if a refactor later moves
  the open into a helper called from outside the block. Reviewer territory.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

GDAL_CLI_TOOLS = {
    "gdalbuildvrt",
    "gdaladdo",
    "gdalwarp",
    "gdal_translate",
    "gdalinfo",
    "ogrinfo",
    "ogr2ogr",
}

SAFE_SUBPROCESS_ENV_HELPER = "gdal_safe_env"
SAFE_OPEN_ENV_HELPER = "gdal_safe_open_env"

# (module path relative to backend/app, enclosing function name) -> why an
# UNWRAPPED rasterio.open is acceptable there. Adding a new rasterio.open
# means either wrapping it in `with gdal_safe_open_env():` or adding an entry
# here with a reviewed justification.
RASTERIO_OPEN_ALLOWLIST: dict[tuple[str, str], str] = {
    ("processing/raster/cog.py", "validate_raster_crs"): (
        "local staged upload path only; no caller-controlled URL reaches it "
        "(callers: ingest/router.py, tasks_raster.py — counted on #936)"
    ),
    ("processing/raster/cog.py", "extract_raster_metadata"): (
        "local staged/temp path only; no caller-controlled URL reaches it"
    ),
    ("processing/raster/cog.py", "check_cog_compliance"): (
        "local staged/temp path only; no caller-controlled URL reaches it"
    ),
    ("processing/raster/cog.py", "prepare_with_overviews"): (
        "local staged/temp path only; probes for internal overviews before "
        "spawning the (safe-env) gdaladdo subprocess"
    ),
    ("processing/raster/quicklook.py", "generate_quicklook"): (
        "opens the locally produced COG output, never a source URL"
    ),
}

# (module path relative to backend/app, enclosing function name) for the one
# sanctioned rasterio.Env construction.
RASTERIO_ENV_ALLOWLIST: dict[tuple[str, str], str] = {
    ("processing/raster/vrt.py", SAFE_OPEN_ENV_HELPER): (
        "the canonical wrapper itself — the only place an Env may be built"
    ),
}

# Module path relative to backend/app -> why its GDAL CLI argv does not go
# through gdal_safe_env. Modules that DO reference gdal_safe_env never need
# an entry.
GDAL_CLI_MODULE_ALLOWLIST: dict[str, str] = {
    "processing/ingest/ogr.py": (
        "ogr2ogr/ogrinfo over local staged files (no HTTP surface) and the "
        "service-ingest path, whose user-supplied URL is gated by "
        "validate_url_for_ssrf at submission time; the vsicurl extension "
        "clamps in gdal_safe_env do not apply to OGR service drivers "
        "(SEC-008 documents the residual, mitigated operationally)"
    ),
    "processing/export/ogr.py": (
        "ogr2ogr export from PostGIS to a local file; argv carries a DB "
        "connection string and local output path, never a user URL"
    ),
    "modules/catalog/sources/preview.py": (
        "ogrinfo preview of a user-supplied service URL, gated by "
        "validate_url_for_ssrf at submission time (#937); the vsicurl "
        "extension clamps do not apply to OGR service drivers"
    ),
}

# Floors so a refactor that blinds the detector fails loudly instead of
# passing on an empty scan (same trick as the Rule-1 route-count floor).
MIN_RASTERIO_OPEN_SITES = 5
MIN_GDAL_CLI_MODULES = 4


def _app_modules() -> list[tuple[str, ast.Module]]:
    modules = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        modules.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _annotate_parents(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._rule2_parent = node  # type: ignore[attr-defined]


def _enclosing_function(node: ast.AST) -> str:
    current = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = getattr(current, "_rule2_parent", None)
    return "<module>"


def _call_name(func: ast.expr) -> str | None:
    """Dotted-tail name of a call target: ``a.b.c(...)`` -> ``c``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_rasterio_call(node: ast.Call, attr: str) -> bool:
    """Match ``rasterio.open`` / ``rasterio.Env`` including ``rio.open``-style
    aliases: any Attribute call named ``attr`` on a bare Name whose id
    contains ``rasterio`` or is ``rio``."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == attr):
        return False
    base = func.value
    return isinstance(base, ast.Name) and ("rasterio" in base.id or base.id == "rio")


def _inside_safe_open_env(node: ast.AST) -> bool:
    current = node
    while current is not None:
        if isinstance(current, (ast.With, ast.AsyncWith)):
            for item in current.items:
                expr = item.context_expr
                if (
                    isinstance(expr, ast.Call)
                    and _call_name(expr.func) == SAFE_OPEN_ENV_HELPER
                ):
                    return True
        current = getattr(current, "_rule2_parent", None)
    return False


def _module_references(tree: ast.Module, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == name or alias.asname == name:
                    return True
    return False


def _gdal_cli_argv_heads(tree: ast.Module) -> set[str]:
    heads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value in GDAL_CLI_TOOLS:
                heads.add(first.value)
    return heads


def test_rasterio_open_sites_are_wrapped_or_allowlisted():
    found: set[tuple[str, str]] = set()
    violations: list[str] = []
    total_open_calls = 0

    for rel, tree in _app_modules():
        _annotate_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_rasterio_call(node, "open"):
                total_open_calls += 1
                site = (rel, _enclosing_function(node))
                if _inside_safe_open_env(node):
                    if site in RASTERIO_OPEN_ALLOWLIST:
                        violations.append(
                            f"{rel}:{node.lineno} ({site[1]}) is wrapped in "
                            f"{SAFE_OPEN_ENV_HELPER} AND allowlisted — remove "
                            "the stale allowlist entry"
                        )
                    continue
                found.add(site)
                if site not in RASTERIO_OPEN_ALLOWLIST:
                    violations.append(
                        f"{rel}:{node.lineno} ({site[1]}) calls rasterio.open "
                        f"outside `with {SAFE_OPEN_ENV_HELPER}():` — wrap it, "
                        "or allowlist it here with a justification "
                        "(AGENTS.md Rule 2, #936)"
                    )
            elif _is_rasterio_call(node, "Env"):
                site = (rel, _enclosing_function(node))
                if site not in RASTERIO_ENV_ALLOWLIST:
                    violations.append(
                        f"{rel}:{node.lineno} ({site[1]}) constructs a raw "
                        f"rasterio.Env — use {SAFE_OPEN_ENV_HELPER} from "
                        "app/processing/raster/vrt.py instead (#936)"
                    )

    stale = set(RASTERIO_OPEN_ALLOWLIST) - found
    for site in sorted(stale):
        violations.append(
            f"stale RASTERIO_OPEN_ALLOWLIST entry {site} — the unwrapped call "
            "no longer exists; remove the entry"
        )

    assert not violations, "\n".join(violations)
    assert total_open_calls >= MIN_RASTERIO_OPEN_SITES, (
        f"detector saw only {total_open_calls} rasterio.open call(s); the "
        f"codebase has at least {MIN_RASTERIO_OPEN_SITES} — the scan has gone "
        "blind, fix the detector before trusting this guard"
    )


def test_rasterio_env_allowlist_is_exact():
    found: set[tuple[str, str]] = set()
    for rel, tree in _app_modules():
        _annotate_parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_rasterio_call(node, "Env"):
                found.add((rel, _enclosing_function(node)))
    assert found == set(RASTERIO_ENV_ALLOWLIST), (
        f"rasterio.Env sites {found} != allowlist {set(RASTERIO_ENV_ALLOWLIST)}"
    )


def test_gdal_cli_modules_use_safe_env_or_are_allowlisted():
    violations: list[str] = []
    cli_modules: set[str] = set()

    for rel, tree in _app_modules():
        heads = _gdal_cli_argv_heads(tree)
        if not heads:
            continue
        cli_modules.add(rel)
        uses_safe_env = _module_references(tree, SAFE_SUBPROCESS_ENV_HELPER)
        allowlisted = rel in GDAL_CLI_MODULE_ALLOWLIST
        if uses_safe_env and allowlisted:
            violations.append(
                f"{rel} references {SAFE_SUBPROCESS_ENV_HELPER} AND is "
                "allowlisted — remove the stale allowlist entry"
            )
        elif not uses_safe_env and not allowlisted:
            violations.append(
                f"{rel} builds GDAL CLI argv {sorted(heads)} without "
                f"{SAFE_SUBPROCESS_ENV_HELPER} — route the subprocess env "
                "through it, or allowlist the module here with a "
                "justification (AGENTS.md Rule 2, #936)"
            )

    stale = set(GDAL_CLI_MODULE_ALLOWLIST) - cli_modules
    for rel in sorted(stale):
        violations.append(
            f"stale GDAL_CLI_MODULE_ALLOWLIST entry {rel} — the module no "
            "longer builds GDAL CLI argv; remove the entry"
        )

    assert not violations, "\n".join(violations)
    assert len(cli_modules) >= MIN_GDAL_CLI_MODULES, (
        f"detector saw only {len(cli_modules)} GDAL CLI module(s); the "
        f"codebase has at least {MIN_GDAL_CLI_MODULES} — the scan has gone "
        "blind, fix the detector before trusting this guard"
    )
