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

1. **In-process rasterio access is wrapped or justified, per call.** Every
   ``rasterio.open(...)`` call must sit lexically inside a
   ``with gdal_safe_open_env()...:`` block (the in-process twin of
   ``gdal_safe_env`` in ``app/processing/raster/vrt.py``), or be covered by
   a ``RASTERIO_OPEN_ALLOWLIST`` entry carrying an EXACT expected call count
   plus a justification — a second unwrapped open added to an
   already-justified function fails instead of riding the entry. Every
   ``rasterio.Env(...)`` construction must be the one inside
   ``gdal_safe_open_env`` itself — ad-hoc Env objects are how clamps drift.

2. **GDAL CLI subprocess argv is built next to the safe env or justified,
   per call.** Every argv list literal starting with a GDAL CLI tool
   (``gdalbuildvrt``, ``gdaladdo``, ``gdalwarp``, ``gdal_translate``,
   ``gdalinfo``, ``ogrinfo``, ``ogr2ogr``) must sit in a FUNCTION that
   references ``gdal_safe_env``, or match a ``GDAL_CLI_CALL_ALLOWLIST``
   entry keyed (module, function, tool) with an exact expected count and a
   justification.

Both allowlists are asserted EXACT in both directions and by count, so an
entry whose site disappears (or becomes wrapped) fails loudly instead of
going stale.

Known limits (accepted trade-offs, same posture as the Rule-1 guard):

- Detection matches ``rasterio.open`` / ``rasterio.Env`` attribute calls and
  common aliases of the module import. ``from rasterio import open as ropen``
  or fully dynamic access (``getattr(rasterio, "open")``) is invisible; no
  such shape exists in the codebase.
- The CLI check is function-scoped with exact counts, not full dataflow: an
  argv is credited when its ENCLOSING FUNCTION references ``gdal_safe_env``,
  and unclamped argvs are counted per (module, function, tool) against the
  allowlist. A function that calls the helper for one subprocess and
  hand-rolls a second env in the SAME function for the SAME tool would still
  pass; verifying which env reaches which ``subprocess.run`` is reviewer
  territory.
- Argv built dynamically (``cmd = [tool_var, ...]``) is not matched. Every
  GDAL CLI call in the codebase starts from a string-literal argv head.
- Wrapping is judged lexically: a ``rasterio.open`` inside a
  ``with gdal_safe_open_env():`` body passes even if a refactor later moves
  the open into a helper called from outside the block. Reviewer territory.
- Helper credit requires the name to be bound to the canonical module by an
  import the resolver understands (see ``_canonical_bindings``). A dotted
  ``import app.processing.raster.vrt`` used without an alias, or a re-export
  through an intermediate module, is NOT credited — the failure mode is a
  spurious violation prompting a review, never silent credit for a shadow.
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

# The one module whose definitions of the helpers are canonical. Credit for
# using a helper requires the name to be BOUND to this module (imported from
# it, or used inside it) — a bare tail-name match would hand credit to a
# local shadow or an unrelated `something.gdal_safe_open_env()` (codex round
# 3 on #974).
CANONICAL_HELPER_MODULE_REL = "processing/raster/vrt.py"
CANONICAL_HELPER_MODULE_SUFFIX = "processing.raster.vrt"

# (module path relative to backend/app, enclosing function name) ->
# (expected UNWRAPPED rasterio.open count, justification). Adding a new
# rasterio.open means either wrapping it in `with gdal_safe_open_env():` or
# adding/adjusting an entry here with a reviewed justification. The count is
# asserted EXACTLY (codex P2 on #974): a second unwrapped open slipped into
# an already-justified function must fail, not ride the existing entry.
RASTERIO_OPEN_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/raster/cog.py", "validate_raster_crs"): (
        1,
        "local staged upload path only; no caller-controlled URL reaches it "
        "(callers: ingest/router.py, tasks_raster.py — counted on #936)",
    ),
    ("processing/raster/cog.py", "extract_raster_metadata"): (
        1,
        "local staged/temp path only; no caller-controlled URL reaches it",
    ),
    ("processing/raster/cog.py", "check_cog_compliance"): (
        1,
        "local staged/temp path only; no caller-controlled URL reaches it",
    ),
    ("processing/raster/cog.py", "prepare_with_overviews"): (
        1,
        "local staged/temp path only; probes for internal overviews before "
        "spawning the (safe-env) gdaladdo subprocess",
    ),
    ("processing/raster/quicklook.py", "generate_quicklook"): (
        1,
        "opens the locally produced COG output, never a source URL",
    ),
}

# (module path relative to backend/app, enclosing function name) ->
# (expected rasterio.Env construction count, justification). Counted exactly
# (codex round 2 on #974): a second Env built inside the wrapper function
# would share the site tuple and ride the canonical entry under a set-based
# check, so membership alone is not enough.
RASTERIO_ENV_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/raster/vrt.py", SAFE_OPEN_ENV_HELPER): (
        1,
        "the canonical wrapper itself — the only place an Env may be built",
    ),
}

# (module path relative to backend/app, enclosing function, tool) ->
# (expected argv-literal count, justification) for GDAL CLI argv built in a
# function that does NOT reference gdal_safe_env. Function-scoped with exact
# counts (codex P2 on #974): a module- or function-level pass may not absorb
# a future hand-rolled subprocess — a new argv in a justified function, or a
# new function in a covered module, must fail on its own.
GDAL_CLI_CALL_ALLOWLIST: dict[tuple[str, str, str], tuple[int, str]] = {
    ("processing/ingest/ogr.py", "run_ogrinfo", "ogrinfo"): (
        2,
        "local staged file; two argvs are the -json path and the pre-GDAL-3.7 "
        "text fallback — no HTTP surface",
    ),
    ("processing/ingest/ogr.py", "run_ogrinfo_preview", "ogrinfo"): (
        1,
        "local staged file preview; no HTTP surface",
    ),
    ("processing/ingest/ogr.py", "run_ogr2ogr", "ogr2ogr"): (
        1,
        "local file into PostGIS; no HTTP surface",
    ),
    ("processing/ingest/ogr.py", "run_ogr2ogr_service", "ogr2ogr"): (
        1,
        "user-supplied service URL gated by validate_url_for_ssrf at "
        "submission time; the vsicurl extension clamps in gdal_safe_env do "
        "not apply to OGR service drivers (SEC-008 documents the residual, "
        "mitigated operationally)",
    ),
    ("processing/export/ogr.py", "run_ogr2ogr_export", "ogr2ogr"): (
        1,
        "PostGIS to local file; argv carries a DB connection string and a "
        "local output path, never a user URL",
    ),
    ("modules/catalog/sources/preview.py", "run_service_preview", "ogrinfo"): (
        1,
        "user-supplied service URL gated by validate_url_for_ssrf at "
        "submission time (#937); the vsicurl extension clamps do not apply "
        "to OGR service drivers",
    ),
}

# Floors so a refactor that blinds the detector fails loudly instead of
# passing on an empty scan (same trick as the Rule-1 route-count floor).
MIN_RASTERIO_OPEN_SITES = 5
MIN_GDAL_CLI_ARGV_SITES = 6


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


def _canonical_bindings(
    rel: str, tree: ast.Module
) -> tuple[dict[str, set[str]], set[str]]:
    """Resolve which local names are bound to the canonical helpers.

    Returns (helper_names, module_aliases): ``helper_names`` maps each helper
    to the set of local names that resolve to its canonical definition;
    ``module_aliases`` is the set of local names bound to the canonical vrt
    module itself (for ``vrt.gdal_safe_open_env()``-style access).

    codex round 3 on #974: a tail-name match credited local shadows and
    unrelated attribute calls. Credit now requires one of:
    - the module IS the canonical module and defines the helper at top level;
    - ``from app.processing.raster.vrt import <helper> [as alias]``;
    - an attribute access on a name bound by
      ``from app.processing.raster import vrt [as alias]`` or
      ``import app.processing.raster.vrt as alias``.
    """
    helper_names: dict[str, set[str]] = {
        SAFE_OPEN_ENV_HELPER: set(),
        SAFE_SUBPROCESS_ENV_HELPER: set(),
    }
    module_aliases: set[str] = set()

    if rel == CANONICAL_HELPER_MODULE_REL:
        for stmt in tree.body:
            if (
                isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                and stmt.name in helper_names
            ):
                helper_names[stmt.name].add(stmt.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.endswith(CANONICAL_HELPER_MODULE_SUFFIX):
                for alias in node.names:
                    if alias.name in helper_names:
                        helper_names[alias.name].add(alias.asname or alias.name)
            elif node.module.endswith("processing.raster"):
                for alias in node.names:
                    if alias.name == "vrt":
                        module_aliases.add(alias.asname or "vrt")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(CANONICAL_HELPER_MODULE_SUFFIX) and alias.asname:
                    module_aliases.add(alias.asname)

    return helper_names, module_aliases


def _is_canonical_helper_call(
    expr: ast.expr,
    helper: str,
    helper_names: dict[str, set[str]],
    module_aliases: set[str],
) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name):
        return func.id in helper_names[helper]
    if isinstance(func, ast.Attribute) and func.attr == helper:
        return isinstance(func.value, ast.Name) and func.value.id in module_aliases
    return False


def _inside_safe_open_env(
    node: ast.AST,
    helper_names: dict[str, set[str]],
    module_aliases: set[str],
) -> bool:
    current = node
    while current is not None:
        if isinstance(current, (ast.With, ast.AsyncWith)):
            for item in current.items:
                if _is_canonical_helper_call(
                    item.context_expr,
                    SAFE_OPEN_ENV_HELPER,
                    helper_names,
                    module_aliases,
                ):
                    return True
        current = getattr(current, "_rule2_parent", None)
    return False


def _enclosing_function_node(
    node: ast.AST,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = getattr(current, "_rule2_parent", None)
    return None


def _scope_uses_safe_env(
    root: ast.AST,
    helper_names: dict[str, set[str]],
    module_aliases: set[str],
) -> bool:
    """True when the scope references a name BOUND to the canonical
    gdal_safe_env (codex round 3: tail-name matching credited shadows)."""
    for node in ast.walk(root):
        if (
            isinstance(node, ast.Name)
            and node.id in helper_names[SAFE_SUBPROCESS_ENV_HELPER]
        ):
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr == SAFE_SUBPROCESS_ENV_HELPER
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
        ):
            return True
    return False


def _blank_justification_violations(allowlist_name: str, allowlist: dict) -> list[str]:
    """codex round 3 on #974: an entry with a blank justification defeats the
    reviewed-justification contract while still counting as covered."""
    violations = []
    for key, (_count, justification) in sorted(allowlist.items()):
        if not justification.strip():
            violations.append(
                f"{allowlist_name} entry {key} has a blank justification — "
                "every entry must record WHY the site is acceptable"
            )
    return violations


def _collect_rasterio_violations(
    modules: list[tuple[str, ast.Module]],
    open_allowlist: dict[tuple[str, str], tuple[int, str]],
    env_allowlist: dict[tuple[str, str], tuple[int, str]],
) -> tuple[list[str], int]:
    """Return (violations, total rasterio.open call count).

    codex round 1 on #974: allowlisting is per-call, not per-function —
    unwrapped opens are COUNTED per (module, function) and the count must
    equal the allowlist entry exactly.

    codex round 2 on #974: a wrapped open sharing its (module, function)
    tuple with a justified unwrapped one is NOT evidence the entry is stale —
    staleness is judged only from the collected unwrapped counts. And
    rasterio.Env constructions are counted per site too, so a second Env
    inside the wrapper function cannot ride the canonical entry.
    """
    unwrapped_counts: dict[tuple[str, str], int] = {}
    unwrapped_lines: dict[tuple[str, str], list[int]] = {}
    env_counts: dict[tuple[str, str], int] = {}
    env_lines: dict[tuple[str, str], list[int]] = {}
    violations: list[str] = []
    total_open_calls = 0

    violations += _blank_justification_violations(
        "RASTERIO_OPEN_ALLOWLIST", open_allowlist
    )
    violations += _blank_justification_violations(
        "RASTERIO_ENV_ALLOWLIST", env_allowlist
    )

    for rel, tree in modules:
        _annotate_parents(tree)
        helper_names, module_aliases = _canonical_bindings(rel, tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_rasterio_call(node, "open"):
                total_open_calls += 1
                site = (rel, _enclosing_function(node))
                if _inside_safe_open_env(node, helper_names, module_aliases):
                    continue
                unwrapped_counts[site] = unwrapped_counts.get(site, 0) + 1
                unwrapped_lines.setdefault(site, []).append(node.lineno)
            elif _is_rasterio_call(node, "Env"):
                site = (rel, _enclosing_function(node))
                env_counts[site] = env_counts.get(site, 0) + 1
                env_lines.setdefault(site, []).append(node.lineno)

    for site, count in sorted(unwrapped_counts.items()):
        rel, func = site
        lines = ",".join(str(n) for n in unwrapped_lines[site])
        if site not in open_allowlist:
            violations.append(
                f"{rel}:{lines} ({func}) calls rasterio.open outside "
                f"`with {SAFE_OPEN_ENV_HELPER}():` — wrap it, or allowlist it "
                "here with a justification (AGENTS.md Rule 2, #936)"
            )
        elif count != open_allowlist[site][0]:
            violations.append(
                f"{rel} ({func}) has {count} unwrapped rasterio.open call(s) "
                f"at line(s) {lines} but the allowlist justifies exactly "
                f"{open_allowlist[site][0]} — each call needs its own "
                "review: wrap the new one or update the entry deliberately"
            )

    for site in sorted(set(open_allowlist) - set(unwrapped_counts)):
        violations.append(
            f"stale RASTERIO_OPEN_ALLOWLIST entry {site} — the unwrapped call "
            "no longer exists; remove the entry"
        )

    for site, count in sorted(env_counts.items()):
        rel, func = site
        lines = ",".join(str(n) for n in env_lines[site])
        if site not in env_allowlist:
            violations.append(
                f"{rel}:{lines} ({func}) constructs a raw rasterio.Env — use "
                f"{SAFE_OPEN_ENV_HELPER} from app/processing/raster/vrt.py "
                "instead (#936)"
            )
        elif count != env_allowlist[site][0]:
            violations.append(
                f"{rel} ({func}) constructs {count} rasterio.Env objects at "
                f"line(s) {lines} but the allowlist sanctions exactly "
                f"{env_allowlist[site][0]} — a second Env is how clamps "
                "drift; build on the canonical one"
            )

    for site in sorted(set(env_allowlist) - set(env_counts)):
        violations.append(
            f"stale RASTERIO_ENV_ALLOWLIST entry {site} — no matching "
            "construction exists; remove the entry"
        )

    return violations, total_open_calls


def _collect_gdal_cli_violations(
    modules: list[tuple[str, ast.Module]],
    allowlist: dict[tuple[str, str, str], tuple[int, str]],
) -> tuple[list[str], int]:
    """Return (violations, total GDAL CLI argv count).

    codex round 1 on #974: judged per ENCLOSING FUNCTION with exact counts,
    not per module — a new hand-rolled argv in a module that references
    gdal_safe_env elsewhere fails on its own. Staleness is judged only from
    the collected unclamped counts (codex round 2: no shared-scope shortcut).
    """
    violations: list[str] = []
    total_argv_sites = 0
    unsafe_counts: dict[tuple[str, str, str], int] = {}
    unsafe_lines: dict[tuple[str, str, str], list[int]] = {}

    violations += _blank_justification_violations("GDAL_CLI_CALL_ALLOWLIST", allowlist)

    for rel, tree in modules:
        _annotate_parents(tree)
        helper_names, module_aliases = _canonical_bindings(rel, tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.List) and node.elts):
                continue
            first = node.elts[0]
            if not (isinstance(first, ast.Constant) and first.value in GDAL_CLI_TOOLS):
                continue
            total_argv_sites += 1
            func_node = _enclosing_function_node(node)
            func_name = func_node.name if func_node is not None else "<module>"
            scope: ast.AST = func_node if func_node is not None else tree
            if _scope_uses_safe_env(scope, helper_names, module_aliases):
                continue
            key = (rel, func_name, first.value)
            unsafe_counts[key] = unsafe_counts.get(key, 0) + 1
            unsafe_lines.setdefault(key, []).append(node.lineno)

    for key, count in sorted(unsafe_counts.items()):
        rel, func_name, tool = key
        lines = ",".join(str(n) for n in unsafe_lines[key])
        if key not in allowlist:
            violations.append(
                f"{rel}:{lines} ({func_name}) builds a {tool} argv without "
                f"{SAFE_SUBPROCESS_ENV_HELPER} in the same function — route "
                "the subprocess env through it, or allowlist this exact "
                "(module, function, tool) with a justification "
                "(AGENTS.md Rule 2, #936)"
            )
        elif count != allowlist[key][0]:
            violations.append(
                f"{rel} ({func_name}) has {count} {tool} argv(s) at line(s) "
                f"{lines} but the allowlist justifies exactly "
                f"{allowlist[key][0]} — each subprocess needs "
                "its own review: use the safe env for the new one or update "
                "the entry deliberately"
            )

    for key in sorted(set(allowlist) - set(unsafe_counts)):
        violations.append(
            f"stale GDAL_CLI_CALL_ALLOWLIST entry {key} — no matching "
            "unclamped argv exists; remove the entry"
        )

    return violations, total_argv_sites


def test_rasterio_open_sites_are_wrapped_or_allowlisted():
    violations, total_open_calls = _collect_rasterio_violations(
        _app_modules(), RASTERIO_OPEN_ALLOWLIST, RASTERIO_ENV_ALLOWLIST
    )
    assert not violations, "\n".join(violations)
    assert total_open_calls >= MIN_RASTERIO_OPEN_SITES, (
        f"detector saw only {total_open_calls} rasterio.open call(s); the "
        f"codebase has at least {MIN_RASTERIO_OPEN_SITES} — the scan has gone "
        "blind, fix the detector before trusting this guard"
    )


def test_gdal_cli_argv_uses_safe_env_or_is_allowlisted():
    violations, total_argv_sites = _collect_gdal_cli_violations(
        _app_modules(), GDAL_CLI_CALL_ALLOWLIST
    )
    assert not violations, "\n".join(violations)
    assert total_argv_sites >= MIN_GDAL_CLI_ARGV_SITES, (
        f"detector saw only {total_argv_sites} GDAL CLI argv site(s); the "
        f"codebase has at least {MIN_GDAL_CLI_ARGV_SITES} — the scan has gone "
        "blind, fix the detector before trusting this guard"
    )


# ---------------------------------------------------------------------------
# Guard-logic regressions, pinned with synthetic modules. Each case is a
# shape a codex review round on #974 proved the set-based accounting missed.
# ---------------------------------------------------------------------------


def _mod(src: str) -> list[tuple[str, ast.Module]]:
    return [("seed/mod.py", ast.parse(src))]


def test_guard_mixed_wrapped_and_allowlisted_open_passes():
    """codex round 2: one justified unwrapped open PLUS a new open correctly
    wrapped in gdal_safe_open_env share the (module, function) tuple; the
    wrapped call must not make the entry read as stale."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def fn(path):\n"
            "    with rasterio.open(path) as a:\n"
            "        pass\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(path) as b:\n"
            "            pass\n"
        ),
        {("seed/mod.py", "fn"): (1, "seed: the unwrapped open is justified")},
        {},
    )
    assert violations == []


def test_guard_second_unwrapped_open_in_justified_function_fails():
    """codex round 1: a second unwrapped open may not ride the entry."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path):\n"
            "    with rasterio.open(path) as a, rasterio.open(path) as b:\n"
            "        pass\n"
        ),
        {("seed/mod.py", "fn"): (1, "seed: only ONE open is justified")},
        {},
    )
    assert len(violations) == 1 and "justifies exactly 1" in violations[0]


def test_guard_second_env_inside_wrapper_fails():
    """codex round 2: two rasterio.Env constructions collapse to one site
    tuple; the count must catch the second one."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def gdal_safe_open_env():\n"
            "    rasterio.Env(A='1')\n"
            "    return rasterio.Env(B='2')\n"
        ),
        {},
        {("seed/mod.py", "gdal_safe_open_env"): (1, "seed: one sanctioned Env")},
    )
    assert len(violations) == 1 and "constructs 2 rasterio.Env" in violations[0]


def test_guard_new_cli_argv_in_covered_module_fails():
    """codex round 1: a module referencing gdal_safe_env elsewhere may not
    absorb a hand-rolled argv in a function that does not use it."""
    violations, _ = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def safe_fn():\n"
            "    return gdal_safe_env()\n"
            "def sneaky(url):\n"
            "    return ['ogrinfo', '-json', url]\n"
        ),
        {},
    )
    assert len(violations) == 1 and "sneaky" in violations[0]


def test_guard_shadowed_open_env_helper_gets_no_credit():
    """codex round 3: a local shadow of gdal_safe_open_env, or an unrelated
    `something.gdal_safe_open_env()`, must not earn wrapping credit — only a
    name bound to the canonical vrt module counts."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def gdal_safe_open_env():\n"
            "    class _N:\n"
            "        def __enter__(self):\n"
            "            return None\n"
            "        def __exit__(self, *a):\n"
            "            return False\n"
            "    return _N()\n"
            "def shadowed(path):\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
            "def decoy(obj, path):\n"
            "    with obj.gdal_safe_open_env():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 2, violations
    assert any("shadowed" in v for v in violations)
    assert any("decoy" in v for v in violations)


def test_guard_canonically_imported_helper_gets_credit():
    """The binding resolver must still credit the legitimate forms: a
    canonical from-import (aliased or not) and vrt-module attribute access."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env as goe\n"
            "from app.processing.raster import vrt\n"
            "def a(path):\n"
            "    with goe():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
            "def b(path):\n"
            "    with vrt.gdal_safe_open_env():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert violations == []


def test_guard_shadowed_cli_helper_gets_no_credit():
    """codex round 3, CLI side: a local def of gdal_safe_env must not credit
    the argvs in its module."""
    violations, _ = _collect_gdal_cli_violations(
        _mod(
            "import os\n"
            "def gdal_safe_env():\n"
            "    return dict(os.environ)\n"
            "def runs(url):\n"
            "    env = gdal_safe_env()\n"
            "    return ['ogrinfo', '-json', url], env\n"
        ),
        {},
    )
    assert len(violations) == 1 and "runs" in violations[0]


def test_guard_blank_justification_fails():
    """codex round 3: a (count, '') entry defeats the reviewed-justification
    contract; blank justifications fail in every allowlist."""
    modules = _mod(
        "import rasterio\ndef fn(path):\n    with rasterio.open(path):\n        pass\n"
    )
    violations, _ = _collect_rasterio_violations(
        modules, {("seed/mod.py", "fn"): (1, "   ")}, {}
    )
    assert len(violations) == 1 and "blank justification" in violations[0]
    cli_violations, _ = _collect_gdal_cli_violations(
        _mod("x = 1\n"), {("seed/mod.py", "fn", "ogrinfo"): (1, "")}
    )
    assert any("blank justification" in v for v in cli_violations)
