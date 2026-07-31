"""Rule-2 structural guard for the GDAL/rasterio half (fix(#936)).

AGENTS.md Rule 2 has two halves. The httpx half (``make_safe_client()`` for
any ``follow_redirects=True`` client) is enforced by the ``ssrf-safe-client``
pre-commit hook. The GDAL/rasterio half had NO enforcement at all: a new
in-process ``rasterio.open()`` involves no ``httpx`` and no subprocess, so
the hook cannot see it, and a new GDAL CLI subprocess that hand-rolls its
env instead of calling ``gdal_safe_env()`` trips nothing either.

**THE INVARIANT: no recognizable guarded call has a silent-pass path.**
A call is recognizable when its head is an attribute named ``open``/``Env``,
or a name that any binding this resolver follows ties to a rasterio
callable — imports, aliases assigned from one (``ropen = rasterio.open``,
``rs = rasterio``, and chains of those), or a ``from rasterio import *``.
For every such call the answer is detected, confidently-something-else, or
UNCLASSIFIED — and UNCLASSIFIED is a VIOLATION. Resolution failure resolves
to a violation, so function defaults, decorators, annotations, star
imports, unrootable expression heads, and aliases built through
expressions the resolver cannot follow (``opener = getattr(rasterio,
"open")``) all fail loudly instead of passing quietly. False alarms are
cheap and visible; a silent miss is the failure that matters.

What is outside the invariant, stated plainly: a rasterio callable that
reaches a call site with NO lexical trace at all — arriving as a plain
parameter, pulled out of a dict, returned by a factory in another module —
is not recognizable as a guarded call by any AST rule, and this gate does
not claim it. That is the same provenance boundary documented for remote
URLs below, and it is enforced elsewhere (``validate_url_for_ssrf``,
``make_safe_client``, the ``CPL_VSIL_CURL_ALLOWED_EXTENSIONS`` clamp).

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
   per call.** Every argv list or tuple literal whose head names a
   gdal*/ogr* executable (the family, not a fixed list — codex round 10)
   must sit in a FUNCTION that references ``gdal_safe_env``, or match a
   ``GDAL_CLI_CALL_ALLOWLIST`` entry keyed (module, function, tool) with an
   exact expected count and a justification.

Both allowlists are asserted EXACT in both directions and by count, so an
entry whose site disappears (or becomes wrapped) fails loudly instead of
going stale.

Known limits (accepted trade-offs, same posture as the Rule-1 guard):

- rasterio detection resolves ACTUAL bindings per scope (codex rounds 5 and
  12): ``import rasterio [as X]``, ``from rasterio import open/Env [as Y]``,
  and simple alias assignments from either (``ropen = rasterio.open``,
  ``rs = rasterio``, chained) are tracked, so ``rs.open(...)`` and
  ``ropen(...)`` are both seen. An alias built through an expression the
  resolver cannot follow (``getattr``, a ternary, a factory call) is marked
  unsure and its calls are UNCLASSIFIED violations. Re-exports of rasterio
  callables through intermediate modules stay invisible; no such shape
  exists in the codebase.
- The CLI check is function-scoped with exact counts, not full dataflow: an
  argv is credited when its ENCLOSING FUNCTION references ``gdal_safe_env``,
  and unclamped argvs are counted per (module, function, tool) against the
  allowlist. A function that calls the helper for one subprocess and
  hand-rolls a second env in the SAME function for the SAME tool would still
  pass; verifying which env reaches which ``subprocess.run`` is reviewer
  territory.
- Argv built dynamically (``cmd = [tool_var, ...]``) is not matched. Every
  GDAL CLI call in the codebase starts from a string-literal argv head.
- A GDAL-headed literal counts as an argv only when its value ESCAPES —
  handed to a call, returned, or yielded — directly, out of a container
  literal, or through a name (``=``, annotated ``=``, walrus) it is bound to
  (fix(#996)). Inert data (``SUPPORTED_TOOLS = ["gdalinfo", "ogrinfo"]``, a
  constant only subscripted or compared) is not a command vector. A literal
  whose every element names a GDAL utility is a name list rather than a
  command, but only while it stays out of a call: a dataset or output path
  may legitimately be named ``ogrinfo``, so ``subprocess.run(["gdalinfo",
  "ogrinfo"])`` is an argv. Deliberately "escapes", not "reaches
  ``subprocess.*``": most argvs here are built in one function and spawned in
  another (``run_gdal(cmd, env=...)``), so a literal ``subprocess.*``
  requirement would blind the gate to the sites it exists for. Two or more
  elements are required for the name-list rule, since ``("gdalinfo",)`` is
  indistinguishable from a bare invocation.
- Comprehensions and generator expressions are binding scopes (fix(#996)),
  so their targets cannot shadow a name used elsewhere in the enclosing
  function. Two carve-outs match Python: the outermost iterable is evaluated
  before the comprehension's scope exists, and a walrus inside a
  comprehension binds in the CONTAINING scope (PEP 572). They remain
  transparent to CLI call-credit, where the question is whether the scope's
  immediate body runs the helper and only def/lambda defer.
- Wrapping is judged lexically, with two execution-order rules (codex round
  6): credit stops at def/lambda boundaries (a callable defined inside a
  wrapped block runs after the context exits), and within one ``with``
  statement only helper items EARLIER than the open's own item count
  (context managers enter left to right). Beyond that, a wrapped open
  passes even if a refactor later moves it into a helper called from
  outside the block. Reviewer territory.
- Helper credit requires the name to be bound to the canonical module by an
  import the resolver understands, resolved through LEXICAL SCOPES
  innermost-first (see ``_scope_info`` / ``_resolve_credit``): a scope that
  rebinds the name (param, assignment, def, non-canonical import, loop or
  with target) kills credit for that scope and everything nested in it. A
  dotted ``import app.processing.raster.vrt`` used without an alias, a
  re-export through an intermediate module, or a name both imported and
  reassigned in one scope is NOT credited — the failure mode is a spurious
  violation prompting a review, never silent credit for a shadow. Class
  bodies are not modeled as scopes, and ``global``/``nonlocal``
  rebinding is not tracked.
- CLI credit stops at the CALL level: the function must actually call the
  canonical ``gdal_safe_env``, but whether that call's RESULT is the env
  passed to the subprocess is not verified. Wiring the returned dict to the
  ``subprocess.run(env=...)`` argument is dataflow analysis — reviewer
  territory, documented, not promised.
- Remote-source detection is LITERAL only (codex round 7): an open or argv
  whose argument is, or obviously leads with, a remote-prefixed string
  literal (http/https, ``/vsicurl*``, hardcoded ``/vsis3``/``/vsiaz``/
  ``/vsigs``) gets no wrapper/safe-env credit, because no GDAL env stops a
  redirect (#937 maintainer decision). A remote URL arriving through a
  VARIABLE is argument provenance — dataflow this gate cannot do. That
  safety does not live here: user-supplied URLs are gated by
  ``validate_url_for_ssrf`` (with ``make_safe_client``'s per-hop
  revalidation on httpx paths) before any fetch, and GDAL fetches are
  constrained by the ``CPL_VSIL_CURL_ALLOWED_EXTENSIONS`` allow-list, per
  AGENTS.md Rule 2 as rewritten for #937.
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The GDAL CLI executables the codebase is KNOWN to spawn today —
# documentation, not the detection predicate. codex round 10 on #974: a
# fixed membership list silently skipped every other family member
# (gdal_rasterize, gdaltindex, ogrlineref, ...), so detection classifies by
# family prefix instead — see _is_gdal_cli_tool. Verified against the tree:
# family matching finds exactly the sites this list's members produce.
GDAL_CLI_TOOLS = {
    "gdalbuildvrt",
    "gdaladdo",
    "gdalwarp",
    "gdal_translate",
    "gdalinfo",
    "ogrinfo",
    "ogr2ogr",
}


# GDAL/OGR utilities whose names match neither family prefix (codex round
# 12). Union'd with the gdal*/ogr* rule below.
GDAL_CLI_EXTRA_TOOLS = frozenset(
    {
        "nearblack",
        "sozip",
        "gnmmanage",
        "gnmanalyse",
        "pct2rgb",
        "pct2rgb.py",
        "rgb2pct",
        "rgb2pct.py",
        "8211view",
        "8211createfromxml",
        "8211dump",
        "s57dump",
        "dgnwritetest",
    }
)


def _gdal_cli_tool_name(value: object) -> str | None:
    """The executable name when a literal argv head names a gdal*/ogr* tool.

    codex round 11 on #974: containers routinely spell the head as a path
    (``/usr/bin/gdalinfo``, ``./bin/ogr2ogr``), which matched neither family
    prefix — normalize to the basename before classifying. The family, not a
    fixed seven (codex round 10).
    """
    if not isinstance(value, str):
        return None
    name = PurePosixPath(value).name or value
    if name.startswith("gdal") or name.startswith("ogr"):
        return name
    if name in GDAL_CLI_EXTRA_TOOLS:
        return name
    return None


SAFE_SUBPROCESS_ENV_HELPER = "gdal_safe_env"
SAFE_OPEN_ENV_HELPER = "gdal_safe_open_env"

# The one module whose definitions of the helpers are canonical. Credit for
# using a helper requires the name to be BOUND to this module (imported from
# it, or used inside it) — a bare tail-match would hand credit to a local
# shadow or an unrelated `something.gdal_safe_open_env()` (codex round 3 on
# #974). Module paths are matched EXACTLY (codex round 9): a suffix match
# credited `from evil.processing.raster.vrt import ...`. The real tree
# imports only the absolute form; relative imports (`from .vrt import ...`)
# are not used and get no credit — the conservative failure direction.
CANONICAL_HELPER_MODULE_REL = "processing/raster/vrt.py"
CANONICAL_HELPER_MODULE = "app.processing.raster.vrt"
CANONICAL_HELPER_PARENT = "app.processing.raster"

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


# Sentinel keys for the credit/detection kinds a name can carry.
_KIND_OPEN = SAFE_OPEN_ENV_HELPER
_KIND_ENV = SAFE_SUBPROCESS_ENV_HELPER
_KIND_MODALIAS = "__vrt_module_alias__"
_KIND_RASTERIO_MOD = "__rasterio_module__"
_KIND_RASTERIO_OPEN = "__rasterio_open__"
_KIND_RASTERIO_ENV = "__rasterio_env__"
# Names an alias chain points at a guarded callable through an expression
# this resolver cannot follow exactly (codex round 12). Calling one is
# UNCLASSIFIED — a violation, never a silent pass.
_KIND_UNSURE = "__unsure_guarded__"

# Kinds an assignment can propagate, and what an attribute of the rasterio
# module resolves to.
_RASTERIO_ATTR_KINDS = {"open": _KIND_RASTERIO_OPEN, "Env": _KIND_RASTERIO_ENV}
_VRT_ATTR_KINDS = {
    SAFE_OPEN_ENV_HELPER: _KIND_OPEN,
    SAFE_SUBPROCESS_ENV_HELPER: _KIND_ENV,
}
_PROPAGATED_KINDS = (
    _KIND_OPEN,
    _KIND_ENV,
    _KIND_MODALIAS,
    _KIND_RASTERIO_MOD,
    _KIND_RASTERIO_OPEN,
    _KIND_RASTERIO_ENV,
    _KIND_UNSURE,
)

_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

# fix(#996): comprehensions and generator expressions are lexical scopes too —
# their targets bind inside them, not in the enclosing function. Kept as a
# separate tuple rather than folded into _SCOPE_NODES because the two are used
# for different questions: _SCOPE_NODES means "a callable whose body runs
# LATER" (the boundary rules in _inside_safe_open_env and _scope_uses_safe_env,
# and the only nodes with a `.args` for _record_params), while _LEXICAL_SCOPES
# means "a scope that owns its own names" (binding resolution).
_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_LEXICAL_SCOPES = (*_SCOPE_NODES, *_COMPREHENSION_NODES)


class _ScopeInfo:
    """Immediate-scope bindings for one function (or the module).

    ``canonical`` maps credit kind -> local names bound to the canonical
    helper/module BY THIS SCOPE'S OWN imports. ``bound`` is every other name
    this scope binds locally (params, assignments, defs, non-canonical
    imports, loop/with targets) — a binding here shadows any outer canonical
    name for the whole scope (codex round 4 on #974: module-wide alias
    collection let one function's import credit another function that had
    rebound the same name)."""

    def __init__(self) -> None:
        self.canonical: dict[str, set[str]] = {
            _KIND_OPEN: set(),
            _KIND_ENV: set(),
            _KIND_MODALIAS: set(),
            _KIND_RASTERIO_MOD: set(),
            _KIND_RASTERIO_OPEN: set(),
            _KIND_RASTERIO_ENV: set(),
            _KIND_UNSURE: set(),
        }
        self.bound: set[str] = set()
        # `from rasterio import *` binds open/Env invisibly (codex round 11).
        self.star_from_rasterio = False
        # name -> value expressions of simple `name = <expr>` assignments in
        # THIS scope (codex round 12: `ropen = rasterio.open` must propagate
        # the binding, not merely shadow it).
        self.assign_values: dict[str, list[ast.expr]] = {}
        # Names bound by anything other than a simple assignment (params,
        # defs, imports, for/with/except targets, augmented assignment...).
        self.other_bound: set[str] = set()


# from-import module -> {imported name -> credit kind}. Names imported from
# these modules under any other name fall through to `bound`.
_FROM_IMPORT_KINDS: dict[str, dict[str, str]] = {
    "rasterio": {"open": _KIND_RASTERIO_OPEN, "Env": _KIND_RASTERIO_ENV},
}


def _record_import_from(info: _ScopeInfo, node: ast.ImportFrom) -> None:
    module = node.module or ""
    # codex round 9: exact module comparison, never a suffix match — a
    # suffix credited `from evil.processing.raster.vrt import ...`. Relative
    # imports (node.level > 0) are not spellings the tree uses; their names
    # fall through to `bound` and earn no credit.
    if node.level == 0 and module == CANONICAL_HELPER_MODULE:
        kinds = {
            SAFE_OPEN_ENV_HELPER: SAFE_OPEN_ENV_HELPER,
            SAFE_SUBPROCESS_ENV_HELPER: SAFE_SUBPROCESS_ENV_HELPER,
        }
    elif node.level == 0 and module == CANONICAL_HELPER_PARENT:
        kinds = {"vrt": _KIND_MODALIAS}
    elif node.level == 0:
        # codex round 5 on #974: `from rasterio import open as ropen` was
        # invisible to the alias-guessing predicate — an unsafe miss.
        kinds = _FROM_IMPORT_KINDS.get(module, {})
    else:
        kinds = {}
    for alias in node.names:
        if alias.name == "*":
            if module == "rasterio":
                info.star_from_rasterio = True
            continue
        kind = kinds.get(alias.name)
        if kind is not None:
            info.canonical[kind].add(alias.asname or alias.name)
        else:
            info.bound.add(alias.asname or alias.name.split(".")[0])


def _record_plain_import(info: _ScopeInfo, node: ast.Import) -> None:
    for alias in node.names:
        if alias.name == CANONICAL_HELPER_MODULE and alias.asname:
            info.canonical[_KIND_MODALIAS].add(alias.asname)
        elif alias.name == "rasterio":
            # codex round 5: `import rasterio as rs` must be tracked as a
            # rasterio-module binding, not guessed from the alias spelling.
            info.canonical[_KIND_RASTERIO_MOD].add(alias.asname or "rasterio")
        elif alias.name.startswith("rasterio.") and not alias.asname:
            # `import rasterio.foo` binds the root `rasterio` name too.
            info.canonical[_KIND_RASTERIO_MOD].add("rasterio")
        else:
            info.bound.add(alias.asname or alias.name.split(".")[0])


def _record_import(info: _ScopeInfo, node: ast.AST) -> None:
    if isinstance(node, ast.ImportFrom) and node.module:
        _record_import_from(info, node)
    elif isinstance(node, ast.Import):
        _record_plain_import(info, node)


def _comprehension_walrus_targets(comp: ast.AST):
    """The ``Name`` targets of walrus operators inside a comprehension.

    PEP 572: ``[(y := f(x)) for x in xs]`` binds ``y`` in the scope CONTAINING
    the comprehension. Nested comprehensions pass their walruses outward the
    same way, so the search descends through them; a nested def or lambda
    owns its own, so it stops there.
    """
    for child in ast.iter_child_nodes(comp):
        if isinstance(child, (*_SCOPE_NODES, ast.ClassDef)):
            continue
        if isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
            # Both: the NamedExpr so _record_assign_targets can propagate its
            # VALUE (fix(#996 review) — `[(ropen := rasterio.open) for _ in x]`
            # must make `ropen` a rasterio alias, not merely a bound name), and
            # the target so _scope_info records the binding itself.
            yield child
            yield child.target
        yield from _comprehension_walrus_targets(child)


def _iter_immediate(node: ast.AST, *, stop_at_comprehensions: bool = True):
    """Yield descendants of ``node`` without entering nested scopes; nested
    scope NODES themselves are yielded (their names bind in this scope).

    fix(#996): comprehensions stop the walk by default, because their targets
    bind in their OWN scope. They did not before, so a function containing
    ``[rasterio for rasterio in tools]`` recorded ``rasterio`` as bound in the
    function and a genuine ``rasterio.open(path)`` elsewhere in that same
    function resolved to _OTHER — an unwrapped open reported as zero opens.

    ``stop_at_comprehensions=False`` keeps the pre-#996 walk for the CLI
    call-credit scan, which asks a different question (does this scope's
    IMMEDIATE body call gdal_safe_env) and where a comprehension body does run
    immediately. Only def/lambda defer, and that boundary is unchanged.
    """
    stop = (
        (*_LEXICAL_SCOPES, ast.ClassDef)
        if stop_at_comprehensions
        else (
            *_SCOPE_NODES,
            ast.ClassDef,
        )
    )
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, stop):
            if isinstance(child, _COMPREHENSION_NODES):
                # fix(#996 review): PEP 572 — a walrus inside a comprehension
                # binds in the CONTAINING scope, not the comprehension's. So
                # the walk stops here for ordinary targets but still hands the
                # enclosing scope its walrus bindings, or
                # `[(rasterio := x) for _ in items]` would leave a genuine
                # rebinding unrecorded.
                yield from _comprehension_walrus_targets(child)
            continue
        yield from _iter_immediate(child, stop_at_comprehensions=stop_at_comprehensions)


def _record_params(info: _ScopeInfo, scope: ast.AST) -> None:
    if not isinstance(scope, _SCOPE_NODES):
        return
    args = scope.args
    for a in (
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *([args.vararg] if args.vararg else []),
        *([args.kwarg] if args.kwarg else []),
    ):
        info.bound.add(a.arg)
        info.other_bound.add(a.arg)


def _record_assign_targets(info: _ScopeInfo, scope: ast.AST) -> set[int]:
    """Record simple ``name = <expr>`` targets, whose bindings PROPAGATE
    (codex round 12) instead of merely shadowing. Returns their node ids."""
    assign_target_nodes: set[int] = set()
    for node in _iter_immediate(scope):
        if isinstance(node, ast.Assign) and all(
            isinstance(t, ast.Name) for t in node.targets
        ):
            for target in node.targets:
                assign_target_nodes.add(id(target))
                info.assign_values.setdefault(target.id, []).append(node.value)
        # fix(#996 review): a walrus binds a value the same way `=` does, and
        # `ropen := rasterio.open` was landing in `bound` as an opaque name, so
        # a later `ropen(path)` resolved to _OTHER and vanished from detection.
        # Covers walruses anywhere in the scope, not only the comprehension
        # ones exported by _comprehension_walrus_targets.
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            assign_target_nodes.add(id(node.target))
            info.assign_values.setdefault(node.target.id, []).append(node.value)
    return assign_target_nodes


def _is_canonical_def(scope: ast.AST, node: ast.AST, rel: str) -> bool:
    """True for the helper definitions inside the canonical module itself."""
    return (
        isinstance(scope, ast.Module)
        and rel == CANONICAL_HELPER_MODULE_REL
        and getattr(node, "name", None)
        in (SAFE_OPEN_ENV_HELPER, SAFE_SUBPROCESS_ENV_HELPER)
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _record_canonical_defs(info: _ScopeInfo, scope: ast.AST, rel: str) -> None:
    if not (isinstance(scope, ast.Module) and rel == CANONICAL_HELPER_MODULE_REL):
        return
    for stmt in scope.body:
        if _is_canonical_def(scope, stmt, rel):
            info.canonical[stmt.name].add(stmt.name)


def _scope_info(scope: ast.AST, rel: str) -> _ScopeInfo:
    cached = getattr(scope, "_rule2_scope_info", None)
    if cached is not None:
        return cached
    info = _ScopeInfo()

    _record_params(info, scope)
    assign_target_nodes = _record_assign_targets(info, scope)
    _record_canonical_defs(info, scope, rel)

    for node in _iter_immediate(scope):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _record_import(info, node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_canonical_def(scope, node, rel):
                info.bound.add(node.name)
                info.other_bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            info.bound.add(node.id)
            if id(node) not in assign_target_nodes:
                info.other_bound.add(node.id)

    # codex round 10 on #974: a name both canonically bound AND rebound in
    # the same scope is left in BOTH sets. The old demotion subtracted it
    # from canonical, which resolved helper credit conservatively but also
    # made a real rasterio.open() through the ambiguous name INVISIBLE to
    # detection — the unsafe direction. _resolve_credit now decides per
    # caller: helper credit treats ambiguous as no-credit, detection treats
    # ambiguous as detected.

    # Cache BEFORE propagation: resolving assignment right-hand sides calls
    # back into _classify_name for this same scope.
    scope._rule2_scope_info = info  # type: ignore[attr-defined]
    _propagate_assignments(info, rel)
    return info


def _assigned_kind(value: ast.expr, rel: str) -> str | None:
    """The binding kind a simple assignment's right-hand side carries.

    Handles ``x = rasterio``, ``x = rasterio.open``, ``x = vrt``,
    ``x = gdal_safe_open_env`` and chains through further simple
    assignments. Anything else that MENTIONS a guarded name resolves to
    ``_KIND_UNSURE`` so calls through the alias flag rather than vanish
    (codex round 12).
    """
    if isinstance(value, ast.Name):
        for kind in _PROPAGATED_KINDS:
            if _classify_name(value.id, kind, value, rel) in (_CANONICAL, _AMBIGUOUS):
                return kind
        return None
    if isinstance(value, ast.Attribute):
        root = _expression_root_name(value.value)
        if root is None:
            return None
        if value.attr in _RASTERIO_ATTR_KINDS and _classify_name(
            root.id, _KIND_RASTERIO_MOD, root, rel
        ) in (_CANONICAL, _AMBIGUOUS):
            return _RASTERIO_ATTR_KINDS[value.attr]
        if value.attr in _VRT_ATTR_KINDS and _classify_name(
            root.id, _KIND_MODALIAS, root, rel
        ) in (_CANONICAL, _AMBIGUOUS):
            return _VRT_ATTR_KINDS[value.attr]
        return None
    # Any other expression that MENTIONS a guarded binding (getattr(rasterio,
    # ...), a ternary, a call returning one) cannot be followed exactly —
    # mark the alias unsure so calling it is a violation, not a silent pass.
    for node in ast.walk(value):
        if isinstance(node, ast.Name):
            for kind in (_KIND_RASTERIO_MOD, _KIND_RASTERIO_OPEN, _KIND_RASTERIO_ENV):
                if _classify_name(node.id, kind, node, rel) in (
                    _CANONICAL,
                    _AMBIGUOUS,
                ):
                    return _KIND_UNSURE
    return None


def _propagate_assignments(info: _ScopeInfo, rel: str) -> None:
    """Resolve ``name = <guarded thing>`` bindings to a fixed point."""
    for _ in range(4):  # chains deeper than this are not worth following
        changed = False
        for name, values in info.assign_values.items():
            kinds = {_assigned_kind(v, rel) for v in values}
            resolved = {k for k in kinds if k is not None}
            if not resolved:
                continue
            kind = _KIND_UNSURE if len(resolved) > 1 else resolved.pop()
            if name in info.canonical[kind]:
                continue
            info.canonical[kind].add(name)
            changed = True
            # A name bound ONLY by propagating assignments is that binding,
            # not a conflicting rebind — do not leave it looking ambiguous.
            if name not in info.other_bound and None not in kinds:
                info.bound.discard(name)
        if not changed:
            return


_CANONICAL = "canonical"
_AMBIGUOUS = "ambiguous"
_OTHER = "other"
_UNRESOLVED = "unresolved"


def _in_signature(
    scope: ast.AST, child: ast.AST, grandchild: ast.AST | None = None
) -> bool:
    """True when ``child`` is the signature part of ``scope`` — a default,
    decorator, or annotation.

    Those expressions evaluate in the ENCLOSING scope, not the new one
    (codex round 11 on #974: ``def f(rasterio=rasterio.open(url))`` consulted
    the new function's params and misresolved the open). Handled as the
    general lexical rule rather than a special case for defaults.

    fix(#996): a comprehension's OUTERMOST iterable is the same shape —
    ``[x for rasterio in rasterio.open(p)]`` evaluates ``rasterio.open(p)`` in
    the enclosing scope, before the comprehension's own scope exists, so the
    target must not shadow it. The path runs through the ``ast.comprehension``
    node, hence ``grandchild``: ``child`` alone cannot tell an iterable
    (enclosing) from a target or an ``if`` clause (comprehension's own).
    """
    if isinstance(scope, _COMPREHENSION_NODES):
        return (
            bool(scope.generators)
            and child is scope.generators[0]
            and grandchild is scope.generators[0].iter
        )
    if not isinstance(scope, _SCOPE_NODES):
        return False
    if child is getattr(scope, "args", None):
        return True
    if child in getattr(scope, "decorator_list", []):
        return True
    return child is getattr(scope, "returns", None)


def _classify_name(name: str, kind: str, usage: ast.AST, rel: str) -> str:
    """Resolve ``name`` at ``usage`` to one of the four classes."""
    prev: ast.AST = usage
    prev_child: ast.AST | None = None
    current = getattr(usage, "_rule2_parent", None)
    while current is not None:
        # fix(#996): _LEXICAL_SCOPES, so a comprehension target resolves in the
        # comprehension rather than leaking into the enclosing function.
        if isinstance(current, (*_LEXICAL_SCOPES, ast.Module)) and not _in_signature(
            current, prev, prev_child
        ):
            info = _scope_info(current, rel)
            if name in info.canonical[kind]:
                return _AMBIGUOUS if name in info.bound else _CANONICAL
            if name in info.bound:
                return _OTHER
        prev_child = prev
        prev = current
        current = getattr(current, "_rule2_parent", None)
    return _UNRESOLVED


def _resolve_credit(
    name: str, kind: str, usage: ast.AST, rel: str, *, ambiguous_counts: bool = False
) -> bool:
    """True when ``name`` at ``usage`` resolves to a canonical binding.

    Walks lexical scopes innermost-first (codex round 4): a scope whose own
    import binds the name canonically grants credit; a scope that rebinds it
    any other way kills credit; otherwise resolution continues outward to
    the module scope.

    codex round 10: a name both canonically bound AND rebound in the same
    scope is ambiguous without statement-order analysis, and the safe answer
    differs by caller. Helper CREDIT must treat ambiguity as no
    (``ambiguous_counts=False``, the default) so a maybe-shadowed helper
    never vouches for anything. rasterio DETECTION must treat ambiguity as
    yes (``ambiguous_counts=True``) so a maybe-rasterio open is flagged
    rather than invisible. Both directions resolve toward a violation.
    """
    cls = _classify_name(name, kind, usage, rel)
    if cls == _CANONICAL:
        return True
    if cls == _AMBIGUOUS:
        return ambiguous_counts
    return False


def _is_canonical_helper_call(expr: ast.expr, helper: str, rel: str) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name):
        return _resolve_credit(func.id, helper, func, rel)
    if isinstance(func, ast.Attribute) and func.attr == helper:
        return isinstance(func.value, ast.Name) and _resolve_credit(
            func.value.id, _KIND_MODALIAS, func, rel
        )
    return False


def _inside_safe_open_env(node: ast.AST, rel: str) -> bool:
    """True when ``node`` executes under an ACTIVE gdal_safe_open_env().

    codex round 6 on #974, two lexical rules:
    - The ancestor walk stops at the first enclosing def/lambda boundary. A
      callable DEFINED inside a wrapped block runs later, when the context
      is gone, so it may not inherit the outer wrapper's credit — the
      nested callable must carry its own (same rule as CLI call-credit).
    - Within a single ``with`` statement, Python enters items left to
      right, so only helper items EARLIER than the item containing the
      open count; ``with rasterio.open(url), gdal_safe_open_env():``
      opens the URL before the env exists. Opens in the with BODY see all
      items.
    """
    prev: ast.AST = node
    current = getattr(node, "_rule2_parent", None)
    while current is not None:
        # codex round 12: stop at the callable boundary for the DEFERRED
        # BODY only. A signature expression (default, decorator, annotation)
        # is evaluated eagerly, while an enclosing `with` is still active,
        # so it keeps that wrapper's credit — the round-11 boundary rule
        # reported such code unwrapped, a false positive.
        if isinstance(current, _SCOPE_NODES) and not _in_signature(current, prev):
            return False
        if isinstance(current, (ast.With, ast.AsyncWith)):
            if isinstance(prev, ast.withitem):
                eligible = current.items[: current.items.index(prev)]
            else:
                eligible = current.items
            for item in eligible:
                if _is_canonical_helper_call(
                    item.context_expr, SAFE_OPEN_ENV_HELPER, rel
                ):
                    return True
        prev = current
        current = getattr(current, "_rule2_parent", None)
    return False


# codex round 7 on #974: gdal_safe_open_env provides NO redirect protection
# (the #937 fact), so wrapper credit must not extend to sources that are
# lexically, obviously remote. A literal /vsis3//vsiaz//vsigs counts too:
# managed-storage paths are always CONSTRUCTED from settings at runtime, so
# a hardcoded literal is by definition outside the managed roots.
_REMOTE_PREFIXES = (
    "http://",
    "https://",
    "/vsicurl",
    "/vsis3/",
    "/vsiaz/",
    "/vsigs/",
)


def _leading_literal(expr: ast.expr) -> str | None:
    """The leftmost string literal of an expression, when one leads it:
    a plain Constant, the first chunk of an f-string, or the left arm of a
    ``+`` concatenation chain."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr) and expr.values:
        first = expr.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _leading_literal(expr.left)
    return None


def _is_remote_literal(expr: ast.expr) -> bool:
    lit = _leading_literal(expr)
    if lit is None:
        return False
    # codex round 8: URL schemes are case-insensitive, so HTTPS:// must be
    # caught — compare those lowercased. The /vsi* prefixes stay exact:
    # GDAL's VSI handler lookup is case-sensitive, so /VSICURL/ would not
    # reach the network in the first place.
    lowered = lit.lower()
    if lowered.startswith(("http://", "https://")):
        return True
    return lit.startswith(tuple(p for p in _REMOTE_PREFIXES if p.startswith("/")))


def _open_source_expr(node: ast.Call) -> ast.expr | None:
    """The source argument of a rasterio.open call: first positional, or the
    ``fp`` keyword (codex round 8: ``rasterio.open(fp="https://...")``
    slipped past a positional-only inspection)."""
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "fp":
            return kw.value
    return None


def _enclosing_function_node(
    node: ast.AST,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = getattr(current, "_rule2_parent", None)
    return None


def _scope_uses_safe_env(root: ast.AST, rel: str) -> bool:
    """True when the scope ITSELF calls the canonical gdal_safe_env.

    codex round 4 on #974: a bare Name reference (assignment, log line, dead
    code) credited the scope while the subprocess ran with a hand-rolled
    env. Credit requires an actual Call whose target resolves to the
    canonical binding. Whether the call's RESULT is the env handed to the
    subprocess is not verified — Call-level is the documented stop.

    codex round 5 on #974: the call must be in the scope's IMMEDIATE body —
    a call inside a nested def or lambda runs on that nested scope's
    schedule (or never), so it may not credit the outer function's argv.

    fix(#996): comprehensions stay transparent here. Only def/lambda defer;
    a list/set/dict comprehension body runs as part of the enclosing
    statement, so a helper call written inside one still credits this scope,
    exactly as it did before #996 made comprehensions binding scopes.
    """
    for node in _iter_immediate(root, stop_at_comprehensions=False):
        if isinstance(node, ast.Call) and _is_canonical_helper_call(
            node, SAFE_SUBPROCESS_ENV_HELPER, rel
        ):
            return True
    return False


UNCLASSIFIED = "unclassified"


def _expression_root_name(expr: ast.expr) -> ast.Name | None:
    """The leftmost ``Name`` an expression is rooted at, if any:
    ``a.b.c`` -> ``a``, ``Path(p).open`` -> ``Path``, ``d[i].open`` -> ``d``."""
    current: ast.expr | None = expr
    while current is not None:
        if isinstance(current, ast.Name):
            return current
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Subscript):
            current = current.value
        else:
            return None
    return None


def _rasterio_call_kind(node: ast.Call, rel: str) -> str | None:
    """Classify a call as ``"open"``/``"Env"``/``UNCLASSIFIED``, else None.

    codex round 5 on #974: the previous predicate GUESSED alias spellings
    ("rasterio" in the name, or "rio"), so `import rasterio as rs` made
    `rs.open(...)` invisible — an unsafe miss, unlike the conservative
    edges. Detection uses per-scope binding resolution: `import rasterio
    [as X]` binds X as the module, `from rasterio import open/Env [as Y]`
    binds Y as the callable.

    codex round 10: ambiguous (bound both ways) resolves to DETECTED.

    codex round 11 — THE INVARIANT: a call that LOOKS like a rasterio
    open/Env by name and that the resolver cannot confidently classify as
    something else is ``UNCLASSIFIED``, which is a violation. Never a silent
    drop. Only two things end detection: a confident non-rasterio binding
    (``Image.open``, ``path.open``, a param, a stdlib import), or a bare
    unbound ``open``/``Env`` name, which can only be the Python builtin —
    rasterio's callables have to be imported to be called bare, and the
    import is exactly what binds them. A ``from rasterio import *`` makes
    even that ambiguous, so it flags too.
    """
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in ("open", "Env"):
        root = _expression_root_name(func.value)
        if root is None:
            # A head this resolver cannot root (literal, lambda call, ...).
            return UNCLASSIFIED
        cls = _classify_name(root.id, _KIND_RASTERIO_MOD, root, rel)
        if cls in (_CANONICAL, _AMBIGUOUS):
            return func.attr
        if cls == _OTHER:
            return None
        return UNCLASSIFIED
    if isinstance(func, ast.Name) and func.id in ("open", "Env"):
        for kind, label in (
            (_KIND_RASTERIO_OPEN, "open"),
            (_KIND_RASTERIO_ENV, "Env"),
        ):
            cls = _classify_name(func.id, kind, func, rel)
            if cls in (_CANONICAL, _AMBIGUOUS):
                return label
        if _star_imports_rasterio(func, rel):
            return UNCLASSIFIED
        return None
    if isinstance(func, ast.Name):
        for kind, label in (
            (_KIND_RASTERIO_OPEN, "open"),
            (_KIND_RASTERIO_ENV, "Env"),
        ):
            if _resolve_credit(func.id, kind, func, rel, ambiguous_counts=True):
                return label
        # An alias whose chain reaches a guarded callable through an
        # expression this resolver cannot follow (codex round 12).
        if _resolve_credit(func.id, _KIND_UNSURE, func, rel, ambiguous_counts=True):
            return UNCLASSIFIED
    return None


def _star_imports_rasterio(usage: ast.AST, rel: str) -> bool:
    """True when any enclosing scope does ``from rasterio import *``, which
    can bind ``open``/``Env`` invisibly."""
    current: ast.AST | None = usage
    while current is not None:
        if isinstance(current, (*_LEXICAL_SCOPES, ast.Module)):
            if _scope_info(current, rel).star_from_rasterio:
                return True
        current = getattr(current, "_rule2_parent", None)
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


def _scan_rasterio_calls(modules: list[tuple[str, ast.Module]]):
    """Walk every module once, returning the raw per-site accounting the
    rasterio checks judge: (unwrapped_counts, unwrapped_lines, remote_sites,
    env_counts, env_lines, unclassified, total_open_calls)."""
    unwrapped_counts: dict[tuple[str, str], int] = {}
    unwrapped_lines: dict[tuple[str, str], list[int]] = {}
    remote_sites: set[tuple[str, str]] = set()
    env_counts: dict[tuple[str, str], int] = {}
    env_lines: dict[tuple[str, str], list[int]] = {}
    unclassified: list[str] = []
    total_open_calls = 0

    for rel, tree in modules:
        _annotate_parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kind = _rasterio_call_kind(node, rel)
            if kind == "open":
                total_open_calls += 1
                site = (rel, _enclosing_function(node))
                # codex round 7 on #974: a lexically remote source gets NO
                # wrapper credit — gdal_safe_open_env carries no redirect
                # protection (#937), so wrapping a remote open proves
                # nothing. It must be allowlisted with its own review.
                # codex round 8: the source may arrive as the fp keyword.
                source = _open_source_expr(node)
                remote = source is not None and _is_remote_literal(source)
                if not remote and _inside_safe_open_env(node, rel):
                    continue
                if remote:
                    remote_sites.add(site)
                unwrapped_counts[site] = unwrapped_counts.get(site, 0) + 1
                unwrapped_lines.setdefault(site, []).append(node.lineno)
            elif kind == "Env":
                site = (rel, _enclosing_function(node))
                env_counts[site] = env_counts.get(site, 0) + 1
                env_lines.setdefault(site, []).append(node.lineno)
            elif kind is UNCLASSIFIED:
                # THE INVARIANT (codex round 11): unclassifiable is a
                # violation, never a silent pass.
                unclassified.append(
                    f"{rel}:{node.lineno} ({_enclosing_function(node)}) calls "
                    "something named open/Env that this guard cannot resolve "
                    "to a definite binding — make the binding obvious (import "
                    "rasterio normally, or name the object) so the gate can "
                    "classify it; unclassifiable is a violation by "
                    "construction (AGENTS.md Rule 2, #936)"
                )

    return (
        unwrapped_counts,
        unwrapped_lines,
        remote_sites,
        env_counts,
        env_lines,
        unclassified,
        total_open_calls,
    )


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
    scan = _scan_rasterio_calls(modules)
    (
        unwrapped_counts,
        unwrapped_lines,
        remote_sites,
        env_counts,
        env_lines,
        unclassified,
        total_open_calls,
    ) = scan
    violations: list[str] = list(unclassified)

    violations += _blank_justification_violations(
        "RASTERIO_OPEN_ALLOWLIST", open_allowlist
    )
    violations += _blank_justification_violations(
        "RASTERIO_ENV_ALLOWLIST", env_allowlist
    )

    for site, count in sorted(unwrapped_counts.items()):
        rel, func = site
        lines = ",".join(str(n) for n in unwrapped_lines[site])
        if site not in open_allowlist:
            if site in remote_sites:
                violations.append(
                    f"{rel}:{lines} ({func}) opens a literally-remote source "
                    "with rasterio — wrapper credit does not apply because "
                    f"{SAFE_OPEN_ENV_HELPER} provides no redirect protection "
                    "(#937); route the URL through validate_url_for_ssrf at "
                    "the API layer and allowlist the site with a "
                    "justification (AGENTS.md Rule 2, #936)"
                )
            else:
                violations.append(
                    f"{rel}:{lines} ({func}) calls rasterio.open outside "
                    f"`with {SAFE_OPEN_ENV_HELPER}():` — wrap it, or allowlist "
                    "it here with a justification (AGENTS.md Rule 2, #936)"
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


def _tool_name_list(node: ast.List | ast.Tuple) -> bool:
    """True for a literal that is a SET OF TOOL NAMES, not a command vector.

    fix(#996): ``SUPPORTED_TOOLS = ["gdalinfo", "ogrinfo"]`` used to trip the
    gate, and the only ways out were a misleading allowlist entry or a
    pointless call to the env helper. A command's non-head elements are flags,
    paths or variables; they are never further GDAL utility names.

    Two or more elements required. ``("gdalinfo",)`` is indistinguishable from
    a bare invocation, so a single-element literal stays a command vector.
    """
    return len(node.elts) >= 2 and all(
        isinstance(elt, ast.Constant) and _gdal_cli_tool_name(elt.value)
        for elt in node.elts
    )


def _scope_root(node: ast.AST) -> ast.AST | None:
    """The nearest enclosing callable or module — where a local name lives."""
    current: ast.AST | None = getattr(node, "_rule2_parent", None)
    while current is not None:
        if isinstance(current, (*_SCOPE_NODES, ast.Module)):
            return current
        current = getattr(current, "_rule2_parent", None)
    return None


# How far a literal's value travels out of the expression it sits in. Ordered:
# a call subsumes a return, because a call is the one that can end at an exec.
_ESCAPE_NONE = 0
_ESCAPE_RETURN = 1
_ESCAPE_CALL = 2


def _escape_kind(node: ast.AST, *, vector: bool = True) -> int:
    """How ``node``'s value leaves the expression it is written in.

    ``vector`` says whether ``node``'s value IS the command vector, rather than
    a container that holds it. It decides only the subscript rule below:
    ``cmd[0]`` yields a string, but ``commands["inspect"]`` yields the argv.

    ``_ESCAPE_CALL`` — handed to a call (``subprocess.run([...])``,
    ``run_gdal(cmd)``, ``out.append(cmd)``). ``_ESCAPE_RETURN`` — returned or
    yielded, which still reaches a caller that may spawn it, so a helper that
    BUILDS an argv and hands it back is covered. ``_ESCAPE_NONE`` — the value
    stays inside this scope.
    """
    best = _ESCAPE_NONE
    prev: ast.AST = node
    current: ast.AST | None = getattr(node, "_rule2_parent", None)
    while current is not None:
        # fix(#996 review): `cmd[0]` yields a STRING, so `return cmd[0]` and
        # `consume(cmd[0])` move an element, not the command vector. A slice
        # still yields a sequence that could be spawned, so only a single
        # index stops the walk.
        if (
            vector
            and isinstance(current, ast.Subscript)
            and prev is current.value
            and not isinstance(current.slice, ast.Slice)
        ):
            return best
        # Stepping out through a container means everything above holds the
        # vector rather than being it, so a subscript up there yields the argv.
        if isinstance(current, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            vector = False
        # The callee itself is not an argument: `cmd.index(x)` reads the list,
        # it does not hand it anywhere. Anything else inside a Call counts.
        if isinstance(current, ast.Call) and prev is not current.func:
            return _ESCAPE_CALL
        if isinstance(current, (ast.Return, ast.Yield, ast.YieldFrom)):
            best = max(best, _ESCAPE_RETURN)
        if isinstance(current, (*_SCOPE_NODES, ast.Module)):
            return best
        prev = current
        current = getattr(current, "_rule2_parent", None)
    return best


def _positional_targets(targets: list[ast.expr], index: int) -> list[ast.expr] | None:
    """The targets an unpacking assigns position ``index`` to, or None.

    fix(#996 review): binding every target name to every nested literal made
    ``ignored, choices = (None, ["gdalinfo", "-json"])`` read ``choices`` as
    escaping through ``ignored``, a false positive on inert data — the class of
    failure this whole issue is about. Positions are matched instead.

    ALL matching targets, because chained unpacking (``a, b = c, d = (...)``)
    binds the same position twice and returning only the first dropped the
    second. None when no target is a flat same-shape sequence, or when a
    starred element makes positions ambiguous — the caller then falls back to
    the conservative all-names answer.
    """
    matched: list[ast.expr] = []
    saw_sequence = False
    for target in targets:
        if not isinstance(target, (ast.Tuple, ast.List)):
            continue
        saw_sequence = True
        if any(isinstance(e, ast.Starred) for e in target.elts):
            return None
        if index < len(target.elts):
            matched.append(target.elts[index])
    return matched if (saw_sequence and matched) else None


# Expression wrappers a value passes through without being consumed. A literal
# inside one is still the value the surrounding statement binds or hands on.
_TRANSPARENT_WRAPPERS = (
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Starred,
    # fix(#996 review): `cmd = [...] if flag else [...]` and `[...] + extra`
    # both stopped the climb short of the assignment, so a real invocation read
    # as inert.
    ast.IfExp,
    ast.BinOp,
)


def _binding_targets(node: ast.AST) -> tuple[set[str], bool]:
    """Names this literal's value is reachable through in its own scope.

    Climbs out of transparent wrappers first (fix(#996 review)), so
    ``commands = {"inspect": ["gdalinfo", path]}`` binds through ``commands``
    and a later ``subprocess.run(commands["inspect"])`` still counts. Covers
    ``=`` including unpacking, annotated ``=``, the walrus, and the loop target
    of a ``for``/``async for``/comprehension over a literal.

    Returns ``(names, holds_a_container)``. The flag tells the caller whether
    those names refer to the command vector itself or to something wrapping
    it, which changes what a subscript on them means.
    """
    current: ast.AST = node
    parent = getattr(current, "_rule2_parent", None)
    index_in_parent: int | None = None
    climbed = False
    while isinstance(parent, _TRANSPARENT_WRAPPERS):
        climbed = True
        if isinstance(parent, (ast.Tuple, ast.List)) and current in parent.elts:
            index_in_parent = parent.elts.index(current)
        else:
            index_in_parent = None
        current = parent
        parent = getattr(current, "_rule2_parent", None)

    if isinstance(parent, ast.Assign) and parent.value is current:
        if index_in_parent is not None:
            positional = _positional_targets(parent.targets, index_in_parent)
            if positional is not None:
                return {
                    n.id
                    for target in positional
                    for n in ast.walk(target)
                    if isinstance(n, ast.Name)
                }, climbed
        return {
            n.id
            for target in parent.targets
            for n in ast.walk(target)
            if isinstance(n, ast.Name)
        }, climbed
    if (
        isinstance(parent, (ast.AnnAssign, ast.NamedExpr))
        and parent.value is current
        and isinstance(parent.target, ast.Name)
    ):
        return {parent.target.id}, climbed
    # fix(#996 review): `for cmd in (["gdalinfo", path],): subprocess.run(cmd)`
    # reaches an exec through the loop target. Same for `async for` and for a
    # comprehension's generator.
    #
    # Only when the literal is an ELEMENT of the iterable, which is what
    # `climbed` records. `for tool in ["gdalinfo", "ogrinfo"]` binds each
    # STRING to the target, not the list, and treating the list as escaping
    # through it flagged ordinary tool-name data.
    if (
        climbed
        and isinstance(parent, (ast.For, ast.AsyncFor, ast.comprehension))
        and parent.iter is current
    ):
        # The loop target receives an ELEMENT of the iterable, so it is the
        # vector itself, not a container of it.
        return {n.id for n in ast.walk(parent.target) if isinstance(n, ast.Name)}, False
    return set(), False


def _use_reaches_the_binding(used: ast.Name, scope: ast.AST, rel: str) -> bool:
    """True when ``used`` is the scope's binding rather than a nested shadow.

    fix(#996 review): the escape search walks the whole scope, so a nested
    ``def inner(cmd): consume(cmd)`` counted as a use of an outer ``cmd`` and
    turned an inert constant into a security failure. Any lexical scope between
    the use and the binding that binds the same name breaks the link -- the
    same rule ``_classify_name`` applies to rasterio names.

    ``bound`` is not the whole binding table: a canonical import
    (``from rasterio import open as cmd``) is recorded in ``canonical``
    instead, and reading only ``bound`` missed that shadow.
    """
    current: ast.AST | None = getattr(used, "_rule2_parent", None)
    while current is not None and current is not scope:
        if isinstance(current, _LEXICAL_SCOPES):
            info = _scope_info(current, rel)
            if used.id in info.bound or any(
                used.id in names for names in info.canonical.values()
            ):
                return False
        current = getattr(current, "_rule2_parent", None)
    return True


def _argv_escape_kind(node: ast.List | ast.Tuple, rel: str) -> int:
    """The strongest escape a GDAL-headed literal reaches, its bindings included.

    fix(#996): the gate used to treat ANY GDAL-headed sequence as a command
    vector, so plain data tripped a security gate. A literal is a command when
    its value goes somewhere — directly, or through a name it is bound to
    (``cmd = ["ogrinfo", ...]`` ... ``create_subprocess_exec(*cmd, ...)``,
    which is the shape most of this codebase uses).

    Deliberately "escapes", not "reaches ``subprocess.*``". Half the real
    argvs in ``app/`` are built at one level and spawned at another —
    ``run_gdal(cmd, env=...)`` wraps ``subprocess.run`` in
    ``processing/raster/vrt.py`` — so a literal ``subprocess.*`` requirement
    would blind the gate to exactly the sites it exists for.
    """
    best = _escape_kind(node)
    if best == _ESCAPE_CALL:
        return best
    names, holds_container = _binding_targets(node)
    scope = _scope_root(node)
    if not names or scope is None:
        return best

    # fix(#996 review): follow re-aliasing to a fixed point. `cmd = [...]`,
    # `alias = cmd`, `subprocess.run(alias)` reaches an exec through a name the
    # literal was never directly bound to, and stopping at the first hop lost
    # it — a regression against the pre-#996 scan, which flagged everything.
    seen: set[str] = set()
    pending = {(n, holds_container) for n in names}
    while pending:
        current_batch = pending
        pending = set()
        seen |= {n for n, _ in current_batch}
        current_names = {n: c for n, c in current_batch}
        for used in ast.walk(scope):
            if not (
                isinstance(used, ast.Name)
                and used.id in current_names
                and isinstance(used.ctx, ast.Load)
                and _use_reaches_the_binding(used, scope, rel)
            ):
                continue
            best = max(best, _escape_kind(used, vector=not current_names[used.id]))
            if best == _ESCAPE_CALL:
                return best
            aliases, alias_container = _binding_targets(used)
            pending |= {
                (n, current_names[used.id] or alias_container) for n in aliases - seen
            }
    return best


def _use_reaches_the_binding(used: ast.Name, scope: ast.AST, rel: str) -> bool:
    """True when ``used`` is the scope's binding rather than a nested shadow.

    fix(#996 review): the escape search walks the whole scope, so a nested
    ``def inner(cmd): consume(cmd)`` counted as a use of an outer ``cmd`` and
    turned an inert constant into a security failure. Any lexical scope between
    the use and the binding that binds the same name breaks the link -- the
    same rule ``_classify_name`` applies to rasterio names.

    ``bound`` is not the whole binding table: a canonical import
    (``from rasterio import open as cmd``) is recorded in ``canonical``
    instead, and reading only ``bound`` missed that shadow.
    """
    current: ast.AST | None = getattr(used, "_rule2_parent", None)
    while current is not None and current is not scope:
        if isinstance(current, _LEXICAL_SCOPES):
            info = _scope_info(current, rel)
            if used.id in info.bound or any(
                used.id in names for names in info.canonical.values()
            ):
                return False
        current = getattr(current, "_rule2_parent", None)
    return True


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
    remote_keys: set[tuple[str, str, str]] = set()
    unsafe_lines: dict[tuple[str, str, str], list[int]] = {}

    violations += _blank_justification_violations("GDAL_CLI_CALL_ALLOWLIST", allowlist)

    for rel, tree in modules:
        _annotate_parents(tree)
        for node in ast.walk(tree):
            # codex round 9: tuples build argv vectors just as well as lists
            # (subprocess.run(("gdalinfo", url))) — match both.
            if not (isinstance(node, (ast.List, ast.Tuple)) and node.elts):
                continue
            first = node.elts[0]
            tool_name = (
                _gdal_cli_tool_name(first.value)
                if isinstance(first, ast.Constant)
                else None
            )
            if tool_name is None:
                continue
            # fix(#996): a GDAL-looking sequence is only a command vector if
            # it is one. Flagging plain data was a false positive that blocked
            # correct code and offered only misleading ways out.
            escape = _argv_escape_kind(node, rel)
            if escape == _ESCAPE_NONE:
                continue  # inert: the value never leaves, so it cannot execute
            if escape != _ESCAPE_CALL and _tool_name_list(node):
                # A tool-NAME list that is only returned is a choices helper.
                # fix(#996 review): the exemption stops at _ESCAPE_CALL. A
                # literal handed into a call is a plausible argv whatever it
                # contains — a dataset or output path may legitimately be
                # named `ogrinfo` — and shape alone cannot tell the two apart.
                continue
            total_argv_sites += 1
            func_node = _enclosing_function_node(node)
            func_name = func_node.name if func_node is not None else "<module>"
            scope: ast.AST = func_node if func_node is not None else tree
            # codex round 7 on #974: an argv carrying a literally-remote
            # element gets no safe-env credit — the safe env cannot stop a
            # redirect (#937), so the site needs its own reviewed entry.
            remote = any(_is_remote_literal(elt) for elt in node.elts[1:])
            if not remote and _scope_uses_safe_env(scope, rel):
                continue
            key = (rel, func_name, tool_name)
            if remote:
                remote_keys.add(key)
            unsafe_counts[key] = unsafe_counts.get(key, 0) + 1
            unsafe_lines.setdefault(key, []).append(node.lineno)

    for key, count in sorted(unsafe_counts.items()):
        rel, func_name, tool = key
        lines = ",".join(str(n) for n in unsafe_lines[key])
        if key not in allowlist:
            if key in remote_keys:
                violations.append(
                    f"{rel}:{lines} ({func_name}) builds a {tool} argv with a "
                    "literally-remote element — safe-env credit does not "
                    "apply because no GDAL env stops a redirect (#937); gate "
                    "the URL with validate_url_for_ssrf and allowlist this "
                    "exact (module, function, tool) with a justification "
                    "(AGENTS.md Rule 2, #936)"
                )
            else:
                violations.append(
                    f"{rel}:{lines} ({func_name}) builds a {tool} argv without "
                    f"{SAFE_SUBPROCESS_ENV_HELPER} in the same function — "
                    "route the subprocess env through it, or allowlist this "
                    "exact (module, function, tool) with a justification "
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


def test_guard_scope_shadow_kills_credit_only_where_shadowed():
    """codex round 4: a module-level canonical alias must not credit a
    function that REBINDS the same name locally, while the clean sibling
    function keeps its credit."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env as guard\n"
            "def clean(path):\n"
            "    with guard():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
            "def shadowed(path, fake):\n"
            "    guard = fake\n"
            "    with guard():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 1, violations
    assert "shadowed" in violations[0]


def test_guard_cli_reference_without_call_gets_no_credit():
    """codex round 4: a bare reference to gdal_safe_env (assignment, log
    line, dead code) must not credit an unclamped argv; an actual call to
    the canonical binding must."""
    violations, _ = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def mentions_only(url):\n"
            "    helper = gdal_safe_env\n"
            "    return ['ogrinfo', '-json', url], helper\n"
            "def actually_calls(url):\n"
            "    env = gdal_safe_env()\n"
            "    return ['ogrinfo', '-json', url], env\n"
        ),
        {},
    )
    assert len(violations) == 1, violations
    assert "mentions_only" in violations[0]


def test_guard_rasterio_alias_and_from_import_are_detected():
    """codex round 5: `import rasterio as rs` / `from rasterio import open`
    previously slipped past the alias-guessing predicate — an unsafe miss.
    Both forms must be flagged when unwrapped."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio as rs\n"
            "from rasterio import open as ropen, Env as REnv\n"
            "def a(path):\n"
            "    with rs.open(path):\n"
            "        pass\n"
            "def b(path):\n"
            "    with ropen(path):\n"
            "        pass\n"
            "def c():\n"
            "    return REnv(X='1')\n"
        ),
        {},
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 3, violations
    assert any("(a)" in v for v in violations)
    assert any("(b)" in v for v in violations)
    assert any("rasterio.Env" in v and "(c)" in v for v in violations)


def test_guard_unrelated_rs_name_is_not_rasterio():
    """The flip side of binding-based detection: a name that merely looks
    rasterio-ish but is bound elsewhere must not be flagged."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import riostyle as rio\n"
            "def fn(path):\n"
            "    with rio.open(path):\n"
            "        pass\n"
        ),
        {},
        {},
    )
    assert total == 0
    assert violations == []


def test_guard_nested_call_does_not_credit_outer_argv():
    """codex round 5: a canonical gdal_safe_env call inside a NESTED def or
    lambda must not credit the outer function's argv; a same-scope call
    still does."""
    violations, _ = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def outer_nested(url):\n"
            "    def inner():\n"
            "        return gdal_safe_env()\n"
            "    return ['ogrinfo', '-json', url], inner\n"
            "def outer_direct(url):\n"
            "    env = gdal_safe_env()\n"
            "    return ['ogrinfo', '-json', url], env\n"
        ),
        {},
    )
    assert len(violations) == 1, violations
    assert "outer_nested" in violations[0]
    # The nested def's own argv (if any) is judged in ITS scope, where the
    # call does live — pin that the inner scope still earns its own credit.
    inner_ok, _ = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def outer(url):\n"
            "    def inner():\n"
            "        env = gdal_safe_env()\n"
            "        return ['ogrinfo', '-json', url], env\n"
            "    return inner\n"
        ),
        {},
    )
    assert inner_ok == []


def test_guard_deferred_callable_inside_wrapper_gets_no_credit():
    """codex round 6: a def/lambda DEFINED inside a wrapped block runs after
    the context exits, so its rasterio.open may not inherit the outer
    wrapper's credit."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def outer(paths):\n"
            "    with gdal_safe_open_env():\n"
            "        def deferred(p):\n"
            "            with rasterio.open(p):\n"
            "                pass\n"
            "        later = lambda p: rasterio.open(p)\n"
            "    return deferred, later\n"
        ),
        {},
        {},
    )
    assert len(violations) == 2, violations
    assert any("(deferred)" in v for v in violations)
    # The lambda's enclosing named function is what the site reports.
    assert any("rasterio.open" in v for v in violations)


def test_guard_with_item_order_decides_credit():
    """codex round 6: context managers enter left to right, so a helper
    LATER in the same with-statement must not credit an earlier open; the
    canonical helper-first shape still passes."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def wrong(path):\n"
            "    with rasterio.open(path), gdal_safe_open_env():\n"
            "        pass\n"
            "def right(path):\n"
            "    with gdal_safe_open_env(), rasterio.open(path):\n"
            "        pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 1, violations
    assert "(wrong)" in violations[0]


def test_guard_remote_literal_open_gets_no_wrapper_credit():
    """codex round 7: gdal_safe_open_env stops no redirect (#937), so a
    wrapped open of a literally-remote source must still be flagged — plain
    literal and f-string forms both."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def literal():\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open('https://example.com/a.tif'):\n"
            "            pass\n"
            "def fstring(host):\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(f'https://{host}/b.tif'):\n"
            "            pass\n"
            "def local(path):\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 2, violations
    assert all("literally-remote" in v and "#937" in v for v in violations)
    assert any("(literal)" in v for v in violations)
    assert any("(fstring)" in v for v in violations)


def test_guard_remote_literal_argv_gets_no_safe_env_credit():
    """codex round 7, CLI side: a safe-env call cannot credit an argv that
    carries a remote-prefixed literal element."""
    violations, _ = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def remote():\n"
            "    env = gdal_safe_env()\n"
            "    return ['gdalinfo', '/vsicurl/https://example.com/a.tif'], env\n"
            "def managed(path):\n"
            "    env = gdal_safe_env()\n"
            "    return ['gdalinfo', path], env\n"
        ),
        {},
    )
    assert len(violations) == 1, violations
    assert "(remote)" in violations[0] and "literally-remote" in violations[0]


def test_guard_remote_fp_keyword_and_uppercase_scheme_are_caught():
    """codex round 8: the remote check must also see the fp keyword form
    and case-varied URL schemes; a hand-written /VSICURL/ literal stays
    uncredited-but-local because GDAL's VSI lookup is case-sensitive and
    would never reach the network."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def kw():\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(fp='https://example.com/a.tif'):\n"
            "            pass\n"
            "def upper():\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open('HTTPS://example.com/b.tif'):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 2, violations
    assert any("(kw)" in v and "literally-remote" in v for v in violations)
    assert any("(upper)" in v and "literally-remote" in v for v in violations)


def test_guard_tuple_argv_is_detected():
    """codex round 9: a tuple argv (subprocess.run(("gdalinfo", url))) must
    be judged exactly like a list argv."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\ndef runs(url):\n    subprocess.run(('gdalinfo', url))\n"
        ),
        {},
    )
    assert total == 1
    assert len(violations) == 1 and "(runs)" in violations[0]


def test_guard_evil_prefixed_module_gets_no_credit():
    """codex round 9: module paths compare exactly — a suffix match credited
    from evil.processing.raster.vrt import gdal_safe_open_env."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from evil.processing.raster.vrt import gdal_safe_open_env\n"
            "def fn(path):\n"
            "    with gdal_safe_open_env():\n"
            "        with rasterio.open(path):\n"
            "            pass\n"
        ),
        {},
        {},
    )
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_import_then_reassign_open_is_detected_not_invisible():
    """codex round 10: the old demotion made a rasterio.open through an
    imported-then-rebound name invisible (not flagged, not counted) — the
    unsafe direction. Ambiguity must classify as a violation."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path):\n"
            "    with rasterio.open(path):\n"
            "        pass\n"
            "rasterio = None\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_gdal_family_tool_is_detected():
    """codex round 10: any gdal*/ogr* executable is a GDAL CLI — a fixed
    seven-name list skipped gdal_rasterize, gdaltindex, ogrlineref, ..."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def rasterize(url):\n"
            "    subprocess.run(['gdal_rasterize', url, 'out.tif'])\n"
        ),
        {},
    )
    assert total == 1
    assert len(violations) == 1 and "(rasterize)" in violations[0]
    assert "gdal_rasterize" in violations[0]


def test_guard_signature_expression_open_is_detected():
    """codex round 11: defaults, decorators, and annotations evaluate in the
    ENCLOSING scope. The walk used to consult the new function's params
    first, so def f(rasterio=rasterio.open(url)) was neither counted nor
    rejected — invisible, the failure class the invariant forbids."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(rasterio=rasterio.open('https://example.com/a.tif')):\n"
            "    return rasterio\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "literally-remote" in violations[0]


def test_guard_unclassifiable_call_is_a_violation():
    """THE INVARIANT (codex round 11): a call the resolver cannot classify —
    here an .open() on a name bound nowhere it can see — is reported, never
    dropped. The sibling call on a confidently-bound non-rasterio object
    stays silent, so the invariant costs no false alarms on normal code."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "from PIL import Image\n"
            "def unresolvable(url):\n"
            "    return mystery.open(url)\n"
            "def fine(path):\n"
            "    return Image.open(path)\n"
        ),
        {},
        {},
    )
    assert len(violations) == 1, violations
    assert "(unresolvable)" in violations[0]
    assert "cannot resolve" in violations[0]


def test_guard_path_qualified_argv_head_is_detected():
    """codex round 11: containers spell the executable as a path; the head
    normalizes to its basename before family classification."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def runs(url):\n"
            "    subprocess.run(['/usr/bin/gdalinfo', url])\n"
            "    subprocess.run(['./bin/ogr2ogr', 'out.gpkg', url])\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 2, violations
    assert any("gdalinfo" in v for v in violations)
    assert any("ogr2ogr" in v for v in violations)


def test_guard_alias_assignment_propagates_the_binding():
    """codex round 12: `ropen = rasterio.open; ropen(url)` recorded only a
    generic bound name, so the call was invisible — a silent-pass path
    reachable by renaming, which falsified the module invariant. Aliases
    propagate now, including module aliases and chains."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "ropen = rasterio.open\n"
            "rs = rasterio\n"
            "rs2 = rs\n"
            "def direct(url):\n"
            "    return ropen(url)\n"
            "def chained(url):\n"
            "    return rs2.open(url)\n"
        ),
        {},
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 2, violations
    assert any("(direct)" in v for v in violations)
    assert any("(chained)" in v for v in violations)


def test_guard_unfollowable_alias_is_unclassified_not_invisible():
    """An alias built through an expression the resolver cannot follow must
    land on the UNCLASSIFIED side rather than vanish."""
    violations, _ = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "opener = getattr(rasterio, 'open')\n"
            "def fn(url):\n"
            "    return opener(url)\n"
        ),
        {},
        {},
    )
    assert len(violations) == 1, violations
    assert "cannot resolve" in violations[0] and "(fn)" in violations[0]


def test_guard_signature_default_keeps_enclosing_wrapper_credit():
    """codex round 12: a default is evaluated eagerly, while an enclosing
    `with gdal_safe_open_env():` is still active, so it IS protected. The
    round-11 boundary rule reported it unwrapped — a false positive that
    would have blocked correct code. The deferred BODY still gets no
    credit."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "from app.processing.raster.vrt import gdal_safe_open_env\n"
            "def outer(path):\n"
            "    with gdal_safe_open_env():\n"
            "        def eager(src=rasterio.open(path)):\n"
            "            return rasterio.open(path)\n"
            "        return eager\n"
        ),
        {},
        {},
    )
    assert total == 2, (total, violations)
    # Only the deferred body call is reported; the default keeps its credit.
    assert len(violations) == 1, violations
    assert "(eager)" in violations[0]


def test_guard_non_prefixed_gdal_utilities_are_detected():
    """codex round 12: GDAL ships utilities matching neither family prefix
    (nearblack, sozip, gnmmanage, ...)."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    subprocess.run(['nearblack', path])\n"
            "    subprocess.run(['/usr/bin/sozip', path])\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 2, violations
    assert any("nearblack" in v for v in violations)
    assert any("sozip" in v for v in violations)


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


# ---------------------------------------------------------------------------
# fix(#996): the two resolution edges #936/#974 merged with open.
# ---------------------------------------------------------------------------


def test_guard_gdal_named_constant_that_never_runs_is_not_an_argv():
    """A constant listing tool NAMES is data, not a command vector.

    The false positive #996 was filed for: a contributor adding
    ``SUPPORTED_TOOLS = ["gdalinfo", "ogrinfo"]``, or a function returning UI
    choices, got a security failure whose only exits were a misleading
    allowlist entry or a pointless call to the env helper.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            'SUPPORTED_TOOLS = ["gdalinfo", "ogrinfo"]\n'
            "def choices():\n"
            '    return ("gdalwarp", "gdal_translate")\n'
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_tool_name_list_handed_to_a_call_is_still_an_argv():
    """fix(#996 review): the tool-name-list exemption stops at a call.

    A dataset or output path may legitimately be named ``ogrinfo``, so
    ``subprocess.run(["gdalinfo", "ogrinfo"])`` is a real invocation and shape
    alone cannot tell it from a choices constant. Returning one is still
    exempt (the test above); passing one into a call is not.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn():\n"
            "    subprocess.run(['gdalinfo', 'ogrinfo'])\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_argv_inside_a_container_or_walrus_is_still_detected():
    """fix(#996 review): escape analysis follows a literal out of the
    container it is nested in, and through a walrus binding. Both shapes
    reach an exec while being bound to nothing directly."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def via_container(path):\n"
            "    commands = {'inspect': ['gdalinfo', path]}\n"
            "    subprocess.run(commands['inspect'])\n"
            "def via_walrus(path):\n"
            "    subprocess.run(cmd := ['ogrinfo', path])\n"
            "def via_walrus_then_used(path):\n"
            "    if (cmd2 := ['gdalwarp', path]):\n"
            "        subprocess.run(cmd2)\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert len(violations) == 3, violations
    assert any("(via_container)" in v for v in violations)
    assert any("(via_walrus)" in v for v in violations)
    assert any("(via_walrus_then_used)" in v for v in violations)


def test_guard_inert_gdal_headed_literal_is_not_an_argv():
    """A GDAL-headed literal that is never handed anywhere cannot execute.

    The exemption is narrow on purpose. The literal here is only subscripted
    and compared; hand it to ANY call, return it, or yield it and it is a
    command vector again, because each of those can end at an exec and this
    gate does not follow values across scopes.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            'DEFAULT_ARGS = ["gdalinfo", "-json"]\n'
            "def label():\n"
            "    head = DEFAULT_ARGS[0]\n"
            "    if head == 'gdalinfo':\n"
            "        pass\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_inert_literal_becomes_an_argv_once_it_is_returned():
    """The negative control for the test above: the same literal, returned."""
    violations, total = _collect_gdal_cli_violations(
        _mod("def build(url):\n    return ['gdalinfo', '-json', url]\n"),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(build)" in violations[0]


def test_guard_argv_that_reaches_a_subprocess_still_trips():
    """The negative control for the exemption above: all three real spawn
    shapes are still detected — the literal passed straight into a call, the
    local splatted into ``create_subprocess_exec``, and the local handed to a
    wrapper that owns the ``subprocess.run`` (``run_gdal`` in
    ``processing/raster/vrt.py``, which is how most of app/ spawns GDAL)."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import asyncio\n"
            "import subprocess\n"
            "def direct(path):\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def splatted(path):\n"
            "    cmd = ['ogrinfo', '-so', path]\n"
            "    return asyncio.create_subprocess_exec(*cmd)\n"
            "def through_wrapper(path):\n"
            "    cmd = ['gdalwarp', path]\n"
            "    return run_gdal(cmd, env={}, tool='gdalwarp')\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert len(violations) == 3, violations
    assert any("(direct)" in v for v in violations)
    assert any("(splatted)" in v for v in violations)
    assert any("(through_wrapper)" in v for v in violations)


def test_guard_single_element_tool_literal_is_still_an_argv():
    """``["ogrinfo"]`` is indistinguishable from a bare invocation, so the
    tool-name-list exemption requires two or more elements."""
    violations, total = _collect_gdal_cli_violations(
        _mod("import subprocess\ndef fn():\n    subprocess.run(['ogrinfo'])\n"),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comprehension_target_does_not_blind_a_sibling_open():
    """A comprehension target binds in the comprehension, not the function.

    It used to land in the enclosing function's binding table, so a genuine
    module-imported ``rasterio.open(path)`` elsewhere in the SAME function
    resolved to _OTHER and the collector reported zero opens — a failure in
    the unsafe direction.
    """
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path, tools):\n"
            "    names = [rasterio for rasterio in tools]\n"
            "    return rasterio.open(path), names\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comprehension_outer_iterable_resolves_in_the_enclosing_scope():
    """The outermost iterable evaluates BEFORE the comprehension's scope
    exists, so its own target cannot shadow the name it is built from."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path):\n"
            "    return [x for rasterio in rasterio.open(path)]\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comprehension_target_still_shadows_inside_the_comprehension():
    """The other direction of the same rule: within the comprehension body the
    target really does shadow, so a call through it is not a rasterio open.
    Without this the scope split would only have moved the error."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(tools):\n"
            "    return [rasterio.open('x') for rasterio in tools]\n"
        ),
        {},
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_comprehension_walrus_binds_in_the_containing_scope():
    """fix(#996 review): PEP 572 — a walrus inside a comprehension binds
    OUTSIDE it. Making comprehensions scopes must not swallow that, or a
    rebinding of `rasterio` in the containing function goes unrecorded.

    The rebound name resolves to _OTHER, so the `rasterio.open` written after
    it is NOT credited as a rasterio open — which is the correct reading of
    code where `rasterio` no longer refers to the module.
    """
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path, items):\n"
            "    seen = [(rasterio := i) for i in items]\n"
            "    return rasterio.open(path), seen\n"
        ),
        {},
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_comprehension_walrus_does_not_leak_the_loop_target_too():
    """The control for the test above: the walrus target crosses out, the
    ordinary comprehension target does not."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path, items):\n"
            "    seen = [(keep := i) for rasterio in items]\n"
            "    return rasterio.open(path), seen, keep\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comprehension_walrus_alias_still_resolves_to_rasterio():
    """fix(#996 review): exporting the binding is not enough, the VALUE must
    travel too. `[(ropen := rasterio.open) for _ in items]` then `ropen(path)`
    is a real unwrapped open; recording `ropen` as an opaque name would leave
    it classified as unrelated and invisible to the gate."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path, items):\n"
            "    handles = [(ropen := rasterio.open) for _ in items]\n"
            "    return ropen(path), handles\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_plain_walrus_alias_resolves_too():
    """The same propagation outside a comprehension, which was equally blind."""
    violations, total = _collect_rasterio_violations(
        _mod(
            "import rasterio\n"
            "def fn(path):\n"
            "    if (ropen := rasterio.open):\n"
            "        return ropen(path)\n"
        ),
        {},
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_argv_bound_by_unpacking_is_still_detected():
    """fix(#996 review): `cmd, _ = ([...], None)` puts an ast.Tuple in
    `targets`, so a Name-only filter found no binding and a real invocation
    read as inert."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    cmd, ignored = (['gdalinfo', path], None)\n"
            "    subprocess.run(cmd)\n"
            "    return ignored\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_nested_shadow_does_not_make_an_inert_literal_escape():
    """fix(#996 review): a nested scope that REBINDS the name is not a use of
    the outer value. Without this the escape search read `def inner(cmd):
    consume(cmd)` as the outer constant reaching a call, and failed a security
    gate on code where the literal never moves."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def outer():\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    def inner(cmd):\n"
            "        return consume(cmd)\n"
            "    return inner\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_genuine_closure_use_still_escapes():
    """The control for the test above: a nested scope that does NOT rebind the
    name is a real use, and the literal is a command vector again."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def outer(path):\n"
            "    cmd = ['gdalinfo', path]\n"
            "    def inner():\n"
            "        return subprocess.run(cmd)\n"
            "    return inner\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(outer)" in violations[0]


def test_guard_argv_built_by_a_conditional_or_concatenation_is_detected():
    """fix(#996 review): the climb used to stop at the wrapping expression, so
    a literal assembled through a ternary or a `+` never reached its
    assignment and read as inert."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def ternary(path, inspect):\n"
            "    cmd = ['gdalinfo', path] if inspect else ['ogrinfo', path]\n"
            "    subprocess.run(cmd)\n"
            "def concatenated(path, extra):\n"
            "    cmd = ['gdalwarp', path] + extra\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert any("(ternary)" in v for v in violations)
    assert any("(concatenated)" in v for v in violations)


def test_guard_argv_reached_through_a_loop_target_is_detected():
    """fix(#996 review): iteration binds the argv to the loop target, which
    the assignment-only model did not see."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def looped(path):\n"
            "    for cmd in (['gdalinfo', path],):\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(looped)" in violations[0]


def test_guard_unpacking_binds_by_position_not_by_all_names():
    """fix(#996 review): attaching every target name to every nested literal
    let a SIBLING's escape drag inert data into the gate — the false-positive
    class this issue exists to remove. Positions are matched instead."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def fn():\n"
            "    ignored, choices = (None, ['gdalinfo', '-json'])\n"
            "    consume(ignored)\n"
            "    if choices[0] == 'gdalinfo':\n"
            "        pass\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_unpacking_still_detects_the_position_that_does_escape():
    """The control: the same shape with the roles swapped is a real argv."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    cmd, ignored = (['gdalinfo', path], None)\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_canonical_import_shadow_also_breaks_the_escape_link():
    """fix(#996 review): a canonical import lands in `canonical`, not `bound`,
    so a nested `from rasterio import open as cmd` was not recognised as a
    shadow and the inner load was credited to an outer literal."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def outer():\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    def inner():\n"
            "        from rasterio import open as cmd\n"
            "        return consume(cmd)\n"
            "    return inner\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_iterating_a_tool_name_list_is_not_an_argv():
    """fix(#996 review): `for tool in ["gdalinfo", "ogrinfo"]` binds each
    STRING to the target, not the list. Linking the list to every load of the
    target flagged ordinary tool-name data — the loop-target rule only applies
    when the literal is an ELEMENT of the iterable."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def fn():\n    for tool in ['gdalinfo', 'ogrinfo']:\n        consume(tool)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_subscripting_an_argv_yields_an_element_not_the_vector():
    """fix(#996 review): `cmd[0]` is a string. Returning or passing it moves an
    element, so the command-shaped list stays inert; a SLICE still yields a
    sequence that could be spawned and keeps escaping."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def head():\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    return cmd[0]\n"
            "def element(path):\n"
            "    cmd = ['ogrinfo', path]\n"
            "    consume(cmd[0])\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []

    sliced, total_sliced = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    cmd = ['gdalwarp', path]\n"
            "    subprocess.run(cmd[0:2])\n"
        ),
        {},
    )
    assert total_sliced == 1, (total_sliced, sliced)
    assert len(sliced) == 1 and "(fn)" in sliced[0]


def test_guard_argv_reached_through_an_alias_chain_is_detected():
    """fix(#996 review): `cmd = [...]`, `alias = cmd`, `run(alias)` reaches an
    exec through a name the literal was never directly bound to. Stopping at
    the first hop lost it, a regression against the pre-#996 scan."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    cmd = ['gdalinfo', path]\n"
            "    alias = cmd\n"
            "    later = alias\n"
            "    subprocess.run(later)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_chained_unpacking_keeps_every_target():
    """fix(#996 review): `a, b = cmd, y = (...)` binds the same position twice;
    returning only the first target dropped the name that reaches the exec."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    ignored, x = cmd, y = (['gdalinfo', path], None)\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]
