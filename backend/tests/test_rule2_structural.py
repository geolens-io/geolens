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
   must be covered by a ``gdal_safe_env()`` call in one of the ALLOWLISTED
   SHAPES below (fix(#1077)), or match a ``GDAL_CLI_CALL_ALLOWLIST`` entry
   keyed (module, function, tool) with an exact expected count and a
   justification.

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
- The CLI check is shape-scoped with exact counts, not full dataflow: an argv
  is credited when a ``gdal_safe_env()`` call in one of the allowlisted shapes
  covers it (see CREDIT IS AN ALLOWLIST below), and unclamped argvs are
  counted per (module, function, tool) against the allowlist. A function that
  calls the helper for one subprocess and hand-rolls a second env in the SAME
  function for the SAME tool would still pass; verifying which env reaches
  which ``subprocess.run`` is reviewer territory.
- Argv built dynamically (``cmd = [tool_var, ...]``) is not matched. Every
  GDAL CLI call in the codebase starts from a string-literal argv head.
- ARGV PASSED AS SEPARATE POSITIONAL ARGUMENTS is matched too, since
  fix(#1857 item 2): ``create_subprocess_exec("ogrinfo", "-so", path)`` is an
  argv site even though no list or tuple display is ever built. The two shapes
  are proved to execute in different ways, which is the whole reason they are
  detected separately. A display is inert until its value ESCAPES, so it earns
  its place through the escape analysis below. A varargs spawn does not need
  that argument: the call IS the spawn, so reaching the node is the proof, and
  neither the escape rule nor the tool-NAME-list exemption applies to it.
  ``_POSITIONAL_ARGV_SPAWNERS`` names the callees whose FIRST positional
  argument is the program (``asyncio.create_subprocess_exec``,
  ``loop.subprocess_exec``, and the ``os.exec*`` families). ``os.spawnl`` and
  friends lead with a mode argument instead and are not modelled; no site in
  ``app/`` uses either shape today -- every GDAL CLI call still builds a list
  and star-unpacks it -- so this closes the door before anyone walks through
  it rather than after. Neither is the SHELL family
  (``create_subprocess_shell``, ``shell=True``, ``os.system``, ``os.popen``),
  where the whole command is one string and there is no argv to read: that is
  a different detector, and a GDAL call spelled that way would be a finding on
  its own before it was a gate gap.
- A GDAL-headed literal counts as an argv only when its value ESCAPES —
  handed to a call, returned, or yielded (fix(#996)). The escape is followed
  directly, out of transparent wrappers (container literals, ternary, ``+``,
  ``or``), and through the PATH it is bound to: a name, an attribute or a
  constant key (``cmd``, ``box.cmd``, ``registry['cmd']``), bound by ``=``
  (positionally, when unpacking), annotated ``=``, ``+=``, a walrus, or a loop
  target over a container of argvs — chased through alias chains and out of
  containers to a fixed point. Consuming operations stop it: a single-index
  subscript of the VECTOR yields an element, while the same subscript of a
  CONTAINER yields the vector. ITERATING one is the same question as
  subscripting it and gets the same two answers (fix(#1394)): a ``for`` over a
  container binds each argv to the loop target, while a ``for`` over the vector
  binds strings. That holds whether or not the container has a name —
  ``for cmd in (["gdalinfo", path],):`` and ``commands = (["gdalinfo", path],)``
  then ``for cmd in commands:`` are one rule, read off the AST in the first case
  and off the followed path in the second. Inert data
  (``SUPPORTED_TOOLS = ["gdalinfo", "ogrinfo"]``, a constant only subscripted
  or compared) is not a command vector. A literal
  whose every element names a GDAL utility is a name list rather than a
  command, but only while it stays out of a call: a dataset or output path
  may legitimately be named ``ogrinfo``, so ``subprocess.run(["gdalinfo",
  "ogrinfo"])`` is an argv. Deliberately "escapes", not "reaches
  ``subprocess.*``": most argvs here are built in one function and spawned in
  another (``run_gdal(cmd, env=...)``), so a literal ``subprocess.*``
  requirement would blind the gate to the sites it exists for. Two or more
  elements are required for the name-list rule, since ``("gdalinfo",)`` is
  indistinguishable from a bare invocation.
- WHERE THE ESCAPE ANALYSIS STOPS (fix(#996), after eight review rounds).
  What it does is def-use tracking over paths, not dataflow: no flow
  sensitivity beyond the one narrow rebinding rule, no cross-function
  propagation, no container element tracking. Known and accepted residue, in
  the reported (loud) direction: a rebinding under an `if` still reports the
  dead literal; a vector passed INTO a helper and spawned there is credited to
  the helper's own scope, not the caller's. In the silent direction: a vector
  reached through a computed key (`registry[name]`) has no path and is not
  tracked; neither is one that leaves via a mutation this analysis cannot name
  (`box.append(cmd)` on an object whose other references are elsewhere); and
  neither is one extracted from an ANONYMOUS container that never gets a name
  (`cmd = ({"k": ["gdalinfo", path]})["k"]`), because the path machinery keys
  on a binding and there is none to key on.
  Three more silent residues sit next to the iteration rule (fix(#1394)), all
  of them "no container-element tracking" wearing different clothes, and each
  needs its own machinery rather than a wider rule: the container kind names
  what ONE wrapper yields, not a depth, so a container of containers
  (`groups = ((["gdalinfo", path],),)`) hands the inner container to the loop
  target as if it were the vector and the second loop follows nothing; a
  container reached through a METHOD (`for cmd in commands.values()`) is a call
  this analysis does not model, which is also why a dict holding argvs as
  values only ever reaches them by subscript here; and a comprehension TARGET is
  bound in the comprehension's own scope, which `_use_reaches_the_binding` reads
  as a shadow, so `[subprocess.run(cmd) for cmd in commands]` links only when
  the comprehension itself escapes — that one predates #1394 and applies equally
  to the inline `for cmd in (["gdalinfo", path],)` spelling.
  Extending further means writing a static analyser, and this is a CI gate —
  the escape hatch for anything it misclassifies is an allowlist entry with a
  written justification, which is the same answer #974 reached for the wrapper
  and credit questions. If a new shape shows up, prefer an allowlist entry and
  a note here over another rule.
- Comprehensions and generator expressions are binding scopes (fix(#996)),
  so their targets cannot shadow a name used elsewhere in the enclosing
  function. Two carve-outs match Python: the outermost iterable is evaluated
  before the comprehension's scope exists, and a walrus inside a
  comprehension binds in the CONTAINING scope (PEP 572). For CLI call-credit
  they are no longer transparent (fix(#1077)): only that outermost iterable is
  an allowlisted position, because a comprehension body runs once per item and
  an empty iterable runs it never.
- Wrapping is judged lexically, with two execution-order rules (codex round
  6): credit stops at def/lambda boundaries (a callable defined inside a
  wrapped block runs after the context exits), and within one ``with``
  statement only helper items EARLIER than the open's own item count
  (context managers enter left to right). Beyond that, a wrapped open
  passes even if a refactor later moves it into a helper called from
  outside the block. Reviewer territory.
- Helper credit requires the name to be bound to one of the canonical modules
  by an import the resolver understands, resolved through LEXICAL SCOPES
  innermost-first (see ``_scope_info`` / ``_resolve_credit``): a scope that
  rebinds the name (param, assignment, def, non-canonical import, loop or
  with target) kills credit for that scope and everything nested in it. A
  dotted ``import app.processing.raster.vrt`` used without an alias, a
  re-export through an UNNAMED intermediate module, or a name both imported
  and reassigned in one scope is NOT credited — the failure mode is a spurious
  violation prompting a review, never silent credit for a shadow. Class
  bodies are not modeled as scopes, and ``global``/``nonlocal``
  rebinding is not tracked. fix(#1857 item 3): "unnamed" is doing the work
  there. ``CANONICAL_HELPER_MODULES`` lists two import paths and, per path,
  which helpers it may vouch for, so ``processing/raster/vrt.py``'s re-export
  of the two driver clamps is credited because the map names that module
  rather than because a chain was followed. Nothing chases a re-export.
- CLI credit stops at the CALL level: a call to the canonical
  ``gdal_safe_env`` in an allowlisted position credits the argv, but whether
  that call's RESULT is the env handed to the subprocess is not verified.
  Wiring the returned dict to the ``subprocess.run(env=...)`` argument is
  dataflow analysis — reviewer territory, documented, not promised. One
  half-step is taken, since ``gdal_safe_env`` is a pure function whose result
  IS the protection: a call that drops it clamps nothing. So a bare
  ``gdal_safe_env()`` statement, and ``env = gdal_safe_env()`` whose target is
  never read, both report.
- CREDIT IS AN ALLOWLIST OF SHAPES (fix(#1077)). Credit used to be granted by
  WALKING the scope: any canonical call the walk reached exempted every argv
  in that scope. That is a broad exemption from a narrow observation, and it
  failed in the direction that matters — a call that is SEEN but not RUN
  (``if False:``, an untaken ternary arm, an unreached ``match`` case)
  produced silent credit in a security gate. Patching that shape by shape does
  not converge, because every conditional structure is another instance of it.

  So the default is inverted. A helper call credits an argv only when both of
  these hold, and reports otherwise:

  1. POSITION. Every step from the call up to the lowest common ancestor it
     shares with the argv is an allowlisted eager position (see
     ``_EAGER_POSITIONS``: a ``try`` body, a ``with`` body or item, the value
     of an assignment or a ``return``, an argument of a call, an element of a
     list/tuple/set display, an ``await``, and the outermost iterable of a
     comprehension). At the shared ancestor the two must meet in
     the same field — the same branch, the same statement list — or both sit
     in eager positions of it, which is what lets ``subprocess.run(argv,
     env=gdal_safe_env())`` credit across the args/keywords split.
  2. SHAPE. The result has to go somewhere. ``env = gdal_safe_env(...)``
     (annotated or not) credits only when the target is read; a bare
     ``gdal_safe_env()`` statement discards the env and credits nothing. A
     call handed straight into another call, bound by a walrus or returned
     carries no extra condition.

  What that buys. The three conditional shapes report. The DEFERRED set
  (generator expression, lambda, nested def/async def — measured on #996, and
  the only constructs in Python whose body does not run at construction) is
  denied by the same machinery rather than by a rule of its own, at every
  nesting level: the hole #996 left, ``(x for x in (gdal_safe_env() for _ in
  ()))``, closes because positions compose.
  ``functools.partial(gdal_safe_env)`` still needs no rule — it is a call to
  ``partial``, and ``_is_canonical_helper_call`` resolves the Call's OWN
  ``func``, so it never credits. Do not add one.

  What it costs. A legitimate call in a shape nobody named reports as
  unclamped. That is the trade: a false alarm someone investigates, never a
  silent pass. Measured on #1077, all 11 GDAL CLI argv sites in ``app/`` keep
  the verdict they had — the 4 that hold safe-env credit still hold it, the 7
  covered by ``GDAL_CLI_CALL_ALLOWLIST`` entries are untouched — and
  ``test_guard_real_tree_credit_shapes_are_all_allowlisted`` pins the shapes
  those 4 use, so a later narrowing fails there instead of in a
  reviewer's head. When a real site lands in a shape the list does not name,
  widen ``_EAGER_POSITIONS`` deliberately with a comment saying which site
  bought the entry, or take a ``GDAL_CLI_CALL_ALLOWLIST`` entry with a
  justification.

  The WRAPPER path (``with gdal_safe_open_env():``, the rasterio half) already
  worked this way and is unchanged: credit is lexical containment in the with
  block, so a wrapped open under ``if False:`` is conditional together with
  its wrapper and the question never arises.

  A separate question, and NOT something an allowlist can close: whether a
  GDAL-headed literal is SEEN as an argv at all. ``commands = (["gdalinfo",
  path],)`` then ``for cmd in commands: subprocess.run(cmd)`` reported zero
  sites, because extraction followed subscript and attribute loads but not
  ``For.iter``. That is a detection gap, not a credit gap — credit decides
  which DETECTED sites are exempt, and no exemption rule makes an undetected
  site appear. Earlier text here filed it as the third of three "credit gap
  classes" #1077 would close at once, which conflated the two. fix(#1394)
  closes it where it belongs, in the escape analysis: the shape is now an argv
  site, credited by the ordinary rules when a safe env covers it and reported
  when none does. Note what the two rules say together — a helper call in the
  LOOP BODY does not credit (a loop body may run zero times, per
  ``_EAGER_POSITIONS``), so the creditable spelling hoists the env above the
  loop, and the inline ``for cmd in (["gdalinfo", path],):`` form has always
  been judged that way.
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
# fix(#1846, GHSA-hrf5-v3cq-frx5): the vector CLI surface needs a different
# clamp from the raster one -- what matters for a vector source is which DRIVER
# GDAL is allowed to pick, not which /vsicurl extensions it may fetch. Both
# live in the same canonical module and both credit an argv the same way; a
# site is credited by whichever one it actually calls.
SAFE_VECTOR_ENV_HELPER = "gdal_vector_safe_env"
SAFE_SERVICE_ENV_HELPER = "gdal_service_safe_env"
SUBPROCESS_ENV_HELPERS = (
    SAFE_SUBPROCESS_ENV_HELPER,
    SAFE_VECTOR_ENV_HELPER,
    SAFE_SERVICE_ENV_HELPER,
)
ENV_HELPERS = (SAFE_OPEN_ENV_HELPER, *SUBPROCESS_ENV_HELPERS)

# fix(#1846): the two GDAL_SKIP driver clamps, which fix(#1857 item 3) moved
# out to `app/platform/gdal_env.py`. Named as their own set because that is
# the module's whole contents and the only thing it may vouch for.
DRIVER_SKIP_HELPERS = (SAFE_VECTOR_ENV_HELPER, SAFE_SERVICE_ENV_HELPER)

# fix(#1846, GHSA-hrf5-v3cq-frx5): the OTHER half of the vector clamp, and the
# primary one. The env helper is a denylist -- it names drivers GDAL may not
# register -- and a denylist can only exclude what somebody thought of, cannot
# name a driver whose short name contains a space (GDAL_SKIP tokenises on
# spaces), and says nothing about a driver a future base image adds. The
# allowlist inverts that: the declared upload extension decides which drivers
# may be ATTEMPTED, via repeated `-if`, so a driver nobody listed is excluded
# by omission. A staged-upload argv needs both, and this gate says so.
DRIVER_ALLOWLIST_HELPER = "local_input_driver_args"
DRIVER_ALLOWLIST_MODULE = "app.processing.ingest.gdal_drivers"

# fix(#1846, GHSA-hrf5-v3cq-frx5): and the THIRD layer, which is neither of the
# other two. GPKG and SQLite are pointer-following drivers -- a SQLite schema
# row can say "this table's rows come from that file over there" -- and neither
# clamp can exclude them, because GPKG is the primary supported upload format
# and the file really is a GeoPackage. What is left is to read the schema and
# refuse the upload, so a staged-upload argv needs that call too.
CONTENT_CHECK_HELPER = "validate_content_directives"
CONTENT_CHECK_MODULE = "app.processing.ingest.validation"
# The check is a linear schema walk, but a 4 MB schema is still real work and
# it runs inside the request that uploaded the file, so the async call sites
# hand it to a thread. That makes the helper an ARGUMENT rather than the head
# of a call, and a gate that only recognises `helper(...)` would have gone
# quiet on all three sites at once -- which is exactly what it did when the
# offload landed, before this. Recognised narrowly: the offload helper by
# name, with the guarded helper as its first positional argument.
THREAD_OFFLOAD_HELPER = "run_in_thread_draining"

# The one module whose definitions of the helpers are canonical. Credit for
# using a helper requires the name to be BOUND to this module (imported from
# it, or used inside it) — a bare tail-match would hand credit to a local
# shadow or an unrelated `something.gdal_safe_open_env()` (codex round 3 on
# #974). Module paths are matched EXACTLY (codex round 9): a suffix match
# credited `from evil.processing.raster.vrt import ...`. The real tree
# imports only the absolute form; relative imports (`from .vrt import ...`)
# are not used and get no credit — the conservative failure direction.
#
# fix(#1857 item 3): there are TWO canonical modules now, and the map says
# which helpers each may vouch for rather than crediting any name imported
# from either. The GDAL_SKIP driver clamps moved to app/platform/gdal_env.py
# so `modules/catalog/sources/preview.py` could reach them at all, and
# `processing/raster/vrt.py` re-exports them because every existing caller
# imports from there. That re-export is credited because this map NAMES the
# module, not because re-exports are credited in general: an unnamed
# intermediate still earns nothing, which is the rule the paragraph above
# describes and this does not relax.
CANONICAL_HELPER_MODULE = "app.processing.raster.vrt"
DRIVER_SKIP_MODULE = "app.platform.gdal_env"
CANONICAL_HELPER_PARENT = "app.processing.raster"

# import path -> the helpers that import path may credit.
CANONICAL_HELPER_MODULES: dict[str, frozenset[str]] = {
    CANONICAL_HELPER_MODULE: frozenset(ENV_HELPERS),
    DRIVER_SKIP_MODULE: frozenset(DRIVER_SKIP_HELPERS),
}
# module path relative to backend/app -> the helpers DEFINED there, so a call
# inside a defining module credits itself.
CANONICAL_HELPER_MODULE_RELS: dict[str, frozenset[str]] = {
    "processing/raster/vrt.py": frozenset(
        h for h in ENV_HELPERS if h not in DRIVER_SKIP_HELPERS
    ),
    "platform/gdal_env.py": frozenset(DRIVER_SKIP_HELPERS),
}

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
    ("processing/raster/cog.py", "_predictor_supported"): (
        1,
        "local staged/temp path only; probes per-band IMAGE_STRUCTURE NBITS "
        "before letting convert_to_cog put PREDICTOR=<n> on the gdal_translate "
        "argv",
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
# fix(#1846, GHSA-hrf5-v3cq-frx5): five entries left this list, and the reason
# they left is worth keeping. Three of them ("local staged file ... no HTTP
# surface") were exemptions granted on a claim about the file's PATH. The path
# was local. What GDAL did with it was not bounded by that: several OGR drivers
# read a document as instructions naming somewhere else to go, so a staged
# local file could name an arbitrary local path or an arbitrary URL, and the
# gate passed while that was live. A justification that describes the input
# rather than the driver set is not a proof, and this list is the wrong place
# for one. Those sites now carry gdal_vector_safe_env plus the input-driver
# allowlist, and are credited rather than excused. The two remaining
# ogr2ogr/ogrinfo sites in ogr.py and export/ogr.py went the same way.
# fix(#1857 item 3): EMPTY, and that is the point. The single entry that used
# to live here was `run_service_preview`, justified on the grounds that
# `modules/catalog/` may not import `app.processing.*` and the helpers lived
# there. That describes a layering accident, not a property of the site, and a
# justification is what you write when the code cannot be fixed. The clamps
# moved to `app/platform/gdal_env.py`, the site calls one, and it is credited
# rather than excused. Every GDAL CLI argv in `app/` now carries a safe env.
GDAL_CLI_CALL_ALLOWLIST: dict[tuple[str, str, str], tuple[int, str]] = {}

# Floors so a refactor that blinds the detector fails loudly instead of
# passing on an empty scan (same trick as the Rule-1 route-count floor).
MIN_RASTERIO_OPEN_SITES = 5
MIN_GDAL_CLI_ARGV_SITES = 6

# Every ogrinfo/ogr2ogr argv in `app/`, and what its input is. Asserted EXACT
# in both directions and by count, like the two allowlists above: a new vector
# CLI site with no entry fails, and an entry whose site disappears fails.
#
# `staged_upload` means the argv opens a file a caller supplied. Those are the
# sites the driver question is live for, and they must carry BOTH the input
# allowlist (`local_input_driver_args`) and a subprocess env helper. Everything
# else carries the env helper and names, in its justification, what pins its
# driver instead.
STAGED_UPLOAD = "staged_upload"
OTHER_INPUT = "other_input"

# (module, function, tool) -> (expected argv count, policy kind, the env
# helper this site MUST use or None, justification).
#
# fix(#1846 codex P2, thread 3939092275): the env helper is named PER SITE
# rather than taken from the kind, and the credit check demands that one
# helper rather than any of the three. Accepting the family let the clamps
# cross: a staged upload wired to `gdal_safe_env` passed this test while
# carrying the RASTER clamps and no vector driver skip at all, and a raster
# argv wired to `gdal_vector_safe_env` passed the older test without
# CPL_VSIL_CURL_ALLOWED_EXTENSIONS or VRT_VIRTUAL_OVERVIEWS. Two helpers that
# both "are a safe env" are not interchangeable; which one is the whole point.
VECTOR_CLI_DRIVER_POLICY: dict[
    tuple[str, str, str], tuple[int, str, str | None, str]
] = {
    ("processing/ingest/ogr.py", "run_ogrinfo", "ogrinfo"): (
        2,
        STAGED_UPLOAD,
        SAFE_VECTOR_ENV_HELPER,
        "the -json path and the pre-GDAL-3.7 text fallback, both reading the "
        "staged file; one driver_args and one driver_env cover both",
    ),
    ("processing/ingest/ogr.py", "run_ogrinfo_preview", "ogrinfo"): (
        1,
        STAGED_UPLOAD,
        SAFE_VECTOR_ENV_HELPER,
        "the preview, which returns sample rows to the caller",
    ),
    ("processing/ingest/ogr.py", "run_ogr2ogr", "ogr2ogr"): (
        1,
        STAGED_UPLOAD,
        SAFE_VECTOR_ENV_HELPER,
        "the commit, which must select the same driver the preview did",
    ),
    ("processing/ingest/ogr.py", "run_ogr2ogr_service", "ogr2ogr"): (
        1,
        OTHER_INPUT,
        SAFE_SERVICE_ENV_HELPER,
        "remote service; the driver is pinned by the WFS:/OAPIF:/ESRIJSON: "
        "prefix build_gdal_source puts on the source string, and the URL is "
        "gated by validate_url_for_ssrf at submission time. The SERVICE env "
        "variant specifically: it keeps WFS and OAPIF, which the vector one "
        "skips, and this call exists to use them",
    ),
    ("processing/export/ogr.py", "run_ogr2ogr_export", "ogr2ogr"): (
        1,
        OTHER_INPUT,
        SAFE_VECTOR_ENV_HELPER,
        "reads a PG connection string, not a caller-supplied document, and "
        "writes a local output path. Takes the VECTOR env, not the service "
        "one: nothing here needs WFS or OAPIF, so the narrower skip list is "
        "the right one and the surface answers uniformly",
    ),
    ("modules/catalog/sources/preview.py", "run_service_preview", "ogrinfo"): (
        1,
        OTHER_INPUT,
        SAFE_SERVICE_ENV_HELPER,
        "remote service. Prefix-pinned on the service branch like "
        "run_ogr2ogr_service, and -if GeoJSON on the localised branch, where "
        "the source is a bare local path the page walker wrote (#1846). Takes "
        "the SERVICE env for the same reason run_ogr2ogr_service does: the "
        "service branch exists to use WFS and OAPIF, which the vector variant "
        "skips. fix(#1857 item 3): this used to be the one site with no env "
        "helper at all, recorded here as None, because modules/catalog/ may "
        "not import app.processing.* (test_layering.py) and that is where the "
        "helpers lived. They live in app/platform/gdal_env.py now, so the "
        "site is credited rather than excused",
    ),
}

# Which policy kinds require the driver allowlist and the content check. The
# env helper is not listed here on purpose -- it is per site, above.
_POLICY_NEEDS_DRIVER_ALLOWLIST = {STAGED_UPLOAD}
_POLICY_KINDS = {STAGED_UPLOAD, OTHER_INPUT}
VECTOR_CLI_TOOLS = ("ogrinfo", "ogr2ogr")
MIN_VECTOR_CLI_ARGV_SITES = 6


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
_KIND_VECTOR_ENV = SAFE_VECTOR_ENV_HELPER
_KIND_SERVICE_ENV = SAFE_SERVICE_ENV_HELPER
_KIND_DRIVER_ALLOWLIST = DRIVER_ALLOWLIST_HELPER
_KIND_CONTENT_CHECK = CONTENT_CHECK_HELPER
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
    SAFE_VECTOR_ENV_HELPER: _KIND_VECTOR_ENV,
    SAFE_SERVICE_ENV_HELPER: _KIND_SERVICE_ENV,
}
_PROPAGATED_KINDS = (
    _KIND_OPEN,
    _KIND_ENV,
    _KIND_VECTOR_ENV,
    _KIND_SERVICE_ENV,
    _KIND_DRIVER_ALLOWLIST,
    _KIND_CONTENT_CHECK,
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
# LATER" (the boundary rule in _inside_safe_open_env, and the only nodes with a
# `.args` for _record_params), while _LEXICAL_SCOPES means "a scope that owns
# its own names" (binding resolution).
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
            _KIND_VECTOR_ENV: set(),
            _KIND_SERVICE_ENV: set(),
            _KIND_DRIVER_ALLOWLIST: set(),
            _KIND_CONTENT_CHECK: set(),
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
    if node.level == 0 and module in CANONICAL_HELPER_MODULES:
        kinds = {helper: helper for helper in CANONICAL_HELPER_MODULES[module]}
    elif node.level == 0 and module == DRIVER_ALLOWLIST_MODULE:
        # Only the direct `from ... import local_input_driver_args` spelling
        # earns credit. A module alias would need its own tracking and the tree
        # does not use one, so it falls through to `bound` and reports.
        kinds = {DRIVER_ALLOWLIST_HELPER: _KIND_DRIVER_ALLOWLIST}
    elif node.level == 0 and module == CONTENT_CHECK_MODULE:
        kinds = {CONTENT_CHECK_HELPER: _KIND_CONTENT_CHECK}
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
        if alias.name in CANONICAL_HELPER_MODULES and alias.asname:
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


def _iter_immediate(node: ast.AST):
    """Yield descendants of ``node`` without entering nested scopes; nested
    scope NODES themselves are yielded (their names bind in this scope).

    fix(#996): comprehensions stop the walk, because their targets bind in
    their OWN scope. They did not before, so a function containing
    ``[rasterio for rasterio in tools]`` recorded ``rasterio`` as bound in the
    function and a genuine ``rasterio.open(path)`` elsewhere in that same
    function resolved to _OTHER — an unwrapped open reported as zero opens.

    fix(#1077): this walk now answers ONE question, binding resolution. CLI
    call-credit used to borrow it with ``stop_at_comprehensions=False`` and
    decide execution from what the walk reached; credit is now a position
    allowlist (``_EAGER_POSITIONS``) that reads the AST upward instead, so the
    second mode is gone.
    """
    stop = (*_LEXICAL_SCOPES, ast.ClassDef)
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
        yield from _iter_immediate(child)


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
    """True for a helper definition inside the module that DEFINES it.

    fix(#1857 item 3): keyed per module, so `processing/raster/vrt.py` vouches
    for the two raster helpers it still defines and `platform/gdal_env.py` for
    the two driver clamps. vrt.py's re-export of the latter pair is an import
    and reaches credit through `_record_import_from` like any other caller's.
    """
    return (
        isinstance(scope, ast.Module)
        and getattr(node, "name", None) in CANONICAL_HELPER_MODULE_RELS.get(rel, ())
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _record_canonical_defs(info: _ScopeInfo, scope: ast.AST, rel: str) -> None:
    if not (isinstance(scope, ast.Module) and rel in CANONICAL_HELPER_MODULE_RELS):
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

    # fix(#996 review): a walrus inside a comprehension binds in the CONTAINING
    # scope (PEP 572), and _comprehension_walrus_targets already exports it
    # there. Recording it HERE as well put the same name in both scopes, so
    # `[run(cmd) for _ in items if (cmd := ["gdalinfo", path])]` had its own
    # load read as a nested shadow and the argv vanished. Exporting a binding
    # and also keeping it is the contradiction; the export is the correct half.
    comprehension_walrus_ids = (
        {id(n) for n in _comprehension_walrus_targets(scope)}
        if isinstance(scope, _COMPREHENSION_NODES)
        else set()
    )
    for node in _iter_immediate(scope):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _record_import(info, node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_canonical_def(scope, node, rel):
                info.bound.add(node.name)
                info.other_bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if id(node) in comprehension_walrus_ids:
                continue  # belongs to the containing scope, not this one
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


# fix(#1077): the POSITIONS that can carry safe-env credit, as an allowlist.
# Every entry names a place where the child expression or statement runs
# exactly once whenever the construct holding it runs — the property credit
# actually depends on. A helper call reached through any position NOT named
# here grants nothing: an `if`/`else` branch, a ternary arm, a `match` case, a
# loop or comprehension body, an `except` handler, a deferred def/lambda/genexp
# body, and every shape nobody has thought of yet all land outside, and the
# argv reports. Widening this dict is a deliberate, reviewed act.
_EAGER_POSITIONS: dict[type[ast.AST], frozenset[str]] = {
    # Statements: a `try` body runs on entry, and a `with` opens its items left
    # to right and then runs its body. A `finally` is deliberately NOT here: it
    # runs whenever the `try` is entered, but it runs AFTER the body it would
    # have to clamp, so an env built there reaches no subprocess in that body.
    # A `finally` that builds its own argv beside its own env still credits,
    # through the same-field rule in _credit_position_reaches.
    ast.Try: frozenset({"body"}),
    ast.TryStar: frozenset({"body"}),
    ast.With: frozenset({"body", "items"}),
    ast.AsyncWith: frozenset({"body", "items"}),
    ast.withitem: frozenset({"context_expr"}),
    # Expressions, within one statement. `return run_gdal(cmd,
    # env=gdal_safe_env())` is the most direct wiring there is and had to be
    # named explicitly, or the tree's own `_build_vrt` shape would lose credit
    # the day someone dropped its intermediate variable.
    ast.Return: frozenset({"value"}),
    ast.Expr: frozenset({"value"}),
    ast.Assign: frozenset({"value"}),
    ast.AnnAssign: frozenset({"value"}),
    ast.AugAssign: frozenset({"value"}),
    ast.NamedExpr: frozenset({"value"}),
    ast.Await: frozenset({"value"}),
    ast.Call: frozenset({"args", "keywords"}),
    ast.keyword: frozenset({"value"}),
    ast.Starred: frozenset({"value"}),
    ast.List: frozenset({"elts"}),
    ast.Tuple: frozenset({"elts"}),
    ast.Set: frozenset({"elts"}),
}


def _position_field(child: ast.AST, parent: ast.AST) -> str | None:
    """The field of ``parent`` that holds ``child`` (``"body"``, ``"value"``…)."""
    for name, value in ast.iter_fields(parent):
        if value is child:
            return name
        if isinstance(value, list) and any(item is child for item in value):
            return name
    return None


def _is_eager_position(child: ast.AST, parent: ast.AST) -> bool:
    """True when ``child`` sits in an allowlisted eager position of ``parent``."""
    field = _position_field(child, parent)
    if field is None:
        return False
    # The OUTERMOST iterable of a comprehension or generator expression is the
    # one part evaluated at construction (fix(#996)); the element, the `if`
    # clauses and any later `for`'s iterable run per item, or never. Written as
    # position rules so the recursion is automatic: the iterable of a genexp
    # nested inside another genexp's element is not reached at all, which is
    # the hole the hand-rolled scan left open.
    if isinstance(parent, ast.comprehension):
        owner = getattr(parent, "_rule2_parent", None)
        generators = getattr(owner, "generators", None)
        return field == "iter" and bool(generators) and generators[0] is parent
    if isinstance(parent, _COMPREHENSION_NODES):
        return (
            field == "generators"
            and bool(parent.generators)
            and (parent.generators[0] is child)
        )
    return field in _EAGER_POSITIONS.get(type(parent), frozenset())


def _credit_position_reaches(call: ast.AST, argv: ast.AST) -> bool:
    """True when ``call`` runs on the same unconditional path as ``argv``.

    Climbs from the helper call to the lowest common ancestor it shares with
    the argv. Every step below that ancestor must be an allowlisted eager
    position, so a call the gate cannot prove executes — under a branch, in a
    loop body, inside a nested callable — never vouches for the argv. At the
    common ancestor itself the two must meet in the SAME field — the same
    branch, the same statement list — or BOTH sit in eager positions of it,
    which is what makes ``subprocess.run(argv, env=gdal_safe_env())`` credit
    (the args and the keywords of one call) while ``if flag: gdal_safe_env()``
    beside an argv in the ``else``, or a helper in a ``try`` body beside an
    argv in its ``except``, does not.
    """
    argv_child: dict[int, ast.AST] = {}
    child: ast.AST = argv
    parent = getattr(argv, "_rule2_parent", None)
    while parent is not None:
        argv_child[id(parent)] = child
        child, parent = parent, getattr(parent, "_rule2_parent", None)

    if id(call) in argv_child:
        return False  # the argv is an argument OF the helper call, not clamped by it

    child = call
    parent = getattr(call, "_rule2_parent", None)
    while parent is not None:
        shared = argv_child.get(id(parent))
        if shared is not None:
            same_field = _position_field(child, parent) == _position_field(
                shared, parent
            )
            return same_field or (
                _is_eager_position(child, parent) and _is_eager_position(shared, parent)
            )
        if not _is_eager_position(child, parent):
            return False
        child, parent = parent, getattr(parent, "_rule2_parent", None)
    return False


def _credit_shape_is_named(call: ast.AST, scope: ast.AST) -> bool:
    """True when the helper call's own shape is one the allowlist names.

    ``gdal_safe_env`` is a pure function: it RETURNS the clamped env and
    changes nothing global, so a call whose result goes nowhere clamps
    nothing. Two spellings of nowhere are named here, because both read as
    protection and are not: a bare ``gdal_safe_env()`` statement, whose result
    is discarded, and ``env = gdal_safe_env()`` (annotated or not) with a
    target nothing ever reads. Every other shape — the call handed into
    another call, bound by a walrus, returned — passes this check; WHICH call
    the env eventually reaches is still not verified, the documented
    Call-level stop, unchanged.
    """
    parent = getattr(call, "_rule2_parent", None)
    if isinstance(parent, ast.Expr) and parent.value is call:
        return False
    targets: list[ast.expr] = []
    if isinstance(parent, ast.Assign) and parent.value is call:
        targets = list(parent.targets)
    elif isinstance(parent, ast.AnnAssign) and parent.value is call:
        targets = [parent.target]
    if not targets:
        return True
    names = {t.id for t in targets if isinstance(t, ast.Name)}
    if len(names) != len(targets):
        return False  # unpacking a helper call into a pattern is not a named shape
    return any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in names
        for node in ast.walk(scope)
    )


def _argv_has_safe_env_credit(
    argv: ast.AST, scope: ast.AST, rel: str, required_helpers: tuple[str, ...]
) -> bool:
    """True when an allowlisted shape of ``required_helpers`` covers ``argv``.

    ``required_helpers`` is not optional and is deliberately not defaulted to
    the whole family (fix(#1846 codex P2)). The three subprocess env helpers
    clamp different things -- the raster one sets
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS and VRT_VIRTUAL_OVERVIEWS, the vector one
    sets GDAL_SKIP over the pointer and network drivers, and the service one
    keeps WFS and OAPIF out of that skip list -- so "some safe env covers this
    argv" is not the question worth asking. Accepting any of them let a staged
    upload be credited by the raster helper, with no vector driver skip
    anywhere near it, and the gate reported clean.

    fix(#1077) inverts the old model. Credit used to be granted by WALKING the
    scope: any canonical call the walk saw exempted every argv in that scope,
    so a call that was seen but never executed (``if False:``, an untaken
    ternary arm, an unreached ``match`` case) produced silent credit — a false
    all-clear in a security gate, and an open-ended one, since every
    conditional structure is another instance of it.

    Credit is now granted only for shapes that can be NAMED: a call in an
    eager, unconditional position relative to the argv (see
    ``_EAGER_POSITIONS``), and, for the assignment form, one whose target is
    actually read. Everything else reports as unclamped. That direction is
    bounded by construction: a shape the gate does not recognise costs a false
    alarm somebody investigates, never a silent pass.

    codex round 4 on #974 still holds inside the shapes: credit requires an
    actual Call resolving to the canonical binding, so a bare Name reference
    (assignment of the function itself, a log line) earns nothing.
    """
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        if not any(
            _is_canonical_helper_call(node, helper, rel) for helper in required_helpers
        ):
            continue
        if _credit_shape_is_named(node, scope) and _credit_position_reaches(node, argv):
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
        # fix(#996 review): a comparison yields a BOOLEAN, so
        # `log.debug("matched=%s", cmd == expected)` hands over the result, not
        # the vector. Same family as the subscript rule below: an operation
        # that consumes the value and produces something else is where the
        # escape stops.
        if isinstance(current, ast.Compare):
            return best
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


def _expr_path(expr: ast.expr) -> str | None:
    """A stable textual handle for a storable location, or None.

    ``cmd`` -> ``"cmd"``; ``box.cmd`` -> ``"box.cmd"``; ``registry['tools']``
    -> ``"registry['tools']"``. fix(#996 review): the analysis tracks PATHS
    rather than bare names, so a vector stored on an attribute or under a
    constant key can be matched when it is loaded back. A computed key gets no
    path — it cannot be compared textually, and guessing would be the
    container mistake again.
    """
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _expr_path(expr.value)
        return f"{base}.{expr.attr}" if base else None
    if isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant):
        base = _expr_path(expr.value)
        return f"{base}[{expr.slice.value!r}]" if base else None
    return None


def _target_names(target: ast.expr) -> set[str]:
    """The paths an assignment TARGET binds.

    fix(#996 review), twice over. First: walking every ``Name`` in the target
    read ``settings.choices = [...]`` as binding ``settings``, so a later
    ``render(settings)`` looked like the argv escaping — a false positive on
    data that never moves. Then: returning NOTHING for such targets meant
    ``box.cmd = [...]`` followed by ``subprocess.run(box.cmd)`` reported zero
    sites for a literal that really is executed.

    Binding the PATH answers both. ``box.cmd = [...]`` binds ``"box.cmd"``,
    which matches a later load of ``box.cmd`` and does not match a load of
    ``box``.
    """
    if isinstance(target, (ast.Tuple, ast.List)):
        return {n for elt in target.elts for n in _target_names(elt)}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    path = _expr_path(target)
    return {path} if path else set()


def _is_value_position(current: ast.AST, parent: ast.AST) -> bool:
    """True when ``parent`` can EVALUATE TO ``current``.

    Not every field of a value wrapper is one of its values, and the two that
    are not both showed up as false positives (codex rounds 7 and 8).

    A ternary yields one of its two RESULTS; its condition is only read for
    truthiness, so ``[] if commands else ()`` is never ``commands``.

    A boolean operator yields a non-final operand only when that operand
    DECIDES the expression, and the two operators decide on opposite
    truthiness. ``or`` yields it when truthy, so ``commands or ()`` really can
    be ``commands`` with argvs in it. ``and`` yields it when FALSY, so
    ``commands and ()`` can only ever be an EMPTY ``commands`` — iterating that
    runs nothing. The final operand is a possible result for both.

    Everything else in ``_VALUE_WRAPPERS`` (the arithmetic chain) passes its
    value through from any operand. That deliberately includes repetition by a
    literal zero, ``commands * 0``, which is always empty (codex round 9,
    declined): this gate does no constant folding ANYWHERE, by the same
    decision #1077 made when it chose to report ``if False: gdal_safe_env()``
    rather than evaluate the condition. Both cost a false alarm and neither
    costs a silent pass, which is the trade this module takes everywhere. The
    two exclusions above are not folding — they read which FIELD an operator
    can return, with no claim about any operand's value.
    """
    if isinstance(parent, ast.NamedExpr):
        # A walrus BINDS its value and also evaluates to it, so
        # `for cmd in (alias := commands):` iterates `commands` (codex round
        # 10). The binding half is recorded elsewhere and does not help here:
        # the target is a Store, and the alias walk only follows Loads.
        return current is parent.value
    if isinstance(parent, ast.IfExp):
        return current is parent.body or current is parent.orelse
    if isinstance(parent, ast.BoolOp):
        return bool(parent.values) and (
            isinstance(parent.op, ast.Or) or current is parent.values[-1]
        )
    return isinstance(parent, _VALUE_WRAPPERS)


def _intact_loop_target(target: ast.expr) -> ast.expr | None:
    """The part of a loop target that receives an element WHOLE, or None.

    A plain name or path receives it intact. So does a LEADING star, which is
    the thing that decides this: ``for *cmd, in commands:`` binds ``cmd`` to
    ``list(element)``, the vector rebuilt (codex round 7), and ``for *cmd,
    ignored in commands:`` binds it to everything but the tail — still an argv,
    because it still starts with the tool name (codex round 17). Both were
    rejected with the rest of the patterns, and both hid a real command.

    Ordinary positional destructuring gets nothing (codex round 2):
    ``for tool, arg in commands:`` splits the vector into strings. Neither does
    a star anywhere but first, ``for tool, *rest in commands:`` — ``rest`` is a
    SUFFIX of the argv, which has no GDAL head and would be judged against the
    wrong tool if it were treated as a command.

    Position decides it, not arity, and the gap that leaves is deliberate
    (codex round 18, declined). ``for *cmd, ignored in [("gdalinfo",)]:`` binds
    ``cmd`` to ``[]``, because the pattern's fixed names eat the only element —
    so the site reports and nothing runs. Closing it means comparing the
    pattern's arity against the LITERAL's, which couples a target-shape
    question to a value this function never sees, for a shape that needs a
    one-element argv and a starred pattern at once. It is the loud direction on
    a literal the module already treats as a command by convention: a
    single-element ``("gdalinfo",)`` is indistinguishable from a bare
    invocation, per the two-element floor in ``_tool_name_list``.
    """
    if isinstance(target, (ast.Tuple, ast.List)):
        if target.elts and isinstance(target.elts[0], ast.Starred):
            return target.elts[0].value
        return None
    return target


def _depth_preserving_ancestor(expr: ast.AST) -> ast.AST:
    """The outermost expression around ``expr`` that is still the same value.

    Same value meaning the same thing at the same container depth, so a caller
    holding a container of argvs still holds one at the top. Four wrappers
    qualify, each already named elsewhere in this module (fix(#1394), codex
    round 6 and after):

    * a VALUE wrapper — ``commands or ()``, ``commands if flag else ()``,
      ``commands + extra`` — or a walrus, in a position the wrapper can
      actually evaluate to, which rules out a ternary's condition and a
      non-final ``and`` operand (see ``_is_value_position``).
    * a star inside a display, ``(*commands,)``, which splices ``commands``'
      elements into a new one and so preserves its depth (codex round 5). The
      pair counts once, exactly as it does in ``_binding_targets``.
    * a SLICE, ``commands[:]``, which yields a sequence of the same things
      (codex round 9). A single index does not: it consumes a level.

    A CONTAINER wrapper is deliberately absent: ``[commands]`` is a level
    deeper, and pretending otherwise is the container mistake #996 is about.
    """
    current: ast.AST = expr
    while True:
        parent = getattr(current, "_rule2_parent", None)
        if parent is not None and _is_value_position(current, parent):
            current = parent
            continue
        if isinstance(parent, ast.Starred):
            display = getattr(parent, "_rule2_parent", None)
            if isinstance(display, (ast.List, ast.Tuple, ast.Set)):
                current = display
                continue
        # A SLICE yields a sequence of the same things: `commands[:]` is still
        # a container of argvs, `cmd[1:]` still a sequence of strings. #996
        # already reads it that way in `_escape_kind`, where only a SINGLE
        # index — which consumes a level — stops the walk (codex round 9).
        if (
            isinstance(parent, ast.Subscript)
            and parent.value is current
            and isinstance(parent.slice, ast.Slice)
        ):
            current = parent
            continue
        return current


def _loop_target_paths(iterable: ast.AST) -> set[str]:
    """The paths a loop binds when ``iterable`` is (part of) the thing iterated.

    ``for cmd in commands:`` binds ``"cmd"``; ``async for`` and a
    comprehension's generator bind the same way. Empty when ``iterable`` is not
    in an iterated position, when the target is a shape ``_target_names``
    cannot name, or when the target DESTRUCTURES.

    fix(#1394): ONE definition of what a loop binds, because two callers need
    it and they know different things. ``_binding_targets`` calls it for a
    literal written directly inside the iterable (``for cmd in (["gdalinfo",
    path],):``), where the container is visible in the AST. ``_argv_escape_kind``
    calls it for a NAME already known to hold a container of argvs
    (``commands = (["gdalinfo", path],)`` then ``for cmd in commands:``), where
    it is not.

    The destructuring rule is codex round 2 on #1394, and it predates the
    named-container half: ``for tool, arg in commands:`` splits the element
    apart, so each name gets a PIECE of the argv and none of them gets the
    argv. ``_target_names`` flattens a pattern to all its names, which is the
    right answer for an assignment — where ``_positional_targets`` then matches
    them up by position — and the wrong one here, where the value being split
    is the command vector rather than a tuple of unrelated values. Returning
    nothing is the accurate answer within this model, in which the element of a
    container IS the vector: destructuring a vector yields strings. One pattern
    is not destructuring though it is spelled like one — see
    ``_intact_loop_target``.

    codex round 6 on #1394: the iterable is reached through
    ``_depth_preserving_ancestor``, so ``for cmd in commands or ():`` is the
    same loop as ``for cmd in commands:``. Requiring the load to be the direct
    child of ``For.iter`` let a value wrapper — the ternary, ``+`` and ``or``
    forms #996 already follows everywhere else — hide a real argv.
    """
    iterated = _depth_preserving_ancestor(iterable)
    parent = getattr(iterated, "_rule2_parent", None)
    if (
        isinstance(parent, (ast.For, ast.AsyncFor, ast.comprehension))
        and parent.iter is iterated
    ):
        target = _intact_loop_target(parent.target)
        if target is not None:
            return _target_names(target)
    return set()


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


# A wrapper whose contents are known only by KIND, not by shape: which position
# holds the argv is unknowable, and in a container of argvs every one does
# (fix(#1394), codex round 14).
#
# So unpacking one binds EVERY name in the pattern, and where the container is
# actually heterogeneous — `container = (argv, None)` reached through a name,
# then `first, ignored = alias` — the inert position reports too (codex round
# 15, declined). Positions are exactly what a kind drops, and this analysis has
# tracked no container ELEMENTS since #996; recovering them means the static
# analyser #996 declined to write. The alternative on the table was dropping
# the inherited level, which reinstates the round-14 silent miss: a false alarm
# somebody investigates traded for an all-clear nobody sees. Take the alarm.
_ANY_POSITION = -1


def _all_pattern_elements(targets: list[ast.expr]) -> list[ast.expr] | None:
    """Every element of the sequence patterns among ``targets``, or None.

    The ``_ANY_POSITION`` counterpart of ``_positional_targets``. A starred
    element bails the same way it does there: it binds a sub-list rather than
    an element, so the pattern's names do not all receive the same thing and
    the caller keeps its conservative answer.

    Keeping the non-starred names and dropping the star was the obvious
    narrowing and is deliberately NOT taken (codex round 16, declined). In
    ``cmd, *rest = commands`` the star's target holds a container of argvs and
    a later ``for c in rest:`` is a real path to an exec, so dropping it trades
    this over-report for a silent miss — the one direction that is worse.
    Splitting the two kinds means the element pickers returning a kind per
    target rather than a level, which is the container-element tracking #996
    declined to build. Until a real site needs it, the loud answer stands.
    """
    matched: list[ast.expr] = []
    saw_sequence = False
    for target in targets:
        if not isinstance(target, (ast.Tuple, ast.List)):
            continue
        saw_sequence = True
        if any(isinstance(e, ast.Starred) for e in target.elts):
            return None
        matched.extend(target.elts)
    return matched if (saw_sequence and matched) else None


def _unpacked_binding(
    targets: list[ast.expr],
    chain: list[tuple[int | None, str | None, bool]],
    container_kind: str | None,
) -> dict[str, str | None] | None:
    """Pair the wrappers a literal sits in against the patterns unpacking them.

    ``chain`` lists those wrappers OUTERMOST first, each with the index the
    value occupies in it, the kind of what is INSIDE it, and whether it adds a
    level. Every level where some target is a sequence pattern consumes one
    wrapper and descends; a target that stops being a pattern stops there,
    holding the value at that depth. Returns None when nothing was unpacked at
    all, and the caller keeps its plain-assignment answer.

    fix(#1394), codex rounds 11 through 13, one shape at a time.

    Unpacking CONSUMES the wrapper it takes apart, so ``alias, = (["gdalinfo",
    path],)`` leaves ``alias`` holding the vector and ``for part in alias:``
    yields strings rather than commands. Handling one level was not enough,
    because patterns nest as freely as displays do: ``((alias,),) =
    ((["gdalinfo", path],),)`` consumes two and lands in the same place, while
    ``(alias,) = ((["gdalinfo", path],),)`` consumes one and leaves a
    container. Counting them one for one covers every depth with no rule per
    depth.

    Two things the counting has to get right. A wrapper that adds NO level
    (a value wrapper, a star and its display) is not a pattern's to consume, so
    it is stepped over rather than ending the pairing — otherwise ``(alias,) =
    ((["gdalinfo", path],) + ())`` never pairs at all. And chained targets can
    unpack to DIFFERENT depths, so a target whose pattern ends early is kept at
    that depth instead of being dropped when its siblings descend further.

    Those endpoints keep their OWN kinds (codex round 15). Chained targets can
    end at different depths, so ``(alias,) = ((deep,),) = ((["gdalinfo",
    path],),)`` leaves ``alias`` holding a container and ``deep`` holding the
    argv, and one kind for both names could only be wrong about one of them.
    Merging happened here because the answer was a set plus a kind; it is a
    mapping now, and merging is left to the one case that needs it, a name that
    really does appear at two depths.
    """
    current = targets
    kind = container_kind
    endpoints: list[tuple[set[str], str | None]] = []
    consumed = False
    for index, kind_below, adds_level in chain:
        if not adds_level:
            continue  # nothing here for a pattern to take apart
        if index is None:
            # A level, but not one unpacked by position (a dict, a set). A
            # SINGLETON set does hand its sole element over unambiguously
            # (`cmd, = {("gdalinfo", path)}`), and reading that would need the
            # wrapper's own arity, which the chain does not carry (codex round
            # 16, declined). It is the loud direction, on a shape that appears
            # nowhere: sets are unordered, so nothing here builds an argv in
            # one.
            break
        nxt = (
            _all_pattern_elements(current)
            if index == _ANY_POSITION
            else _positional_targets(current, index)
        )
        if nxt is None:
            break
        for target in current:
            if not isinstance(target, (ast.Tuple, ast.List)):
                endpoints.append((_target_names(target), kind))
        current, kind, consumed = nxt, kind_below, True
    if not consumed:
        return None
    endpoints.extend((_target_names(target), kind) for target in current)
    bound: dict[str, str | None] = {}
    for target_names, endpoint_kind in endpoints:
        for name in target_names:
            bound[name] = (
                _louder_kind(bound[name], endpoint_kind)
                if name in bound
                else endpoint_kind
            )
    return bound


# Expression wrappers a value passes through without being consumed. A literal
# inside one is still the value the surrounding statement binds or hands on.
# Two kinds, and the difference is load-bearing. fix(#996 review): they shared
# one tuple and one `climbed` flag, which conflated "the value here CONTAINS
# the vector" with "the value here IS the vector". `cmd = ["gdalinfo", "-json"]
# + []` then `consume(cmd[0])` was then read as a container access yielding the
# argv — but a BinOp yields the vector itself, so `cmd[0]` is only a string.
# A false positive on inert data, from an inconsistency in the flag rather than
# from a missing rule.
#
# A CONTAINER wrapper holds the vector as an element, so climbing out of one
# means the name above binds a container.
_CONTAINER_WRAPPERS = (
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Starred,
)
# A VALUE wrapper evaluates to the vector: `[...] if flag else [...]`,
# `[...] + extra`, `fallback or [...]`. Climbing out still leaves you holding
# the vector, so it must not set the container flag.
_VALUE_WRAPPERS = (
    ast.IfExp,
    ast.BinOp,
    ast.BoolOp,
)
_TRANSPARENT_WRAPPERS = (*_CONTAINER_WRAPPERS, *_VALUE_WRAPPERS)

# What ITERATING a path that holds the vector hands to a loop target
# (fix(#1394), codex round 1). "Holds a container" is one bit and iteration
# needs two, because the containers do not agree: a list, tuple or set yields
# its elements, so `for cmd in commands:` receives the argv, while a dict
# yields its KEYS, so the same line over `{"inspect": ["gdalinfo", path]}`
# receives the string "inspect" and the argv never moves — flagging it would be
# a false positive on inert data, the #996 class. Note the rule is about WHERE
# in the dict the literal sits, not about `dict` as a type: a literal used as a
# KEY is exactly what iteration yields.
#
# Every other question this analysis asks still only wants the one bit, and
# asks it as `kind is not None`.
_ITER_YIELDS_VECTOR = "vector"
_ITER_YIELDS_OTHER = "other"


def _container_iteration_kind(container: ast.AST, held: ast.AST) -> str:
    """What iterating ``container`` yields, given that ``held`` is in it."""
    if isinstance(container, ast.Dict):
        return (
            _ITER_YIELDS_VECTOR
            if any(key is held for key in container.keys)
            else _ITER_YIELDS_OTHER
        )
    return _ITER_YIELDS_VECTOR


# How much FOLLOWING each kind licenses, so two answers for one path merge to
# the louder rather than to whichever arrived last (fix(#1394), codex round 3).
# `None` — the path IS the vector — follows least: a subscript on it yields an
# element and stops the escape. Holding a container follows more, because the
# subscript then yields the vector and the extraction is chased; and a
# container that yields the vector when iterated follows most, because the loop
# rule applies on top. Merging toward the loud end keeps a conflict on the
# reported side, which is the direction this gate is built to fail in.
_KIND_LOUDNESS: dict[str | None, int] = {
    None: 0,
    _ITER_YIELDS_OTHER: 1,
    _ITER_YIELDS_VECTOR: 2,
}


def _louder_kind(left: str | None, right: str | None) -> str | None:
    """The kind of two that licenses more following."""
    return left if _KIND_LOUDNESS[left] >= _KIND_LOUDNESS[right] else right


def _queue_path(
    queue: dict[str, str | None],
    resolved: dict[str, str | None],
    path: str,
    kind: str | None,
) -> None:
    """Add ``path`` to the worklist unless this kind is already covered.

    Covered means a kind at least this loud has been walked (``resolved``) or
    is already queued, so nothing is followed twice for the same reason and a
    LOUDER kind arriving late still gets its pass. Loudness only ever rises and
    there are three values, so a path is walked at most three times.
    """
    for table in (resolved, queue):
        if path in table and _KIND_LOUDNESS[table[path]] >= _KIND_LOUDNESS[kind]:
            return
    queue[path] = kind


def _default_parameter_name(args: ast.arguments, value: ast.AST) -> str | None:
    """The parameter a default value belongs to, positionally or by keyword."""
    positional = [*args.posonlyargs, *args.args]
    if value in args.defaults:
        # Defaults are right-aligned against the positional parameters.
        idx = args.defaults.index(value)
        offset = len(positional) - len(args.defaults)
        if 0 <= offset + idx < len(positional):
            return positional[offset + idx].arg
    if value in args.kw_defaults:
        kw = args.kwonlyargs[args.kw_defaults.index(value)]
        return kw.arg
    return None


def _defaults_owner(node: ast.AST) -> ast.AST | None:
    """The callable whose SIGNATURE holds ``node`` as a default, if any.

    The default itself is evaluated in the enclosing scope, but the parameter
    it binds lives in the callable's own body — so that body, not the
    enclosing scope, is where its uses are (fix(#996 review)).
    """
    prev: ast.AST = node
    current: ast.AST | None = getattr(node, "_rule2_parent", None)
    while current is not None:
        if isinstance(current, _SCOPE_NODES):
            return current if prev is getattr(current, "args", None) else None
        prev = current
        current = getattr(current, "_rule2_parent", None)
    return None


def _binding_targets(
    node: ast.AST, *, inherited: str | None = None
) -> dict[str, str | None]:
    """Names this literal's value is reachable through in its own scope.

    Climbs out of transparent wrappers first (fix(#996 review)), so
    ``commands = {"inspect": ["gdalinfo", path]}`` binds through ``commands``
    and a later ``subprocess.run(commands["inspect"])`` still counts. Covers
    ``=`` including unpacking, annotated ``=``, the walrus, and the loop target
    of a ``for``/``async for``/comprehension over a literal.

    Returns ``{path: container_kind}``. A kind of ``None`` means that path
    refers to the command vector ITSELF, which is what decides that a subscript
    on it yields an element rather than the vector. Otherwise the path refers
    to something WRAPPING the vector, and the kind says what ITERATING that
    wrapper hands over (fix(#1394), see ``_container_iteration_kind``); callers
    that only need the one bit ask ``kind is not None``.

    Per path, not one kind for the set (codex round 15): a chained unpacking
    can end at different depths, and one answer for every name could only be
    wrong about some of them.

    ``inherited`` is the kind ``node``'s value ALREADY carries when the AST
    does not show it — a name known to hold a container of argvs, say. The
    returned kind is relative to that, so a caller passing it must not add it
    back (fix(#1394), codex round 14).
    """
    current: ast.AST = node
    parent = getattr(current, "_rule2_parent", None)
    container_kind: str | None = inherited
    # Every wrapper climbed, innermost first: the index the value occupies in
    # it (None when the wrapper is not a positional display), the kind of what
    # is INSIDE it, and whether it adds a LEVEL at all. An unpacking pattern
    # consumes these one for one, so the pairing needs the whole chain, not
    # just its outermost link.
    chain: list[tuple[int | None, str | None, bool]] = []
    # fix(#1394), codex round 14: an INHERITED container is an unpackable level
    # too, and the innermost one — `alias, = commands` takes `commands` apart
    # exactly as `alias, = (["gdalinfo", path],)` takes the display apart, and
    # leaves `alias` holding the vector. Only for a container that yields the
    # vector: unpacking a MAPPING yields keys, which are not commands, and that
    # falls through to the conservative answer instead.
    if inherited == _ITER_YIELDS_VECTOR:
        chain.append((_ANY_POSITION, None, True))
    while isinstance(parent, _TRANSPARENT_WRAPPERS):
        # fix(#1394), codex round 8: a VALUE wrapper only carries the value in
        # a position it can evaluate to. `empty = [] if commands else ()` never
        # binds `commands` to `empty`, and neither does
        # `nothing = commands and ()`; climbing anyway put an always-empty name
        # on the follow list, where the loop rule then reported an argv that
        # cannot run. Stopping here leaves no branch below matching, which is
        # the accurate answer: nothing above binds this value.
        if isinstance(parent, _VALUE_WRAPPERS) and not _is_value_position(
            current, parent
        ):
            break
        # fix(#1394), codex rounds 4 and 5: a star and the display around it
        # are ONE level, not two. `*X` splices X's ELEMENTS into that display,
        # which PRESERVES X's own depth rather than adding or removing one:
        # `[*["gdalinfo", path]]` is `["gdalinfo", path]`, still the vector,
        # while `[*(["gdalinfo", path],)]` is `[["gdalinfo", path]]`, still a
        # container of it. Counting both nodes reported the first (iterating it
        # yields strings, not commands); resetting to "is the vector" hid the
        # second, which is the direction that actually matters. So neither the
        # star nor the step out of it moves the kind.
        starred = isinstance(parent, ast.Starred) or isinstance(current, ast.Starred)
        kind_below = container_kind
        # Only a CONTAINER wrapper means the level above holds the vector
        # rather than being it (fix(#996 review)) — which is the same thing as
        # adding a level for an unpacking pattern to consume.
        adds_level = isinstance(parent, _CONTAINER_WRAPPERS) and not starred
        if adds_level:
            container_kind = _container_iteration_kind(parent, current)
        index = (
            parent.elts.index(current)
            if adds_level
            and isinstance(parent, (ast.Tuple, ast.List))
            and current in parent.elts
            else None
        )
        chain.append((index, kind_below, adds_level))
        current = parent
        parent = getattr(current, "_rule2_parent", None)
    chain.reverse()  # outermost first, the order an unpacking consumes them

    if isinstance(parent, ast.Assign) and parent.value is current:
        unpacked = _unpacked_binding(parent.targets, chain, container_kind)
        if unpacked is not None:
            return unpacked
        return {
            n: container_kind
            for target in parent.targets
            for n in _target_names(target)
        }
    # fix(#996 review): the same path rule as the Assign branch above. An
    # annotated `box.cmd: list[str] = [...]` binds a path exactly like the
    # unannotated form; requiring a bare Name here dropped it. A walrus target
    # is always a Name, so it rides the same branch.
    if isinstance(parent, (ast.AnnAssign, ast.NamedExpr)) and parent.value is current:
        return {n: container_kind for n in _target_names(parent.target)}
    # fix(#996 review): `cmd = []` then `cmd += ["gdalinfo", path]` assembles a
    # real argv, and the literal's parent is an AugAssign that none of the
    # branches above matched. The kind is None regardless: `+=` splices the
    # elements in, so the target holds the vector rather than a container.
    if isinstance(parent, ast.AugAssign) and parent.value is current:
        return {n: None for n in _target_names(parent.target)}
    # fix(#996 review): `def run(cmd=("gdalinfo", "-json")): subprocess.run(cmd)`
    # executes the default on every bare call. The literal sits in the
    # signature, so the escape walk stops at the function boundary and no
    # assignment matches — the vector bound to the parameter NAME is the link.
    if isinstance(parent, ast.arguments):
        name = _default_parameter_name(parent, current)
        if name:
            return {name: None}
    # fix(#996 review): `for cmd in (["gdalinfo", path],): subprocess.run(cmd)`
    # reaches an exec through the loop target. Same for `async for` and for a
    # comprehension's generator.
    #
    # Only when the literal is an ELEMENT the iteration actually yields, which
    # is what the kind records. `for tool in ["gdalinfo", "ogrinfo"]` binds each
    # STRING to the target, not the list, and treating the list as escaping
    # through it flagged ordinary tool-name data.
    if container_kind == _ITER_YIELDS_VECTOR:
        # The loop target receives an ELEMENT of the iterable, so it is the
        # vector itself, not a container of it.
        loop_targets = _loop_target_paths(current)
        if loop_targets:
            return {n: None for n in loop_targets}
    return {}


def _enclosing_statement(node: ast.AST, body: list) -> ast.stmt | None:
    """The statement of ``body`` that contains ``node``, if any."""
    current: ast.AST | None = node
    while current is not None:
        parent = getattr(current, "_rule2_parent", None)
        if isinstance(current, ast.stmt) and current in body:
            return current
        current = parent
    return None


def _overwritten_before(used: ast.AST, binding: ast.AST, path: str) -> bool:
    """True when ``path`` is re-bound between its binding and this use.

    fix(#996 review): `cmd = ["gdalinfo", ...]` then `cmd = ["echo", "ok"]`
    then `run(cmd)` reported the GDAL literal as escaping, although nothing
    GDAL can execute — ordinary variable reuse producing a CI-blocking false
    positive.

    Deliberately narrow. Only rebindings in the SAME statement list count, so
    "later" really means later: #974 round 10 already declined statement-order
    analysis for the rasterio resolver, and a rebinding under an `if` is not
    ordered against a use in the `else`. Where order is not straight-line this
    returns False and the use still counts, which keeps the miss on the
    reported side.
    """
    binding_stmt = None
    body = None
    current: ast.AST | None = binding
    while current is not None and binding_stmt is None:
        parent = getattr(current, "_rule2_parent", None)
        for attr in ("body", "orelse", "finalbody"):
            candidate = getattr(parent, attr, None)
            if isinstance(candidate, list) and current in candidate:
                binding_stmt, body = current, candidate
                break
        current = parent
    if binding_stmt is None or body is None:
        return False

    use_stmt = _enclosing_statement(used, body)
    if use_stmt is None:
        return False
    start, end = body.index(binding_stmt), body.index(use_stmt)
    if end <= start:
        return False
    for stmt in body[start + 1 : end]:
        targets: list = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            targets = [stmt.target]
        if any(path in _target_names(tgt) for tgt in targets):
            return True
    return False


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


def _derived_paths(used: ast.expr, kind: str | None) -> list[tuple[str, str | None]]:
    """The paths one load of a tracked path hands the vector on to.

    ``used`` is a load of a path the literal is reachable through, and ``kind``
    is what that path holds (see ``_container_iteration_kind``). Returns
    ``(path, kind)`` pairs for everything the load leads to, which the caller
    merges into its worklist.
    """
    derived: list[tuple[str, str | None]] = []
    if kind is not None:
        # fix(#996 review): reading a CONTAINER through a subscript or
        # attribute yields the vector — `commands = {...}` then
        # `cmd = commands["inspect"]`. Follow that extraction, or the alias
        # chain stops dead at the container.
        parent = getattr(used, "_rule2_parent", None)
        if isinstance(parent, (ast.Subscript, ast.Attribute)) and parent.value is used:
            # An INDEX of a container yields the vector, one level down, so it
            # inherits nothing. A SLICE yields a container of the same things,
            # so `sliced = commands[:]` inherits this path's kind (codex round
            # 9). Fixed here as well as in `_depth_preserving_ancestor` because
            # the alias path went around the loop's own iterable once already
            # (round 8).
            sliced = isinstance(parent, ast.Subscript) and isinstance(
                parent.slice, ast.Slice
            )
            derived += list(
                _binding_targets(parent, inherited=kind if sliced else None).items()
            )
        # fix(#1394): ITERATING a container hands each element — the argv — to
        # the loop target, exactly as subscripting it hands over one.
        # `_binding_targets` already reads that off the AST when the container
        # is written in place (`for cmd in (["gdalinfo", path],):`); once the
        # container has a NAME (`commands = (["gdalinfo", path],)` then `for cmd
        # in commands:`) the AST no longer says so, and only the followed kind
        # carries what the container was. Without it the shape reported ZERO
        # argv sites: invisible to the gate, so neither creditable nor
        # reportable — the one failure direction the #1077 allowlist inversion
        # exists to remove.
        #
        # Gated on the kind for the same reason #996 gated its in-place twin:
        # iterating the VECTOR (`for part in cmd:`) yields strings, and
        # iterating a dict that holds the argv as a VALUE yields keys (codex
        # round 1).
        if kind == _ITER_YIELDS_VECTOR:
            derived += [(n, None) for n in _loop_target_paths(used)]
    # A wrapper at the ALIAS site is the outermost one now, so it decides what
    # iterating the alias yields; with no new wrapper the kind carries over
    # unchanged, and an UNPACKING there takes one off. All three are the same
    # question, so the inherited kind goes in and the answer comes back
    # absolute rather than being re-applied here (codex round 14).
    derived += list(_binding_targets(used, inherited=kind).items())
    return derived


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
    bindings = _binding_targets(node)
    scope = _defaults_owner(node) or _scope_root(node)
    if not bindings or scope is None:
        return best

    # fix(#996 review): follow re-aliasing to a fixed point. `cmd = [...]`,
    # `alias = cmd`, `subprocess.run(alias)` reaches an exec through a name the
    # literal was never directly bound to, and stopping at the first hop lost
    # it — a regression against the pre-#996 scan, which flagged everything.
    # The overwrite guard below applies only to paths the literal binds
    # DIRECTLY. For a derived alias the statement that introduces it would
    # itself look like an overwrite, and over-reporting is the safe side.
    original_paths = set(bindings)
    # fix(#1394), codex round 3: path -> kind, MERGED, never overwritten. The
    # worklist used to be a set of pairs collapsed with `{n: c for n, c in
    # batch}`, so one path reached with two kinds — `x = commands` beside
    # `x = {"label": commands}` — kept whichever the set happened to yield
    # last, and the gate's verdict moved with PYTHONHASHSEED. It predates the
    # kinds (the same collapse could pick either boolean) and widens with them.
    resolved: dict[str, str | None] = {}
    pending: dict[str, str | None] = {}
    for name, name_kind in bindings.items():
        _queue_path(pending, resolved, name, name_kind)
    while pending:
        current_paths = pending
        pending = {}
        for queued, queued_kind in current_paths.items():
            resolved[queued] = _louder_kind(
                resolved.get(queued, queued_kind), queued_kind
            )
        for used in ast.walk(scope):
            if not isinstance(used, (ast.Name, ast.Attribute, ast.Subscript)):
                continue
            if not isinstance(getattr(used, "ctx", None), ast.Load):
                continue
            path = _expr_path(used)
            if path is None or path not in current_paths:
                continue
            root = _expression_root_name(used)
            if root is not None and not _use_reaches_the_binding(root, scope, rel):
                continue
            if path in original_paths and _overwritten_before(used, node, path):
                continue
            kind = current_paths[path]
            best = max(best, _escape_kind(used, vector=kind is None))
            if best == _ESCAPE_CALL:
                return best
            for name, derived_kind in _derived_paths(used, kind):
                _queue_path(pending, resolved, name, derived_kind)
    return best


# fix(#1857 item 2): callees that take the program as their FIRST POSITIONAL
# argument, so an argv can exist with no list or tuple display anywhere. The
# `exec*` families are here for completeness rather than because the tree uses
# them. Deliberately absent: `os.spawnl` and its variants, whose leading
# argument is a mode rather than the program; `subprocess.run` / `Popen`, which
# take the whole argv as ONE argument and are therefore already covered by the
# display rule; and the shell family (`create_subprocess_shell`, `shell=True`,
# `os.system`, `os.popen`), which has no argv at all -- see the module
# docstring.
_POSITIONAL_ARGV_SPAWNERS = frozenset(
    {
        "create_subprocess_exec",
        "subprocess_exec",
        "execl",
        "execlp",
        "execle",
        "execlpe",
        "execv",
        "execvp",
        "execve",
        "execvpe",
    }
)


def _positional_argv_tool(node: ast.AST) -> str | None:
    """The GDAL tool a varargs spawn names, when argv is passed positionally.

    Matched on the callee's terminal name, so `asyncio.create_subprocess_exec`,
    a `from asyncio import create_subprocess_exec` and `loop.subprocess_exec`
    all read the same. That is looser than the identity resolution the helper
    credit uses, and deliberately so: this side of the gate decides what to
    LOOK at, where a false positive costs a reviewed allowlist entry, while
    credit decides what to EXEMPT, where a false positive costs the guarantee.
    """
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        callee: str | None = func.attr
    elif isinstance(func, ast.Name):
        callee = func.id
    else:
        callee = None
    if callee not in _POSITIONAL_ARGV_SPAWNERS:
        return None
    head = node.args[0]
    if not isinstance(head, ast.Constant):
        return None
    return _gdal_cli_tool_name(head.value)


def _iter_argv_sites(rel: str, tree: ast.Module):
    """Yield (tool, argv node, the argv's tail expressions) for one module.

    The single definition of "an argv site", shared by the GDAL CLI env gate
    and the vector driver policy so the two cannot drift apart on what they
    are looking at. Requires ``_annotate_parents(tree)`` to have run.

    The tail is what follows the program: the remaining display elements, or
    the remaining positional arguments. Callers scan it for a literally remote
    source, which is the one thing a safe env cannot defend against.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first = node.elts[0]
            tool = (
                _gdal_cli_tool_name(first.value)
                if isinstance(first, ast.Constant)
                else None
            )
            if tool is None:
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
                # contains -- a dataset or output path may legitimately be
                # named `ogrinfo` -- and shape alone cannot tell the two apart.
                continue
            yield tool, node, node.elts[1:]
            continue
        tool = _positional_argv_tool(node)
        if tool is not None:
            # No escape test and no name-list exemption: this node is the
            # spawn, so it executes by construction, and there is no display
            # that could be mistaken for inert data.
            yield tool, node, node.args[1:]


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
        # codex round 9: tuples build argv vectors just as well as lists
        # (subprocess.run(("gdalinfo", url))) — match both. fix(#1857 item 2):
        # and a varargs spawn that builds no display at all.
        for tool_name, node, tail in _iter_argv_sites(rel, tree):
            total_argv_sites += 1
            func_node = _enclosing_function_node(node)
            func_name = func_node.name if func_node is not None else "<module>"
            scope: ast.AST = func_node if func_node is not None else tree
            # codex round 7 on #974: an argv carrying a literally-remote
            # element gets no safe-env credit — the safe env cannot stop a
            # redirect (#937), so the site needs its own reviewed entry.
            remote = any(_is_remote_literal(elt) for elt in tail)
            # fix(#1846 codex P2): which helper this argv may be credited by
            # depends on the tool family. A raster CLI needs the raster clamps
            # and nothing else vouches for it; a vector CLI may use any of the
            # three here, because `test_vector_gdal_argv_restricts_input_drivers`
            # is what pins the exact one per site and this test would otherwise
            # duplicate that judgement in a second place.
            required = (
                SUBPROCESS_ENV_HELPERS
                if tool_name in VECTOR_CLI_TOOLS
                else (SAFE_SUBPROCESS_ENV_HELPER,)
            )
            if not remote and _argv_has_safe_env_credit(node, scope, rel, required):
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
                wanted = (
                    " or ".join(SUBPROCESS_ENV_HELPERS)
                    if tool in VECTOR_CLI_TOOLS
                    else SAFE_SUBPROCESS_ENV_HELPER
                )
                violations.append(
                    f"{rel}:{lines} ({func_name}) builds a {tool} argv without "
                    f"{wanted} in the same function — route the subprocess env "
                    "through it, or allowlist this exact (module, function, "
                    "tool) with a justification (AGENTS.md Rule 2, #936). "
                    "Another safe-env helper does not substitute: they clamp "
                    "different things (#1846)"
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


def _is_named_helper_call(expr: ast.expr, kind: str, rel: str) -> bool:
    """True for a call to the canonical helper bound under ``kind``.

    Only the direct ``from <canonical module> import <helper>`` spelling earns
    credit; a module alias would need its own tracking, the tree does not use
    one, and the conservative answer to a shape this cannot read is no.
    """
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Name):
        if _resolve_credit(func.id, kind, func, rel):
            return True
        # `run_in_thread_draining(helper, *args)` runs the helper; the name is
        # the first positional argument rather than the call head.
        if func.id == THREAD_OFFLOAD_HELPER and expr.args:
            first = expr.args[0]
            return isinstance(first, ast.Name) and _resolve_credit(
                first.id, kind, first, rel
            )
    return False


def _argv_has_helper_credit(
    argv: ast.AST,
    scope: ast.AST,
    rel: str,
    kind: str,
    *,
    result_is_the_protection: bool = True,
) -> bool:
    """Same credit rules as the env half: an eager, named-shape call.

    ``result_is_the_protection`` is what the shape check turns on. For a pure
    helper that RETURNS the clamp, a call whose result goes nowhere clamps
    nothing, which is what ``_credit_shape_is_named`` refuses. For a validator
    the protection IS the raise, so a bare statement call is the correct
    spelling and there is no discarded result to refuse; only the position
    rules apply (fix(#1846)).
    """
    for node in ast.walk(scope):
        if not _is_named_helper_call(node, kind, rel):
            continue
        if result_is_the_protection and not _credit_shape_is_named(node, scope):
            continue
        if _credit_position_reaches(node, argv):
            return True
    return False


def _iter_vector_cli_argv_sites(modules: list[tuple[str, ast.Module]]):
    """Yield (rel, function, tool, argv node, enclosing scope) per vector argv.

    Same detection as ``_collect_gdal_cli_violations`` -- through the shared
    ``_iter_argv_sites`` so the two cannot drift on what an argv site is --
    narrowed to the two OGR command-line tools.
    """
    for rel, tree in modules:
        _annotate_parents(tree)
        for tool, node, _tail in _iter_argv_sites(rel, tree):
            if tool not in VECTOR_CLI_TOOLS:
                continue
            func_node = _enclosing_function_node(node)
            func_name = func_node.name if func_node is not None else "<module>"
            scope: ast.AST = func_node if func_node is not None else tree
            yield rel, func_name, tool, node, scope


def _collect_vector_driver_violations(
    modules: list[tuple[str, ast.Module]],
    policy: dict[tuple[str, str, str], tuple[int, str, str | None, str]],
) -> tuple[list[str], int]:
    """Return (violations, total vector CLI argv count)."""
    violations: list[str] = []
    counts: dict[tuple[str, str, str], int] = {}
    lines: dict[tuple[str, str, str], list[int]] = {}
    # fix(#1857 item 1): keys whose env helper this file cannot resolve. The
    # site loop below feeds that string into name resolution as a binding
    # KIND, and _classify_name indexes the per-scope kind map with it, so an
    # unrecognised name raised KeyError from inside _resolve_credit before the
    # authored violation above ever reached the caller. CI still failed, but
    # on a traceback naming a helper rather than on the sentence that says
    # which entry is wrong and what the allowed names are. Only the env helper
    # earns a place here: it is the one policy field that becomes a name to
    # resolve. An unknown KIND is inert, since every use of it is a set
    # membership test that simply answers False.
    unresolvable_env_helper: set[tuple[str, str, str]] = set()
    total = 0

    for key, (_count, kind, env_helper, justification) in sorted(policy.items()):
        if kind not in _POLICY_KINDS:
            violations.append(
                f"unknown VECTOR_CLI_DRIVER_POLICY kind {kind!r} for {key}"
            )
        if env_helper is not None and env_helper not in SUBPROCESS_ENV_HELPERS:
            unresolvable_env_helper.add(key)
            violations.append(
                f"VECTOR_CLI_DRIVER_POLICY names {env_helper!r} for {key}, which "
                f"is not one of {', '.join(SUBPROCESS_ENV_HELPERS)}"
            )
        if not justification.strip():
            violations.append(f"blank VECTOR_CLI_DRIVER_POLICY justification for {key}")

    for rel, func_name, tool, node, scope in _iter_vector_cli_argv_sites(modules):
        total += 1
        key = (rel, func_name, tool)
        counts[key] = counts.get(key, 0) + 1
        lines.setdefault(key, []).append(node.lineno)
        entry = policy.get(key)
        if entry is None:
            violations.append(
                f"{rel}:{node.lineno} ({func_name}) builds a {tool} argv with no "
                "VECTOR_CLI_DRIVER_POLICY entry — say what its input is and "
                "clamp it accordingly (AGENTS.md Rule 2, #1846)"
            )
            continue
        if key in unresolvable_env_helper:
            # Already reported above, with the name and the allowed set. Asking
            # whether an unresolvable helper covers this argv is not a question
            # with an answer, and attempting it is what used to raise.
            continue
        _expected, kind, env_helper, _why = entry
        if kind in _POLICY_NEEDS_DRIVER_ALLOWLIST:
            if not _argv_has_helper_credit(node, scope, rel, _KIND_DRIVER_ALLOWLIST):
                violations.append(
                    f"{rel}:{node.lineno} ({func_name}) opens a staged upload "
                    f"with a {tool} argv but no {DRIVER_ALLOWLIST_HELPER} call "
                    "covers it — an unrestricted driver set decides what the "
                    "file is, and some OGR drivers read a document as "
                    "instructions naming somewhere else to read from "
                    "(AGENTS.md Rule 2, #1846)"
                )
            if not _argv_has_helper_credit(
                node,
                scope,
                rel,
                _KIND_CONTENT_CHECK,
                result_is_the_protection=False,
            ):
                violations.append(
                    f"{rel}:{node.lineno} ({func_name}) opens a staged upload "
                    f"with a {tool} argv but no {CONTENT_CHECK_HELPER} call "
                    "covers it — a SQLite-family upload carries its own schema, "
                    "and a schema row can name a source outside the file that "
                    "no driver clamp can exclude (AGENTS.md Rule 2, #1846)"
                )
        if env_helper is not None and not _argv_has_safe_env_credit(
            node, scope, rel, (env_helper,)
        ):
            violations.append(
                f"{rel}:{node.lineno} ({func_name}) builds a {tool} argv with no "
                f"{env_helper} call covering it — that exact helper, not "
                "whichever safe env is nearest: the three clamp different "
                "things, and a staged upload credited by the raster one "
                "carries no vector driver skip at all "
                "(AGENTS.md Rule 2, #1846)"
            )

    for key, count in sorted(counts.items()):
        entry = policy.get(key)
        if entry is not None and count != entry[0]:
            rel, func_name, tool = key
            seen = ",".join(str(n) for n in lines[key])
            violations.append(
                f"{rel} ({func_name}) has {count} {tool} argv(s) at line(s) {seen} "
                f"but VECTOR_CLI_DRIVER_POLICY expects exactly {entry[0]} — each "
                "one needs its own review, not a ride on the entry"
            )

    for key in sorted(set(policy) - set(counts)):
        violations.append(
            f"stale VECTOR_CLI_DRIVER_POLICY entry {key} — no matching vector "
            "CLI argv exists; remove the entry"
        )

    return violations, total


def test_policy_naming_an_unknown_env_helper_reports_instead_of_raising():
    """A typo in VECTOR_CLI_DRIVER_POLICY must read as a sentence.

    fix(#1857 item 1). The validator already authored the right message, and
    nobody ever saw it. The site loop resolves the named env helper as a
    binding kind, and the per-scope kind map raised KeyError on a name it did
    not know, so the run died on a traceback before the violation list was
    returned. A gate whose misconfiguration surfaces as an internal error
    teaches the next person to distrust the gate rather than fix the entry.

    The site key is a REAL one, because the crash needed an argv site to match
    it; a policy entry pointing nowhere just reports as stale.
    """
    key = ("processing/export/ogr.py", "run_ogr2ogr_export", "ogr2ogr")
    policy = dict(VECTOR_CLI_DRIVER_POLICY)
    assert key in policy, (
        "the site this test names has moved; point it at another real vector "
        "CLI argv site, since an entry with no matching site reports as stale "
        "and never reaches the resolution that used to raise"
    )
    count, kind, real_helper, why = policy[key]
    assert real_helper is not None
    typo = real_helper + "_typo"
    assert typo not in SUBPROCESS_ENV_HELPERS
    policy[key] = (count, kind, typo, why)

    violations, _total = _collect_vector_driver_violations(_app_modules(), policy)

    named = [v for v in violations if typo in v]
    assert len(named) == 1, (
        f"expected exactly one violation naming {typo!r}, got {violations}"
    )
    # The message has to carry the allowed set, or the reader has to go read
    # this file to learn what they may write instead.
    for allowed in SUBPROCESS_ENV_HELPERS:
        assert allowed in named[0], named[0]

    # And the entry's own credit check is skipped rather than attempted, so
    # the run does not also blame the site for a policy typo.
    assert not [v for v in violations if "run_ogr2ogr_export" in v and typo not in v], (
        violations
    )


def test_vector_gdal_argv_restricts_input_drivers():
    """Every staged-upload ogrinfo/ogr2ogr argv carries BOTH clamps.

    fix(#1846, GHSA-hrf5-v3cq-frx5). The gate that existed passed while an
    uploaded archive could make GDAL pick a driver that reads the document as
    instructions and go fetch what it names, because three sites were exempted
    on a justification about the input being a local file. It was. That is not
    the same claim as the driver set being bounded, and this test asks the
    second question directly: for a caller-supplied file, is there an allowlist
    saying which drivers may be attempted, and an env saying which may not be
    registered at all. Either alone is a real defense; the pair is what makes a
    gap in one survivable.
    """
    violations, total = _collect_vector_driver_violations(
        _app_modules(), VECTOR_CLI_DRIVER_POLICY
    )
    assert not violations, "\n".join(violations)
    assert total >= MIN_VECTOR_CLI_ARGV_SITES, (
        f"detector saw only {total} vector GDAL CLI argv site(s); the codebase "
        f"has at least {MIN_VECTOR_CLI_ARGV_SITES} — the scan has gone blind, "
        "fix the detector before trusting this guard"
    )


def test_every_sqlite_family_extension_is_content_checked():
    """The two tables that decide "is this a database" must agree.

    fix(#1846, GHSA-hrf5-v3cq-frx5). `-if GPKG` and `-if SQLite` are the two
    allowed drivers that read a schema, and a schema row can name a source
    outside the file. Adding an extension to the driver table that maps to
    either of them, without adding it to the set the content check covers,
    would open the hole again from the other end -- so this asserts the
    inclusion rather than trusting two lists to be edited together.
    """
    from app.processing.ingest.gdal_drivers import (
        ARCHIVE_MEMBER_DRIVERS,
        _DRIVERS_BY_EXTENSION,
    )
    from app.processing.ingest.validation import (
        SQLITE_FAMILY_EXTENSIONS,
        ZIP_CONTAINER_EXTENSIONS,
    )

    schema_readers = {"GPKG", "SQLite"}
    uncovered = sorted(
        extension
        for extension, drivers in _DRIVERS_BY_EXTENSION.items()
        if schema_readers & set(drivers)
        and drivers is not ARCHIVE_MEMBER_DRIVERS
        and extension not in SQLITE_FAMILY_EXTENSIONS
    )
    assert not uncovered, (
        f"{uncovered} may be opened by a schema-reading driver but is not "
        "content-checked; add it to SQLITE_FAMILY_EXTENSIONS"
    )

    # And an archive can carry one as a member, so every container extension
    # has to be scanned for members too.
    assert schema_readers & set(ARCHIVE_MEMBER_DRIVERS)
    assert ZIP_CONTAINER_EXTENSIONS, "container list went empty"


# fix(#1857 item 2): the shape the gate could not see. Both fixtures spawn the
# same tool with the same arguments and differ only in the env, so a pass on
# the clamped one and a report on the other isolates exactly what is measured.
# Written as source rather than as a file in app/, because a real one would be
# a real unclamped subprocess.
_POSITIONAL_ARGV_UNCLAMPED = """
import asyncio


async def probe(path):
    proc = await asyncio.create_subprocess_exec(
        "ogrinfo", "-so", path, stdout=asyncio.subprocess.PIPE
    )
    return proc
"""

_POSITIONAL_ARGV_CLAMPED = """
import asyncio

from app.processing.raster.vrt import gdal_vector_safe_env


async def probe(path):
    proc = await asyncio.create_subprocess_exec(
        "ogrinfo",
        "-so",
        path,
        stdout=asyncio.subprocess.PIPE,
        env=gdal_vector_safe_env(),
    )
    return proc
"""

_POSITIONAL_FIXTURE_REL = "processing/ingest/_positional_spawn_fixture.py"


def _fixture_modules(source: str) -> list[tuple[str, ast.Module]]:
    return [(_POSITIONAL_FIXTURE_REL, ast.parse(source))]


def test_positional_argv_is_seen_by_the_cli_env_gate():
    """An argv passed as separate arguments is still an argv.

    fix(#1857 item 2). Detection keyed on a list or tuple DISPLAY whose head
    names a GDAL tool, so a spawn that never builds one was invisible to every
    rule in this file: no env requirement, no allowlist entry, no count. The
    tree had no such site, which is why it went unnoticed, and a gate that goes
    quiet on a shape it cannot read fails in the wrong direction.

    The clamped fixture is the half that makes this a measurement rather than a
    tautology. Without it, "the new shape reports" would also be true of a
    change that reported every varargs spawn unconditionally.
    """
    violations, total = _collect_gdal_cli_violations(
        _fixture_modules(_POSITIONAL_ARGV_UNCLAMPED), {}
    )
    assert total == 1, f"the positional spawn was not counted as an argv: {total}"
    assert len(violations) == 1, violations
    assert "ogrinfo" in violations[0] and "probe" in violations[0], violations[0]

    violations, total = _collect_gdal_cli_violations(
        _fixture_modules(_POSITIONAL_ARGV_CLAMPED), {}
    )
    assert total == 1, total
    assert not violations, violations


def test_positional_argv_is_seen_by_the_vector_driver_policy():
    """The same shape reaches the per-site driver policy, from one change.

    fix(#1857 item 2). Both gates read what an argv site is from
    ``_iter_argv_sites``, so widening detection in one place widens both. A
    positional ogrinfo with no entry reports as unreviewed rather than as
    absent, which is the answer that gets a new site looked at.
    """
    violations, total = _collect_vector_driver_violations(
        _fixture_modules(_POSITIONAL_ARGV_UNCLAMPED), {}
    )
    assert total == 1, total
    assert len(violations) == 1, violations
    assert "VECTOR_CLI_DRIVER_POLICY" in violations[0], violations[0]


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


def test_guard_argv_iterated_from_a_named_container_is_detected():
    """fix(#1394): the container above wearing a name.

    ``commands = (["gdalinfo", path],)`` then ``for cmd in commands:`` reported
    ZERO argv sites, because extraction followed subscript and attribute loads
    out of a container but not ``For.iter``. A site the collector cannot see is
    neither creditable nor reportable, which is the failure direction the
    #1077 credit inversion exists to remove — so this is pinned as a DETECTION
    property first: the site exists, and then the ordinary credit rules decide
    it.
    """
    unclamped, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def looped(path):\n"
            "    commands = (['gdalinfo', path],)\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, unclamped)
    assert len(unclamped) == 1 and "(looped)" in unclamped[0]

    # The same site, clamped. The env is hoisted ABOVE the loop, which is the
    # spelling that credits: it shares the function body with the argv, so
    # _credit_position_reaches finds them in the same field of the same
    # ancestor.
    clamped, total_clamped = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def looped(path):\n"
            "    commands = (['gdalinfo', path],)\n"
            "    env = gdal_safe_env()\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd, env=env)\n"
        ),
        {},
    )
    assert total_clamped == 1, (total_clamped, clamped)
    assert clamped == []

    # An env built INSIDE the loop body still reports, because a loop body may
    # run zero times (#1077, `_EAGER_POSITIONS`). Pinned so the two rules are
    # read together: this is the verdict the inline `for cmd in (["gdalinfo",
    # path],):` spelling has always had, not a new class of false positive.
    in_loop, total_in_loop = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def looped(path):\n"
            "    commands = (['gdalinfo', path],)\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd, env=gdal_safe_env())\n"
        ),
        {},
    )
    assert total_in_loop == 1, (total_in_loop, in_loop)
    assert len(in_loop) == 1 and "(looped)" in in_loop[0]


def test_guard_iterating_the_vector_itself_binds_strings_not_argvs():
    """The control for fix(#1394): the follow is gated on holding a CONTAINER.

    ``for part in cmd:`` walks the argv's own elements, and a named tool-name
    list is the same shape — binding either to the loop target would flag
    ordinary data, the #996 false-positive class. Both stay inert.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def elements(path):\n"
            "    cmd = ['gdalinfo', path]\n"
            "    for part in cmd:\n"
            "        consume(part)\n"
            "def names():\n"
            "    tools = ['gdalinfo', 'ogrinfo']\n"
            "    for tool in tools:\n"
            "        consume(tool)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_iterating_a_dict_yields_keys_not_the_argv():
    """fix(#1394), codex round 1: not every container yields its contents.

    ``for key in commands:`` over a dict hands over ``"inspect"``; the argv
    stays put, so following the loop target flagged inert data — the #996
    false-positive class, from treating "holds a container" as one bit when
    iteration needs two. Subscripting the same dict is unaffected and still
    reaches the argv (the second case).

    A dict is not uniformly opaque either, which is why the rule reads WHERE the
    literal sits rather than testing for ``dict``: a literal used as a KEY is
    exactly what iteration hands over (the third).
    """
    inert, total = _collect_gdal_cli_violations(
        _mod(
            "def fn(path):\n"
            "    commands = {'inspect': ['gdalinfo', path]}\n"
            "    for key in commands:\n"
            "        consume(key)\n"
        ),
        {},
    )
    assert total == 0, (total, inert)
    assert inert == []

    subscripted, total_subscripted = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = {'inspect': ['gdalinfo', path]}\n"
            "    subprocess.run(commands['inspect'])\n"
        ),
        {},
    )
    assert total_subscripted == 1, (total_subscripted, subscripted)
    assert len(subscripted) == 1 and "(fn)" in subscripted[0]

    keyed, total_keyed = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = {('gdalinfo', path): 'inspect'}\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total_keyed == 1, (total_keyed, keyed)
    assert len(keyed) == 1 and "(fn)" in keyed[0]


def test_guard_destructuring_loop_target_does_not_receive_the_argv():
    """fix(#1394), codex round 2: unpacking splits the argv into strings.

    ``for tool, arg in commands:`` binds ``"gdalinfo"`` and the path, never the
    vector, so linking the literal to either name flagged data that cannot
    execute. Both spellings of the container are checked, because the
    destructuring bug predates the named-container half — the inline form went
    through the same ``_target_names`` flattening on #996.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def named(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    for tool, arg in commands:\n"
            "        consume(tool)\n"
            "def inline(path):\n"
            "    for tool, arg in (['ogrinfo', path],):\n"
            "        consume(arg)\n"
            "def partial_star(path):\n"
            "    commands = [['gdalwarp', path]]\n"
            "    for tool, *rest in commands:\n"
            "        consume(rest)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_a_leading_star_target_keeps_the_argv():
    """fix(#1394), codex rounds 7 and 17: a LEADING star is not destructuring.

    ``for *cmd, in commands:`` binds ``cmd`` to ``list(element)`` — the vector,
    whole — and ``for *cmd, ignored in commands:`` binds it to everything but
    the tail, still a command because it still starts with the tool name.
    Rejecting either with the ordinary positional patterns hid a real argv, the
    direction that matters.

    A star anywhere else is a suffix and keeps getting nothing, which the
    sibling destructuring test pins.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def named(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    for *cmd, in commands:\n"
            "        subprocess.run(cmd)\n"
            "def inline(path):\n"
            "    for *cmd, in (['ogrinfo', path],):\n"
            "        subprocess.run(cmd)\n"
            "def bracketed(path):\n"
            "    commands = [['gdalwarp', path]]\n"
            "    for [*cmd] in commands:\n"
            "        subprocess.run(cmd)\n"
            "def leading_star(path):\n"
            "    commands = [('gdaladdo', path, None)]\n"
            "    for *cmd, ignored in commands:\n"
            "        subprocess.run(cmd)\n"
            "def leading_star_inline(path):\n"
            "    for *cmd, ignored in [('gdal_translate', path, None)]:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 5, (total, violations)
    assert len(violations) == 5, violations
    for name in (
        "(named)",
        "(inline)",
        "(bracketed)",
        "(leading_star)",
        "(leading_star_inline)",
    ):
        assert any(name in v for v in violations), (name, violations)


def test_guard_starring_an_argv_splices_it_into_the_display():
    """fix(#1394), codex rounds 4 and 5: `*` preserves depth.

    ``commands = [*["gdalinfo", path]]`` IS ``["gdalinfo", path]``. Reading the
    outer display as a container of the argv made ``for part in commands:``
    look like it handed over a command when it hands over strings — inert data
    reported, the #996 class. The vector is still a vector, so passing the
    spliced display to a subprocess is still a site (the second case), and
    nesting the star one level deeper puts a real container back (the third).

    Depth PRESERVED, not removed, is the whole rule:
    ``[*(["gdalinfo", path],)]`` splices a one-element tuple and is
    ``[["gdalinfo", path]]``, a container of the argv either way it is read
    (the last two cases). Collapsing that to "is the vector" hid a real argv,
    which is the direction that matters.
    """
    inert, total = _collect_gdal_cli_violations(
        _mod(
            "def fn(path):\n"
            "    commands = [*['gdalinfo', path]]\n"
            "    for part in commands:\n"
            "        consume(part)\n"
        ),
        {},
    )
    assert total == 0, (total, inert)
    assert inert == []

    spawned, total_spawned = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = [*['gdalinfo', path]]\n"
            "    subprocess.run(commands)\n"
        ),
        {},
    )
    assert total_spawned == 1, (total_spawned, spawned)
    assert len(spawned) == 1 and "(fn)" in spawned[0]

    nested, total_nested = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = [[*['gdalinfo', path]]]\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total_nested == 1, (total_nested, nested)
    assert len(nested) == 1 and "(fn)" in nested[0]

    wrapped, total_wrapped = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def iterated(path):\n"
            "    commands = [*(['gdalinfo', path],)]\n"
            "    for cmd in commands:\n"
            "        subprocess.run(cmd)\n"
            "def indexed(path):\n"
            "    commands = [*(['ogrinfo', path],)]\n"
            "    subprocess.run(commands[0])\n"
        ),
        {},
    )
    assert total_wrapped == 2, (total_wrapped, wrapped)
    assert len(wrapped) == 2, wrapped
    assert any("(iterated)" in v for v in wrapped)
    assert any("(indexed)" in v for v in wrapped)


def test_guard_a_wrapped_iterable_is_still_the_same_loop():
    """fix(#1394), codex round 6: the value wrappers reach the loop too.

    ``for cmd in commands or ():`` iterates ``commands``. Requiring the load to
    be the direct child of ``For.iter`` let the ternary, ``+`` and ``or`` forms
    #996 follows everywhere else hide a real argv — a silent miss. A star into
    a display preserves depth the same way (round 5), so it reaches the loop
    too.

    A CONTAINER wrapper must NOT reach it: ``for held in [commands]:`` binds
    the container, one level above the argv. Pinned on the helper, because
    end-to-end the container escapes into the loop body either way and the two
    answers are indistinguishable from the verdict.
    """

    def loop_targets_of(src: str, name: str) -> set[str]:
        tree = ast.parse(src)
        _annotate_parents(tree)
        load = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
        )
        return _loop_target_paths(load)

    assert loop_targets_of("for cmd in commands:\n    pass\n", "commands") == {"cmd"}
    assert loop_targets_of("for cmd in commands or ():\n    pass\n", "commands") == {
        "cmd"
    }
    assert loop_targets_of("for cmd in (*commands,):\n    pass\n", "commands") == {
        "cmd"
    }
    assert loop_targets_of("for held in [commands]:\n    pass\n", "commands") == set()
    # codex round 7: the ternary qualifies through its RESULTS, not its test.
    assert loop_targets_of(
        "for cmd in (commands if flag else ()):\n    pass\n", "commands"
    ) == {"cmd"}
    assert (
        loop_targets_of("for cmd in ([] if commands else ()):\n    pass\n", "commands")
        == set()
    )
    # codex round 8: `and` yields a non-final operand only when it is FALSY,
    # so an `and`-guarded container can never be iterated with anything in it.
    # `or` yields it when truthy, and the final operand is a result for both.
    assert (
        loop_targets_of("for cmd in commands and ():\n    pass\n", "commands") == set()
    )
    assert loop_targets_of("for cmd in () and commands:\n    pass\n", "commands") == {
        "cmd"
    }
    assert loop_targets_of("for cmd in () or commands:\n    pass\n", "commands") == {
        "cmd"
    }
    # codex round 10: a walrus evaluates to its value as well as binding it,
    # and its target is a Store that the Load-only alias walk never sees.
    assert loop_targets_of(
        "for cmd in (alias := commands):\n    pass\n", "commands"
    ) == {"cmd"}
    assert loop_targets_of(
        "for cmd in (alias := commands) or ():\n    pass\n", "commands"
    ) == {"cmd"}

    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fallback(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    for cmd in commands or ():\n"
            "        subprocess.run(cmd)\n"
            "def ternary(path, flag):\n"
            "    commands = [['ogrinfo', path]]\n"
            "    for cmd in commands if flag else []:\n"
            "        subprocess.run(cmd)\n"
            "def concatenated(path, extra):\n"
            "    commands = [['gdalwarp', path]]\n"
            "    for cmd in commands + extra:\n"
            "        subprocess.run(cmd)\n"
            "def starred(path):\n"
            "    commands = [['gdaladdo', path]]\n"
            "    for cmd in (*commands,):\n"
            "        subprocess.run(cmd)\n"
            "def condition_only(path):\n"
            "    commands = [['gdal_translate', path]]\n"
            "    for cmd in ([] if commands else ()):\n"
            "        subprocess.run(cmd)\n"
            "def and_guarded(path):\n"
            "    commands = [['nearblack', path]]\n"
            "    for cmd in commands and ():\n"
            "        subprocess.run(cmd)\n"
            "def walrus(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    for cmd in (alias := commands):\n"
            "        subprocess.run(cmd)\n"
            "def walrus_vector(path):\n"
            "    cmd = ['ogrinfo', path]\n"
            "    for part in (alias := cmd):\n"
            "        consume(part)\n"
        ),
        {},
    )
    assert total == 5, (total, violations)
    assert len(violations) == 5, violations
    assert any("(walrus)" in v for v in violations), violations
    for quiet in ("(condition_only)", "(and_guarded)", "(walrus_vector)"):
        assert not any(quiet in v for v in violations), (quiet, violations)


def test_guard_positional_unpacking_consumes_the_wrapper():
    """fix(#1394), codex round 11: unpacking takes the container apart.

    ``alias, = (["gdalinfo", path],)`` binds the vector itself, so
    ``for part in alias:`` yields strings and reporting it was a false positive
    on inert data. The kind for an unpacked target is the one from BELOW the
    wrapper the unpacking consumed, so the same shape one level deeper still
    hands over a container.

    The control in the middle: ``alias`` is the vector, so spawning it directly
    is still a site — the fix must not turn the unpacking into a dead end.

    codex round 12: patterns nest as freely as displays do, so the wrappers and
    the patterns are counted one for one. ``((alias,),) = ((argv,),)`` consumes
    two and lands where the single unpacking does, while ``(alias,) =
    ((argv,),)`` consumes one and leaves a container — the last two functions.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def unpacked(path):\n"
            "    alias, = (['gdalinfo', path],)\n"
            "    for part in alias:\n"
            "        consume(part)\n"
            "def spawned(path):\n"
            "    alias, = (['ogrinfo', path],)\n"
            "    subprocess.run(alias)\n"
            "def one_deeper(path):\n"
            "    alias, = ((['gdalwarp', path],),)\n"
            "    for cmd in alias:\n"
            "        subprocess.run(cmd)\n"
            "def nested_pattern(path):\n"
            "    ((alias,),) = ((['gdaladdo', path],),)\n"
            "    for part in alias:\n"
            "        consume(part)\n"
            "def nested_pattern_half(path):\n"
            "    (alias,) = ((['gdal_translate', path],),)\n"
            "    for cmd in alias:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert len(violations) == 3, violations
    for reported in ("(spawned)", "(one_deeper)", "(nested_pattern_half)"):
        assert any(reported in v for v in violations), (reported, violations)
    for quiet in ("(unpacked)", "(nested_pattern)"):
        assert not any(quiet in v for v in violations), (quiet, violations)


def test_guard_unpacking_pairs_only_with_real_levels():
    """fix(#1394), codex round 13: two ways the one-for-one count goes wrong.

    A wrapper that adds NO level is not a pattern's to consume, so it has to be
    stepped over rather than end the pairing: ``(alias,) = ((argv,) + ())``
    unpacks the concatenated tuple exactly as ``(alias,) = (argv,)`` does, and
    abandoning the match at the ``+`` left ``alias`` looking like a container.

    Chained targets can unpack to DIFFERENT depths, and a target whose pattern
    ends early was dropped the moment a sibling descended past it — so
    ``(alias,) = ((deep,),) = ((argv,),)`` lost ``alias`` entirely and the loop
    over it reported nothing.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def through_a_value_wrapper(path):\n"
            "    (alias,) = ((['gdalinfo', path],) + ())\n"
            "    for part in alias:\n"
            "        consume(part)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []

    uneven, total_uneven = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def uneven_chain(path):\n"
            "    (alias,) = ((deep,),) = ((['ogrinfo', path],),)\n"
            "    for cmd in alias:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total_uneven == 1, (total_uneven, uneven)
    assert len(uneven) == 1 and "(uneven_chain)" in uneven[0]

    # codex round 15: those two endpoints hold DIFFERENT things — `alias` a
    # container, `deep` the argv — so one kind for both names could only be
    # wrong about one of them. Iterating `deep` yields strings.
    per_endpoint, total_per_endpoint = _collect_gdal_cli_violations(
        _mod(
            "def uneven_chain(path):\n"
            "    (alias,) = ((deep,),) = ((['gdalinfo', path],),)\n"
            "    for part in deep:\n"
            "        consume(part)\n"
        ),
        {},
    )
    assert total_per_endpoint == 0, (total_per_endpoint, per_endpoint)
    assert per_endpoint == []


def test_guard_unpacking_a_named_container_consumes_its_kind():
    """fix(#1394), codex round 14: the same rule one alias hop away.

    ``alias, = commands`` takes ``commands`` apart exactly as
    ``alias, = (["gdalinfo", path],)`` takes the display apart, and leaves
    ``alias`` holding the vector. The AST shows no wrapper there — it lives in
    the followed kind — so the alias hop restored the container and the loop
    over ``alias`` reported strings as commands.

    A container the analysis knows only by KIND has no known position, and in a
    container of argvs every position is one. A MAPPING is different: unpacking
    it yields keys, which are not commands, so it keeps the conservative answer
    (the last function reports because ``holder`` still looks like a container,
    not because a key was mistaken for a command).
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def unpacked_alias(path):\n"
            "    commands = (['gdalinfo', path],)\n"
            "    alias, = commands\n"
            "    for part in alias:\n"
            "        consume(part)\n"
            "def unpacked_alias_spawned(path):\n"
            "    commands = (['ogrinfo', path],)\n"
            "    alias, = commands\n"
            "    subprocess.run(alias)\n"
            "def plain_alias(path):\n"
            "    commands = (['gdalwarp', path],)\n"
            "    alias = commands\n"
            "    for cmd in alias:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 2, violations
    for reported in ("(unpacked_alias_spawned)", "(plain_alias)"):
        assert any(reported in v for v in violations), (reported, violations)
    assert not any("(unpacked_alias)" in v for v in violations), violations


def test_guard_a_sliced_container_is_still_a_container():
    """fix(#1394), codex round 9: a slice yields a sequence of the same things.

    ``for cmd in commands[:]:`` iterates argvs, and the loop rule could not
    climb the subscript, so a real GDAL invocation went undetected — the silent
    direction. #996 already reads a slice this way in ``_escape_kind``, where
    only a SINGLE index stops the walk because it consumes a level.

    Fixed on the alias path too (``sliced = commands[:]``), since that is how
    round 8 got around the round-7 fix. The controls: an INDEX still yields the
    vector, and slicing the vector itself still yields strings.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def in_place(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    for cmd in commands[:]:\n"
            "        subprocess.run(cmd)\n"
            "def aliased(path):\n"
            "    commands = [['ogrinfo', path]]\n"
            "    sliced = commands[:]\n"
            "    for cmd in sliced:\n"
            "        subprocess.run(cmd)\n"
            "def indexed(path):\n"
            "    commands = [['gdalwarp', path]]\n"
            "    subprocess.run(commands[0])\n"
            "def vector_slice(path):\n"
            "    cmd = ['gdaladdo', path]\n"
            "    for part in cmd[:]:\n"
            "        consume(part)\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert len(violations) == 3, violations
    for reported in ("(in_place)", "(aliased)", "(indexed)"):
        assert any(reported in v for v in violations), (reported, violations)
    assert not any("(vector_slice)" in v for v in violations), violations


def test_guard_a_dead_wrapper_alias_is_not_followed_either():
    """fix(#1394), codex round 8: the same rule one alias hop away.

    ``empty = [] if commands else ()`` and ``nothing = commands and ()`` are
    always empty, so a later ``for cmd in empty:`` runs nothing. The wrapper
    rule lived only where the loop reads its iterable, and ``_binding_targets``
    climbed every value wrapper unconditionally, so the alias inherited the
    container kind and the loop rule reported an argv that cannot run. Both
    now stop at the wrapper, and the live spellings beside them still report.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def dead_condition(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    empty = [] if commands else ()\n"
            "    for cmd in empty:\n"
            "        subprocess.run(cmd)\n"
            "def dead_and(path):\n"
            "    commands = [['ogrinfo', path]]\n"
            "    nothing = commands and ()\n"
            "    for cmd in nothing:\n"
            "        subprocess.run(cmd)\n"
            "def live_result(path, flag):\n"
            "    commands = [['gdalwarp', path]]\n"
            "    chosen = commands if flag else ()\n"
            "    for cmd in chosen:\n"
            "        subprocess.run(cmd)\n"
            "def live_or(path):\n"
            "    commands = [['gdaladdo', path]]\n"
            "    chosen = commands or ()\n"
            "    for cmd in chosen:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 2, violations
    for live in ("(live_result)", "(live_or)"):
        assert any(live in v for v in violations), (live, violations)


def test_guard_conflicting_container_kinds_merge_to_the_louder():
    """fix(#1394), codex round 3: a path reached twice has ONE answer.

    ``x = commands`` beside ``x = {"label": commands}`` puts ``x`` on the
    worklist as both a sequence and a dict. Collapsing the pairs kept whichever
    the set happened to yield last, so the verdict moved with
    ``PYTHONHASHSEED``; they now merge to the kind that follows MORE, which
    keeps a conflict on the reported side.

    The merge rule is pinned directly, because the end-to-end shape below can
    only ever catch a regression on half the seeds — which is the flake this
    exists to prevent, not a gate.
    """
    assert _louder_kind(_ITER_YIELDS_VECTOR, None) == _ITER_YIELDS_VECTOR
    assert _louder_kind(None, _ITER_YIELDS_VECTOR) == _ITER_YIELDS_VECTOR
    assert _louder_kind(_ITER_YIELDS_VECTOR, _ITER_YIELDS_OTHER) == _ITER_YIELDS_VECTOR
    assert _louder_kind(_ITER_YIELDS_OTHER, _ITER_YIELDS_VECTOR) == _ITER_YIELDS_VECTOR
    assert _louder_kind(_ITER_YIELDS_OTHER, None) == _ITER_YIELDS_OTHER
    assert _louder_kind(None, None) is None

    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    x = commands\n"
            "    x = {'label': commands}\n"
            "    for cmd in x:\n"
            "        subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_container_kind_survives_an_alias_hop():
    """fix(#1394), codex round 1: the kind travels with the path.

    An alias of a container is the same container, so ``alias = commands`` then
    ``for x in alias:`` has to reach the SAME verdict as iterating ``commands``
    directly — reported for a list, inert for a dict. Carrying only "holds a
    container" across the hop loses that and reports both.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def sequence(path):\n"
            "    commands = [['gdalinfo', path]]\n"
            "    alias = commands\n"
            "    for cmd in alias:\n"
            "        subprocess.run(cmd)\n"
            "def mapping(path):\n"
            "    lookup = {'inspect': ['ogrinfo', path]}\n"
            "    other = lookup\n"
            "    for key in other:\n"
            "        consume(key)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(sequence)" in violations[0]


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


def test_guard_argv_assembled_by_augmented_assignment_is_detected():
    """fix(#996 review): `cmd = []` then `cmd += [...]` assembles a real argv,
    and the literal's parent is an AugAssign no binding branch matched."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    cmd = []\n"
            "    cmd += ['gdalinfo', path]\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_argv_behind_a_boolean_fallback_is_detected():
    """fix(#996 review): `fallback or [...]` is a value-producing wrapper like
    the ternary; the climb used to stop at the BoolOp."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path, fallback):\n"
            "    cmd = fallback or ['gdalinfo', path]\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_attribute_target_does_not_bind_its_container():
    """fix(#996 review): `settings.choices = [...]` binds nothing this analysis
    can follow. Reading `settings` as the binding made `render(settings)` look
    like the argv escaping — a false positive on data that never moves."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def fn(settings):\n"
            "    settings.choices = ['gdalinfo', '-json']\n"
            "    render(settings)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_subscript_target_does_not_bind_its_container_either():
    """The sibling shape: `registry['tools'] = [...]` then `render(registry)`."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def fn(registry):\n"
            "    registry['tools'] = ['gdalinfo', '-json']\n"
            "    render(registry)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_argv_stored_on_an_attribute_or_key_is_detected():
    """fix(#996 review): refusing to bind the container was right; binding
    NOTHING was not. `box.cmd = [...]` then `subprocess.run(box.cmd)` executes
    the literal, so the PATH is what gets tracked."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def via_attribute(box, path):\n"
            "    box.cmd = ['gdalinfo', path]\n"
            "    subprocess.run(box.cmd)\n"
            "def via_key(registry, path):\n"
            "    registry['cmd'] = ['ogrinfo', path]\n"
            "    subprocess.run(registry['cmd'])\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert any("(via_attribute)" in v for v in violations)
    assert any("(via_key)" in v for v in violations)


def test_guard_extracting_a_vector_from_a_container_keeps_the_chain():
    """fix(#996 review): `commands = {...}`, `cmd = commands["inspect"]`,
    `run(cmd)`. The alias chain used to stop at the container, because a
    subscript is not a transparent wrapper for a vector."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = {'inspect': ['gdalinfo', path]}\n"
            "    cmd = commands['inspect']\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_argv_as_a_default_parameter_is_detected():
    """fix(#996 review): a default executes on every bare call, but the literal
    sits in the signature — the escape walk stops at the function boundary, so
    the parameter NAME is the link."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def positional(cmd=('gdalinfo', '-json')):\n"
            "    subprocess.run(cmd)\n"
            "def keyword_only(*, cmd=['ogrinfo', '-so']):\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert any("(positional)" in v for v in violations)
    assert any("(keyword_only)" in v for v in violations)


def test_guard_rebinding_before_use_is_not_an_escape():
    """fix(#996 review): ordinary variable reuse must not fail the gate.
    `cmd = [gdal]; cmd = ['echo', 'ok']; run(cmd)` executes nothing GDAL."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn():\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    cmd = ['echo', 'ok']\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_rebinding_in_a_branch_still_reports():
    """The narrowness is deliberate: only a rebinding in the SAME statement
    list is ordered against the use. A rebinding under an `if` is not, so the
    literal still counts — the miss stays on the reported side, matching #974
    round 10's refusal to do statement-order analysis."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(flag):\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    if flag:\n"
            "        cmd = ['echo', 'ok']\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_annotated_path_target_is_tracked():
    """fix(#996 review): `box.cmd: list[str] = [...]` binds a path exactly like
    the unannotated form. The AnnAssign branch still required a bare Name."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(box, path):\n"
            "    box.cmd: list[str] = ['gdalinfo', path]\n"
            "    subprocess.run(box.cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comparison_result_is_not_the_vector():
    """fix(#996 review): a comparison yields a BOOLEAN. Passing that to a call
    hands over the result, not the argv — same family as the subscript rule."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "def fn(expected):\n"
            "    cmd = ['gdalinfo', '-json']\n"
            "    log.debug('matched=%s', cmd == expected)\n"
        ),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_comparison_does_not_hide_a_later_real_escape():
    """The control: comparing a vector must not exempt it from a genuine
    spawn elsewhere in the same scope."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path, expected):\n"
            "    cmd = ['gdalinfo', path]\n"
            "    if cmd == expected:\n"
            "        pass\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_value_wrapper_does_not_make_the_name_a_container():
    """fix(#996 review): a BinOp/IfExp/BoolOp evaluates TO the vector, so the
    name it is assigned to holds the vector, not a container of it. Sharing one
    `climbed` flag with the container wrappers made `cmd[0]` read as a
    container access yielding the argv, when only a string escapes."""
    violations, total = _collect_gdal_cli_violations(
        _mod("def fn():\n    cmd = ['gdalinfo', '-json'] + []\n    consume(cmd[0])\n"),
        {},
    )
    assert total == 0, (total, violations)
    assert violations == []


def test_guard_value_wrapper_still_escapes_when_the_vector_itself_is_passed():
    """The control: the distinction must not exempt the vector from a real
    spawn — only from an element access."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path, extra):\n"
            "    cmd = ['gdalinfo', path] + extra\n"
            "    subprocess.run(cmd)\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_container_wrapper_still_marks_the_name_a_container():
    """The other control: a real container wrapper must keep setting the flag,
    so `commands['inspect']` still yields the argv rather than an element."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path):\n"
            "    commands = {'inspect': ['gdalinfo', path]}\n"
            "    subprocess.run(commands['inspect'])\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_generator_expression_does_not_grant_safe_env_credit():
    """fix(#996 review): building `(gdal_safe_env() for _ in ())` executes
    nothing, so it must not credit the scope. This module lumped generator
    expressions in with the eager comprehensions and its own comment claimed
    only def and lambda defer — an unclamped argv beside one passed."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def fn(path):\n"
            "    deferred = (gdal_safe_env() for _ in ())\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "    return deferred\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_comprehension_body_no_longer_grants_safe_env_credit():
    """fix(#1077) changed this verdict on purpose. A comprehension body is
    eager only in the sense that it runs inside the enclosing statement —
    ``[gdal_safe_env() for _ in ()]`` still executes nothing, so "eager" was
    never the same claim as "runs". It is not a shape the position allowlist
    names, so the argv beside it now reports. Nothing in ``app/`` builds its
    env this way; the price of the stricter answer is a false alarm somebody
    investigates, which is the direction this gate chooses."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def fn(path):\n"
            "    envs = [gdal_safe_env() for _ in range(1)]\n"
            "    subprocess.run(['gdalinfo', path], env=envs[0])\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_generator_expression_outermost_iterable_is_still_eager():
    """The other half: a genexp's FIRST iterable is evaluated at construction,
    so a helper call there is real and does credit the scope."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def fn(path):\n"
            "    lazy = (x for x in [gdal_safe_env()])\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "    return lazy\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert violations == []


def test_guard_comprehension_walrus_argv_is_detected():
    """fix(#996 review): the walrus binds in the CONTAINING scope, so
    recording it in the comprehension too made its own load read as a nested
    shadow and the argv vanished."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "def fn(path, items):\n"
            "    return [subprocess.run(cmd) for _ in items "
            "if (cmd := ['gdalinfo', path])]\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


# ---------------------------------------------------------------------------
# fix(#1077): credit is an ALLOWLIST of positions, not a walk that credits any
# call it sees. The three shapes below all execute eagerly WHEN REACHED, so
# #996's deferred-body rule never touched them; they credited silently until
# the inversion. Each pairs the conditional form with the unconditional
# control, because a gate that reports both is not the same gate.
# ---------------------------------------------------------------------------


def test_guard_call_under_a_branch_does_not_credit():
    """``if False: gdal_safe_env()`` is a call the scan SEES and the process
    never RUNS. The sibling with the same call in the straight-line body keeps
    its credit."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def branched(path):\n"
            "    if False:\n"
            "        env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def straight(path):\n"
            "    env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path], env=env)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 1, violations
    assert "(branched)" in violations[0]


def test_guard_untaken_ternary_arm_does_not_credit():
    """An arm of a conditional expression is chosen at runtime, so a helper
    call in one of them proves nothing about the argv beside it."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def ternary(path, flag):\n"
            "    env = gdal_safe_env() if flag else None\n"
            "    subprocess.run(['gdalinfo', path], env=env)\n"
            "def unconditional(path):\n"
            "    subprocess.run(['gdalinfo', path], env=gdal_safe_env())\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 1, violations
    assert "(ternary)" in violations[0]


def test_guard_unreached_match_case_does_not_credit():
    """A ``match`` case body runs only for its own subject — the same
    conditionality as ``if``, in a construct the old walk did not distinguish
    from straight-line code."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def matched(path, mode):\n"
            "    match mode:\n"
            "        case 'safe':\n"
            "            env = gdal_safe_env()\n"
            "        case _:\n"
            "            env = {}\n"
            "    subprocess.run(['gdalinfo', path], env=env)\n"
            "def unconditional(path):\n"
            "    env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path], env=env)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 1, violations
    assert "(matched)" in violations[0]


def test_guard_loop_and_handler_bodies_do_not_credit_outside_themselves():
    """The same rule, applied to the other constructs that may not run: a
    ``for`` body over an empty iterable, and an ``except`` handler that fires
    only on failure. An argv INSIDE the loop is in the same branch as the
    call, so it keeps its credit — the allowlist is about the relationship
    between the two, not about banning loops."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def looped(path, items):\n"
            "    for _ in items:\n"
            "        env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def handled(path):\n"
            "    try:\n"
            "        pass\n"
            "    except OSError:\n"
            "        env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def inside_the_loop(paths):\n"
            "    for path in paths:\n"
            "        env = gdal_safe_env()\n"
            "        subprocess.run(['gdalinfo', path], env=env)\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert len(violations) == 2, violations
    assert any("(looped)" in v for v in violations)
    assert any("(handled)" in v for v in violations)


def test_guard_finally_env_does_not_credit_the_try_body():
    """A ``finally`` runs whenever the ``try`` is entered, so it is eager in
    the ordinary sense and still cannot clamp anything in the body: it runs
    after it. The control is a ``finally`` that builds its own argv beside its
    own env, which the same-branch rule keeps crediting."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def too_late(path):\n"
            "    try:\n"
            "        subprocess.run(['gdalinfo', path])\n"
            "    finally:\n"
            "        env = gdal_safe_env()\n"
            "        print(env)\n"
            "def cleans_up(path):\n"
            "    try:\n"
            "        pass\n"
            "    finally:\n"
            "        env = gdal_safe_env()\n"
            "        subprocess.run(['gdalinfo', path], env=env)\n"
        ),
        {},
    )
    assert total == 2, (total, violations)
    assert len(violations) == 1, violations
    assert "(too_late)" in violations[0]


def test_guard_nested_generator_iterable_no_longer_credits():
    """fix(#1077) also closes the recursion hole #996 left in the eager half
    of the deferral rule: a genexp's outermost iterable is eager, but when
    that iterable is ITSELF a generator expression nothing runs. The hand
    rolled scan re-entered and credited; positions compose, so this one
    reports without a rule of its own."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def fn(path):\n"
            "    lazy = (x for x in (gdal_safe_env() for _ in ()))\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "    return lazy\n"
        ),
        {},
    )
    assert total == 1, (total, violations)
    assert len(violations) == 1 and "(fn)" in violations[0]


def test_guard_env_that_goes_nowhere_does_not_credit():
    """``gdal_safe_env`` returns the clamped env and mutates nothing, so a
    call whose result is dropped clamps nothing — a call that RUNS and still
    means nothing, the mirror of the conditional cases. All three spellings of
    dropping it are covered together, since fixing one and leaving its
    siblings is how this gate spent rounds on #974."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "import subprocess\n"
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "def dead_store(path):\n"
            "    env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def annotated_dead_store(path):\n"
            "    env: dict = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def discarded(path):\n"
            "    gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path])\n"
            "def read_and_passed(path):\n"
            "    env = gdal_safe_env()\n"
            "    subprocess.run(['gdalinfo', path], env=env)\n"
        ),
        {},
    )
    assert total == 4, (total, violations)
    assert len(violations) == 3, violations
    assert any("(dead_store)" in v for v in violations)
    assert any("(annotated_dead_store)" in v for v in violations)
    assert any("(discarded)" in v for v in violations)


def test_guard_real_tree_credit_shapes_are_all_allowlisted():
    """The practicality check, pinned as a test rather than left to the
    measurement in #1077's PR body: the exact shapes the credited argv sites in
    ``app/`` use. ``prepare_with_overviews`` assigns the env inside a ``try``;
    ``convert_to_cog`` builds its argv across conditional ``extend`` calls and
    passes an env variable (fix(#1291) removed its second, gdalwarp site, whose
    shape was an env passed inline from inside an ``if``); ``_build_vrt``
    builds the argv in the straight-line body and passes the env inline from
    inside a ``try``. Narrowing the allowlist until any of these reports means
    breaking the tree, and this is where that shows up."""
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env, run_gdal\n"
            "def prepare(path, tmp_path):\n"
            "    try:\n"
            "        env = gdal_safe_env(extras={'GDAL_CACHEMAX': '200'})\n"
            "        cmd = ['gdaladdo', '-r', 'average', tmp_path]\n"
            "        return run_gdal(cmd, env=env, tool='gdaladdo')\n"
            "    except Exception:\n"
            "        raise\n"
            "def convert(path, out, assign_crs, nodata):\n"
            "    try:\n"
            "        env = gdal_safe_env(extras={'GDAL_CACHEMAX': '200'})\n"
            "        cmd = ['gdal_translate', '-of', 'GTiff']\n"
            "        if nodata is not None:\n"
            "            cmd.extend(['-a_nodata', str(nodata)])\n"
            "        if assign_crs is not None:\n"
            "            cmd.extend(['-a_srs', f'EPSG:{assign_crs}'])\n"
            "        cmd.extend([path, out])\n"
            "        return run_gdal(cmd, env=env, tool='gdal_translate')\n"
            "    finally:\n"
            "        pass\n"
            "def build_vrt(sources, out):\n"
            "    cmd = ['gdalbuildvrt', out, *sources]\n"
            "    try:\n"
            "        return run_gdal(cmd, env=gdal_safe_env(), tool='gdalbuildvrt')\n"
            "    except FileNotFoundError:\n"
            "        return None\n"
        ),
        {},
    )
    assert total == 3, (total, violations)
    assert violations == []


def test_guard_staged_upload_credited_by_the_raster_helper_reports():
    """fix(#1846 codex P2, thread 3939092275): the clamps may not cross.

    A staged-upload argv wired to `gdal_safe_env` has the RASTER clamps and no
    vector driver skip anywhere near it, so the drivers that read a document as
    instructions are all still registered. It used to pass this gate, because
    credit accepted any member of the safe-env family.
    """
    violations, total = _collect_vector_driver_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_safe_env\n"
            "from app.processing.ingest.gdal_drivers import local_input_driver_args\n"
            "from app.processing.ingest.validation import validate_content_directives\n"
            "import asyncio\n"
            "async def run_ogrinfo(file_path):\n"
            "    validate_content_directives(file_path)\n"
            "    driver_args = local_input_driver_args(file_path)\n"
            "    env = gdal_safe_env()\n"
            "    cmd = ['ogrinfo', '-so', *driver_args, file_path]\n"
            "    return await asyncio.create_subprocess_exec(*cmd, env=env)\n"
        ),
        {
            ("seed/mod.py", "run_ogrinfo", "ogrinfo"): (
                1,
                STAGED_UPLOAD,
                SAFE_VECTOR_ENV_HELPER,
                "synthetic staged-upload site for this counterfactual",
            )
        },
    )
    assert total == 1
    assert len(violations) == 1, violations
    assert SAFE_VECTOR_ENV_HELPER in violations[0], violations
    # And it names what is missing rather than the helper that was found.
    assert "no gdal_vector_safe_env call covering it" in violations[0], violations


def test_guard_raster_argv_credited_by_the_vector_helper_reports():
    """The same crossing in the other direction, under the older gate.

    `gdal_vector_safe_env` sets GDAL_SKIP and nothing else, so a raster argv
    credited by it runs without CPL_VSIL_CURL_ALLOWED_EXTENSIONS or
    VRT_VIRTUAL_OVERVIEWS -- the two clamps that gate the /vsicurl surface a
    raster VRT build can reach.
    """
    violations, total = _collect_gdal_cli_violations(
        _mod(
            "from app.processing.raster.vrt import gdal_vector_safe_env, run_gdal\n"
            "def build_vrt(sources, out):\n"
            "    env = gdal_vector_safe_env()\n"
            "    cmd = ['gdalbuildvrt', out, *sources]\n"
            "    return run_gdal(cmd, env=env, tool='gdalbuildvrt')\n"
        ),
        {},
    )
    assert total == 1
    assert len(violations) == 1, violations
    assert SAFE_SUBPROCESS_ENV_HELPER in violations[0], violations
    assert SAFE_VECTOR_ENV_HELPER not in violations[0], violations
