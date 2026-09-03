"""One producer of a credential header, enforced structurally (fix(#1746)).

In the shape of ``test_rule2_structural.py``: walk every module under
``backend/app/`` as an AST and assert that the transports which carry a
credential get their header from ``build_credential_header`` and
``credential_header_line`` in ``app/core/service_tokens.py`` rather than
composing one of their own.

Why a structural test rather than a code comment. The prefix is composed today
in four separate places on the service-credential path, and handing any of them
a finished line without removing its own composition produces
``Authorization: Bearer Authorization: Basic <blob>``, a working-looking string
that fails at the origin with a 401 and reads in a log like a credential
problem rather than a bug. Once the four are collapsed into the builder,
nothing except this test stops a fifth appearing beside them.

The two sinks it watches, over the whole ``backend/app/`` tree:

1. **The header FILE.** Any write in a scope that calls ``gdal_header_dir()``.
   That directory exists for exactly one thing, the 0600
   ``GDAL_HTTP_HEADER_FILE``, so a write in a scope that located it is a
   credential line by construction.
2. **A header MAPPING.** A subscript assignment or a dict literal key. Which
   ones are judged:

   - Tree-wide, any key naming one of the three credential headers
     (``authorization``, ``proxy-authorization``, ``x-esri-authorization``),
     case-insensitively, whatever the mapping is called and wherever it goes.
     That rule has no preconditions, which is why it is the one that catches a
     composition in a module nobody thought about.
   - On the two credential paths (``modules/catalog/sources/`` and
     ``processing/``), EVERY key of a mapping that reaches an outbound HTTP
     request, minus a short list of headers that cannot carry a credential.
     That covers the header-key method, whose whole point is a custom name:
     ``X-API-Key``, Ordnance Survey's literal ``key``, Azure's
     ``Ocp-Apim-Subscription-Key``. A computed key there is judged too, since
     ``key = "Authorization"`` two lines above would otherwise walk through.

   "Reaches an outbound request" means the dict literal, or the name it is
   bound to, is passed as a ``headers=`` argument to a request call (``get``,
   ``post``, ``stream``, ``request`` and the rest). That binding is the whole
   test for whether a mapping is in scope; the mapping's own name is not
   consulted, so ``request_options`` is watched exactly as closely as
   ``headers`` (fix(#1756 codex round 4)). It is also what separates a
   credential from response-header plumbing: everything under
   ``processing/export/`` and ``processing/tiles/`` passes ``headers=`` to
   ``Response``, ``StreamingResponse`` or ``HTTPException``, and none of it
   leaves the process.

   fix(#1756 codex round 1): the mapping rule used to be scoped to
   ``sources/adapters/``, which missed the composition in ``sources/router.py``
   entirely. fix(#1756 codex round 3): and it read only the three credential
   names, so a hand-composed ``X-API-Key`` bypassed it.

**Provenance is a whole-expression rule, and it depends on the sink.**
fix(#1756 codex round 2): it used to ask whether the written expression
MENTIONED builder output anywhere, which passed
``f"Authorization: Bearer {line}"`` for a builder-derived ``line``.
fix(#1756 codex round 3): and it accepted a joined line in mapping position,
which puts ``Authorization: Authorization: Basic ...`` on the wire.

Every expression is classified as one of four kinds, or as nothing, and a
classified expression also carries the identity of the builder call it came
from:

- PAIR: a resolved ``build_credential_header(...)`` call, or a name bound to a
  PAIR.
- LINE: ``credential_header_line(<PAIR>)``; ``<LINE> + "\\n"``; an f-string
  whose single interpolation is a LINE, with no conversion, no format spec and
  no literal part but a trailing newline; ``.encode()`` or ``.encode("ascii")``
  on a LINE; or a name bound to a LINE.
- NAME and VALUE: the two components of a PAIR, reached by ``<PAIR>[0]`` and
  ``<PAIR>[1]`` or by unpacking ``name, value = build_credential_header(...)``.

The file sink accepts a LINE and nothing else, so a PAIR or a bare component
written to the header file fails. The mapping sink accepts a VALUE for the
value and a NAME for the key, from the SAME builder call: a PAIR written whole
fails, a LINE fails, a string-literal key fails (fix(#1756 codex round 4)), and
so does a key and value taken from two different results
(fix(#1756 codex round 5)). ``headers[first[0]] = second[1]`` sends one call's
credential under another call's name, which is the same mismatch a literal key
produces, so a clean mapping write is spelled ``headers[pair[0]] = pair[1]`` or
``headers[name] = value``.

Provenance also requires the call to BE the shared helper (fix(#1756 codex
round 5)). A bare name counts only when the module imports it from
``app.core.service_tokens`` and nothing shadows it at the call site; an
attribute call counts only when its base names that module AND that base is
itself unshadowed (fix(#1756 codex round 6)), so an alias rebound by a
parameter or an assignment buys nothing. A local
``def build_credential_header`` and an ``other.build_credential_header(...)``
therefore confer nothing either, which matters because the whole point of the
rule is that one function validates the inputs. A plain ``import a.b.c`` binds
the package ``a`` as a namespace and cannot point it at another value, so it is
not read as a shadow; ``import x as a`` and ``from x import a`` are.

A name resolves to its latest binding BEFORE the use site, so a later
``line = anything_else`` revokes it, and a parameter, loop target, ``with``
target or import carries no provenance at all.

Both allowlists are asserted EXACT in both directions and by count, so an
entry whose site disappears fails loudly instead of going stale. Four of the
six entries were the hand-rolled compositions lane B2b deleted, and this test
is what told it when each one was gone. The two that remain are named
individually: an OAuth access token the builder cannot produce by design, and
the one write whose value crosses a process boundary before it arrives.

**Known limits, which are deliberate and are not defects.** This gate is one
layer beside the runtime validation inside ``build_credential_header`` itself,
and that function is the actual enforcement: it validates the inputs, encodes
Basic server side, and refuses a header for any format outside
``HEADER_AUTH_SERVICE_FORMATS``. What this test adds is that no SECOND composer
appears beside it. It is a lexical AST rule, so:

- Provenance is intra-function. A pair or line returned by a helper, or
  arriving as a parameter, has no lexical provenance and is REPORTED, not
  trusted. That is the safe direction and it is why B2b composes at the write
  site rather than passing a finished line around.
- Only two containers are modelled: a dict literal and a subscript assignment.
  A credential put into a request through ``dict(Authorization=...)``,
  ``headers.setdefault(...)``, a list of pairs, or a mapping built by a
  comprehension is not seen by the mapping rule at all. A dict literal inside
  ``headers.update({...})`` IS seen, because it is still a dict literal. This
  is a silent gap rather than a loud one, and closing it needs container
  modelling this rule does not have.
- A mapping is identified by the tail name it is reached through, so
  ``headers`` and ``self.headers`` are one key and the write meets the request
  argument (fix(#1756 codex round 7)). Two things stay unmodelled after that:
  a mapping aliased through a second attribute or a longer chain
  (``self.session.headers`` written to and ``client.session.headers`` passed,
  or two different objects whose attribute happens to share a tail) is matched
  on the tail alone and so is neither reliably joined nor reliably separated,
  and a mapping that only ever exists as a call result
  (``client.get(url, headers=self._auth_headers())``) has no name to key on and
  is invisible.
- Dynamic dispatch is not modelled. ``getattr(module, "build_credential_header")``,
  a callable pulled from a registry, and a mapping reached through a computed
  attribute chain all resolve to nothing, so a call site built that way is
  reported rather than trusted, and a container reached that way is invisible.
- Binding order is read from source position. A binding made under one branch
  of an ``if`` and used under the other is judged as though the file ran top to
  bottom.

The tree-wide credential-name rule has none of those preconditions, so the
three names that matter most stay covered whatever the surrounding shape.
False alarms are cheap and visible; a silent miss is the failure that matters,
so anything the resolver cannot classify is reported.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The module that owns the policy, and the two functions this gate trusts.
POLICY_MODULE = "app.core.service_tokens"
POLICY_PACKAGE = "app.core"
POLICY_MODULE_TAIL = "service_tokens"
CREDENTIAL_BUILDER = "build_credential_header"
CREDENTIAL_JOINER = "credential_header_line"

# The helper that locates the 0600 header-file directory. A scope that calls
# it is writing a credential header or nothing at all.
HEADER_DIR_HELPER = "gdal_header_dir"

# The two trees that handle a service credential, where every outbound header
# key is judged rather than only the three credential names.
CREDENTIAL_PACKAGES = ("modules/catalog/sources/", "processing/")

# Write calls, by exact name. Substring matching would sweep in unrelated
# helpers: `_tenant_writer_subprocess_env` contains "write".
WRITE_CALL_NAMES = frozenset({"write", "writelines", "write_text", "write_bytes"})

# Calls that SEND a request. A header mapping handed to one of these leaves
# the process; one handed to Response/StreamingResponse/HTTPException does
# not, and cannot carry a credential to a third party.
#
# fix(#1770 round 41 P1): `bounded_probe_read` (`platform/probe_bounds.py`)
# joins the list. It is the probe adapters' own thin wrapper around
# `client.stream` -- the walk is scope-local and does not trace into a
# callee's body, so without this entry a header mapping handed to it (as
# `wfs.py`/`ogcapi.py` now do) reads as though it never left the scope that
# built it, and every credential-header site in those two files silently
# dropped out of the count this rule exists to keep honest.
OUTBOUND_REQUEST_CALLS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "request",
        "stream",
        "send",
        "build_request",
        "bounded_probe_read",
    }
)

# Header names that carry a credential, compared case-insensitively because
# HTTP field names are case-insensitive. Judged everywhere in the tree.
CREDENTIAL_HEADER_KEYS = frozenset(
    {"authorization", "proxy-authorization", "x-esri-authorization"}
)

# Request headers that cannot carry a credential, so they are exempt from the
# every-key rule on the credential paths. Deliberately short and explicit: a
# long list would turn the rule back into the three-name one by attrition.
NON_CREDENTIAL_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "cache-control",
        "content-length",
        "content-type",
        "if-modified-since",
        "if-none-match",
        "range",
        "user-agent",
        "x-request-id",
    }
)

# Every allowlist entry is (module, scope) -> (exact count, justification).
HEADER_FILE_WRITE_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/ingest/ogr.py", "run_ogr2ogr_service"): (
        1,
        "composes nothing: under plan D9 the finished header line crosses the "
        "queue as the `token` task argument, so it arrives in this scope as a "
        "PARAMETER and has no lexical provenance for this rule to read. What "
        "guards it instead is `_sanitize_authorization_token` in the same "
        "module, which judges the LINE (printable ASCII, no CR or LF, one "
        "`: ` separator, an RFC 7230 field name, and the base64url charset on "
        "the bearer branch) before the write. This is the one hop that cannot "
        "compose at the write site, which is why the queue is the only place "
        "a finished line travels. fix(#1746 B2b r3): that validator also "
        "composes the line for a PRE-#1770 queued job, whose kwarg still holds "
        "a bare bearer token, and it does so through `build_credential_header` "
        "in `_legacy_bearer_line` rather than by a prefix of its own, so this "
        "module still produces no credential header itself",
    ),
}

CREDENTIAL_HEADER_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("modules/auth/oauth/service.py", "_resolve_github_identity"): (
        1,
        "not a service credential and not B2b's to move: this is the OAuth "
        "access token for the provider's own userinfo call, and the builder "
        "cannot produce it by design, since it composes a header only for the "
        "formats in HEADER_AUTH_SERVICE_FORMATS. Listed so the rule can stay "
        "tree-wide and catch the next hand-composed Authorization header",
    ),
}

# Positive controls. A walker that silently matched nothing would satisfy
# every allowlist assertion in this module, which is the failure mode the
# absence-claim rule exists for.
MIN_APP_MODULES = 100
MIN_HEADER_FILE_WRITE_SITES = 2
MIN_CREDENTIAL_HEADER_SITES = 4

_MODULE_SCOPE = "<module>"
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# Before every statement in a scope, so a parameter never resolves to a
# binding made later in the body.
_SCOPE_START = (-1, -1)

# The four kinds an expression can carry. See the module docstring.
_PAIR = "pair"
_LINE = "line"
_NAME = "name"
_VALUE = "value"
_COMPONENT_KINDS = {0: _NAME, 1: _VALUE}


class _Kind(NamedTuple):
    """What an expression is, and which builder call it came from.

    ``result`` is the id of the originating ``build_credential_header`` call
    node. The mapping sink compares it across the key and the value, so a key
    from one call and a value from another cannot be paired
    (fix(#1756 codex round 5)).
    """

    kind: str
    result: int


def _app_modules() -> list[tuple[str, ast.Module]]:
    modules = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        modules.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _annotate_parents(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._credential_parent = node  # type: ignore[attr-defined]


def _enclosing_scope(node: ast.AST, tree: ast.Module) -> ast.AST:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = getattr(current, "_credential_parent", None)
    return tree


def _scope_name(scope: ast.AST) -> str:
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return scope.name
    return _MODULE_SCOPE


def _call_name(func: ast.expr) -> str | None:
    """Dotted-tail name of a call target: ``a.b.c(...)`` -> ``c``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _dotted_path(expr: ast.expr) -> str | None:
    """``app.core.service_tokens`` for an attribute chain of plain names."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted_path(expr.value)
        return None if base is None else f"{base}.{expr.attr}"
    return None


def _scope_calls(scope: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == name
        for node in ast.walk(scope)
    )


def _pos(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _is_header_keyword(keyword: ast.keyword) -> bool:
    return bool(keyword.arg) and "header" in keyword.arg.lower()


def _iter_scope_nodes(scope: ast.AST):
    """Every node in *scope*, without descending into a nested callable."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED_SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))


class _Imports(NamedTuple):
    """How this module reaches the policy functions, if it does at all.

    fix(#1756 codex round 5): trusting any callable whose attribute tail spells
    ``build_credential_header`` lets a local helper of the same name defeat the
    gate, which matters because the point of the rule is that ONE function
    validates the inputs.
    """

    builder_names: frozenset[str]
    joiner_names: frozenset[str]
    module_paths: frozenset[str]
    # Import statements that bound one of the above, so the shadow check does
    # not read the import itself as a rebinding.
    policy_imports: frozenset[int]


def _policy_import_names(node: ast.AST) -> dict[str, str] | None:
    """What a policy import binds locally: local name -> what it points at.

    The value is the function name, or ``POLICY_MODULE_TAIL`` for the module.
    """
    if isinstance(node, ast.ImportFrom):
        if node.module == POLICY_MODULE and not node.level:
            return {
                alias.asname or alias.name: alias.name
                for alias in node.names
                if alias.name in (CREDENTIAL_BUILDER, CREDENTIAL_JOINER)
            } or None
        if node.module == POLICY_PACKAGE and not node.level:
            return {
                alias.asname or alias.name: POLICY_MODULE_TAIL
                for alias in node.names
                if alias.name == POLICY_MODULE_TAIL
            } or None
        return None
    if isinstance(node, ast.Import):
        bound = {}
        for alias in node.names:
            if alias.name != POLICY_MODULE:
                continue
            # `import a.b.c` binds `a`; `import a.b.c as x` binds `x`.
            bound[alias.asname or POLICY_MODULE] = POLICY_MODULE_TAIL
        return bound or None
    return None


def _module_imports(tree: ast.Module) -> _Imports:
    builders: set[str] = set()
    joiners: set[str] = set()
    modules: set[str] = set()
    statements: set[int] = set()
    for node in ast.walk(tree):
        bound = _policy_import_names(node)
        if bound is None:
            continue
        statements.add(id(node))
        for local, target in bound.items():
            if target == CREDENTIAL_BUILDER:
                builders.add(local)
            elif target == CREDENTIAL_JOINER:
                joiners.add(local)
            else:
                modules.add(local)
    return _Imports(
        frozenset(builders),
        frozenset(joiners),
        frozenset(modules),
        frozenset(statements),
    )


class _Outbound(NamedTuple):
    """The header mappings in one scope that reach a request call."""

    names: frozenset[str]
    dicts: frozenset[int]


def _outbound_header_mappings(scope: ast.AST) -> _Outbound:
    """Header mappings handed to an outbound request call in *scope*.

    This binding, and not what the mapping is called, is what puts a mapping
    in scope for the every-key rule (fix(#1756 codex round 4)).
    """
    names: set[str] = set()
    dicts: set[int] = set()
    for node in _iter_scope_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) not in OUTBOUND_REQUEST_CALLS:
            continue
        for keyword in node.keywords:
            if not _is_header_keyword(keyword):
                continue
            if isinstance(keyword.value, ast.Dict):
                dicts.add(id(keyword.value))
                continue
            # fix(#1756 codex round 7): an attribute reaches the request the
            # same way a plain name does, and it is reduced by the same
            # function the write target is reduced by, so
            # `self.request_options[...] = ...` and
            # `headers=self.request_options` meet on one key.
            reference = _mapping_reference(keyword.value)
            if reference is not None:
                names.add(reference)

    # The literal a request-bound mapping was built from is the same mapping.
    for node in _iter_scope_nodes(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if _mapping_reference(target) in names:
                dicts.add(id(node.value))
    return _Outbound(frozenset(names), frozenset(dicts))


class _Binding(NamedTuple):
    """One binding of a name inside a scope.

    ``value`` is None when the binding is something this rule cannot judge: a
    parameter, a loop target, an import. Such a binding is RECORDED rather
    than skipped, because it has to revoke an earlier builder binding.
    ``index`` is the position within a tuple target, so
    ``name, value = build_credential_header(auth)`` gives each name the right
    component kind.
    """

    pos: tuple[int, int]
    value: ast.expr | None
    index: int | None = None


def _scope_arguments(scope: ast.AST) -> list[str]:
    args = getattr(scope, "args", None)
    if not isinstance(args, ast.arguments):
        return []
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    if args.vararg is not None:
        every.append(args.vararg)
    if args.kwarg is not None:
        every.append(args.kwarg)
    return [argument.arg for argument in every]


def _assignment_binding(
    node: ast.AST,
) -> tuple[list[ast.expr], ast.expr | None] | None:
    """Targets and bound value for a node that binds by assignment.

    A None value means the binding is real but unjudgeable, which is what
    makes a loop target or an augmented assignment revoke an earlier one.
    """
    if isinstance(node, ast.Assign):
        return node.targets, node.value
    if isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
        return [node.target], node.value
    if isinstance(node, ast.AugAssign):
        return [node.target], None
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return [node.target], None
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [node.optional_vars], None
    return None


def _opaque_names(node: ast.AST, imports: _Imports) -> list[str]:
    """Names *node* binds to something this rule cannot judge.

    A policy import is not one of them: it is how the trusted names arrive, so
    recording it would read as a shadow of itself.
    """
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if id(node) in imports.policy_imports:
            return []
        names = []
        for alias in node.names:
            if alias.asname:
                names.append(alias.asname)
            elif isinstance(node, ast.Import) and "." in alias.name:
                # `import a.b.c` binds the package `a` as a namespace. It
                # cannot point `a` at another value, so it is not a shadow of
                # a fully qualified policy call (fix(#1756 codex round 6));
                # `import x as a` and `from x import a` still are.
                continue
            else:
                names.append(alias.name)
        return names
    if isinstance(node, _NESTED_SCOPES) and not isinstance(node, ast.Lambda):
        return [node.name]
    return []


def _scope_bindings(scope: ast.AST, imports: _Imports) -> dict[str, list[_Binding]]:
    """Every name binding in *scope*, ordered by source position."""
    bindings: dict[str, list[_Binding]] = defaultdict(list)

    def record(
        target: ast.expr, value: ast.expr | None, index: int | None = None
    ) -> None:
        if isinstance(target, ast.Name):
            bindings[target.id].append(_Binding(_pos(target), value, index))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for position, element in enumerate(target.elts):
                record(element, value, position)
        elif isinstance(target, ast.Starred):
            record(target.value, None)

    for argument in _scope_arguments(scope):
        bindings[argument].append(_Binding(_SCOPE_START, None))

    for node in _iter_scope_nodes(scope):
        assignment = _assignment_binding(node)
        if assignment is not None:
            targets, value = assignment
            for target in targets:
                record(target, value)
        for name in _opaque_names(node, imports):
            bindings[name].append(_Binding(_pos(node), None))

    for name in bindings:
        bindings[name].sort(key=lambda binding: binding.pos)
    return dict(bindings)


def _binding_before(
    bindings: dict[str, list[_Binding]], name: str, limit: tuple[int, int]
) -> _Binding | None:
    """The latest binding of *name* that precedes *limit*."""
    latest: _Binding | None = None
    for binding in bindings.get(name, ()):
        if binding.pos < limit:
            latest = binding
    return latest


class _Context(NamedTuple):
    """Everything expression classification needs about where it stands."""

    bindings: dict[str, list[_Binding]]
    module_bindings: dict[str, list[_Binding]]
    imports: _Imports


def _is_shadowed(name: str, ctx: _Context, limit: tuple[int, int]) -> bool:
    """Whether *name* is bound to anything other than the policy import."""
    if _binding_before(ctx.bindings, name, limit) is not None:
        return True
    return bool(ctx.module_bindings.get(name))


def _resolves_to_policy(
    func: ast.expr, target: str, ctx: _Context, limit: tuple[int, int]
) -> bool:
    """Whether this call target IS the shared helper, not one that looks like it."""
    if isinstance(func, ast.Name):
        allowed = (
            ctx.imports.builder_names
            if target == CREDENTIAL_BUILDER
            else ctx.imports.joiner_names
        )
        return func.id in allowed and not _is_shadowed(func.id, ctx, limit)
    if isinstance(func, ast.Attribute):
        if func.attr != target:
            return False
        base = _dotted_path(func.value)
        if base is None:
            return False
        # `import app.core.service_tokens` binds the root package, so the call
        # is spelled out in full.
        known = base in ctx.imports.module_paths or (
            base == POLICY_MODULE and POLICY_MODULE in ctx.imports.module_paths
        )
        if not known:
            return False
        # fix(#1756 codex round 6): the base needs the same shadow check the
        # bare name gets. `from app.core import service_tokens as policy` plus
        # a parameter called `policy` would otherwise make anything that
        # object returns authoritative.
        return not _is_shadowed(base.split(".")[0], ctx, limit)
    return False


def _is_newline_literal(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value == "\n"


def _line_from(inner: _Kind | None) -> _Kind | None:
    return (
        _Kind(_LINE, inner.result)
        if inner is not None and inner.kind == _LINE
        else None
    )


def _encode_kind(expr: ast.Call, ctx: _Context, limit: tuple[int, int]) -> _Kind | None:
    if not isinstance(expr.func, ast.Attribute) or expr.keywords:
        return None
    if len(expr.args) > 1:
        return None
    if expr.args and not (
        isinstance(expr.args[0], ast.Constant) and expr.args[0].value == "ascii"
    ):
        return None
    return _line_from(_expr_kind(expr.func.value, ctx, limit))


def _call_kind(expr: ast.Call, ctx: _Context, limit: tuple[int, int]) -> _Kind | None:
    if _resolves_to_policy(expr.func, CREDENTIAL_BUILDER, ctx, limit):
        return _Kind(_PAIR, id(expr))
    if _resolves_to_policy(expr.func, CREDENTIAL_JOINER, ctx, limit):
        if len(expr.args) != 1 or expr.keywords:
            return None
        argument = _expr_kind(expr.args[0], ctx, limit)
        if argument is None or argument.kind != _PAIR:
            return None
        return _Kind(_LINE, argument.result)
    if _call_name(expr.func) == "encode":
        return _encode_kind(expr, ctx, limit)
    return None


def _name_kind(expr: ast.Name, ctx: _Context, limit: tuple[int, int]) -> _Kind | None:
    binding = _binding_before(ctx.bindings, expr.id, limit)
    if binding is None or binding.value is None:
        return None
    bound = _expr_kind(binding.value, ctx, binding.pos)
    if bound is None:
        return None
    if binding.index is None:
        return bound
    if bound.kind != _PAIR or binding.index not in _COMPONENT_KINDS:
        return None
    return _Kind(_COMPONENT_KINDS[binding.index], bound.result)


def _component_kind(
    expr: ast.Subscript, ctx: _Context, limit: tuple[int, int]
) -> _Kind | None:
    index = expr.slice
    if not isinstance(index, ast.Constant) or isinstance(index.value, bool):
        return None
    if index.value not in _COMPONENT_KINDS:
        return None
    base = _expr_kind(expr.value, ctx, limit)
    if base is None or base.kind != _PAIR:
        return None
    return _Kind(_COMPONENT_KINDS[index.value], base.result)


def _concat_kind(
    expr: ast.BinOp, ctx: _Context, limit: tuple[int, int]
) -> _Kind | None:
    if not isinstance(expr.op, ast.Add) or not _is_newline_literal(expr.right):
        return None
    return _line_from(_expr_kind(expr.left, ctx, limit))


def _fstring_kind(
    expr: ast.JoinedStr, ctx: _Context, limit: tuple[int, int]
) -> _Kind | None:
    """One interpolation of a LINE, plus at most a trailing newline."""
    interpolations = [
        value for value in expr.values if isinstance(value, ast.FormattedValue)
    ]
    literals = [
        value for value in expr.values if not isinstance(value, ast.FormattedValue)
    ]
    if len(interpolations) != 1 or len(literals) > 1:
        return None
    if literals and not (
        literals[0] is expr.values[-1] and _is_newline_literal(literals[0])
    ):
        return None
    placeholder = interpolations[0]
    if placeholder.conversion != -1 or placeholder.format_spec is not None:
        return None
    return _line_from(_expr_kind(placeholder.value, ctx, limit))


def _expr_kind(expr: ast.expr, ctx: _Context, limit: tuple[int, int]) -> _Kind | None:
    """What the WHOLE of *expr* is, and which builder call produced it.

    An expression that merely CONTAINS builder output is nothing: that was the
    round-2 hole, and ``f"Authorization: Bearer {line}"`` is exactly the string
    it let through.

    Name resolution walks backwards: a name resolves to its latest binding
    before *limit*, and that binding's own value is then judged with the
    binding's position as the new limit. The limit therefore decreases on
    every step, so a self-reference such as ``line = line`` terminates instead
    of recursing forever.
    """
    if isinstance(expr, ast.Call):
        return _call_kind(expr, ctx, limit)
    if isinstance(expr, ast.Name):
        return _name_kind(expr, ctx, limit)
    if isinstance(expr, ast.Subscript):
        return _component_kind(expr, ctx, limit)
    if isinstance(expr, ast.BinOp):
        return _concat_kind(expr, ctx, limit)
    if isinstance(expr, ast.JoinedStr):
        return _fstring_kind(expr, ctx, limit)
    return None


def _written_value(call: ast.Call) -> ast.expr | None:
    """The expression a write call puts into the file.

    ``os.write(fd, data)`` carries it second; every other write shape carries
    it first. Reading the wrong index would credit an ``os.write`` for its
    file descriptor, which never comes from the builder.
    """
    func = call.func
    is_os_write = (
        isinstance(func, ast.Attribute)
        and func.attr == "write"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )
    index = 1 if is_os_write else 0
    if len(call.args) <= index:
        return None
    return call.args[index]


def _mapping_reference(expr: ast.expr) -> str | None:
    """How a header mapping is referred to, reduced to one comparable name.

    ``headers`` and ``self.headers`` both reduce to ``headers``, so the write
    target and the ``headers=`` argument meet on the same key whichever way
    each is spelled (fix(#1756 codex round 7)). Reducing to the tail is what
    makes that work and is also its limit, stated in the module docstring.
    """
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _container_name(target: ast.expr) -> str | None:
    """The name a subscript is written into, whatever it is called.

    fix(#1756 codex round 4): this used to require "header" in the name, so a
    request-bound ``request_options`` mapping was invisible. The request
    binding decides scope now; this only reports the name so that binding can
    be looked up.
    """
    if not isinstance(target, ast.Subscript):
        return None
    return _mapping_reference(target.value)


def _key_is_judged(key: ast.expr, *, credential_path: bool, outbound: bool) -> bool:
    """Whether a header under *key* is this rule's business."""
    if isinstance(key, ast.Constant):
        if not isinstance(key.value, str):
            return False
        lowered = key.value.lower()
        if lowered in CREDENTIAL_HEADER_KEYS:
            return True
        return credential_path and outbound and lowered not in NON_CREDENTIAL_HEADERS
    # A computed key cannot be read off the AST. On an outbound mapping in the
    # two credential trees that is a violation waiting to happen; elsewhere it
    # is ordinary response-header plumbing.
    return credential_path and outbound


class _HeaderWrite(NamedTuple):
    key: ast.expr
    value: ast.expr


def _header_writes(
    node: ast.AST, *, credential_path: bool, outbound: _Outbound
) -> list[_HeaderWrite]:
    """Every key and value *node* writes into a header mapping."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        if node.value is None:
            return []
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            container = _container_name(target)
            if _key_is_judged(
                target.slice,
                credential_path=credential_path,
                outbound=container is not None and container in outbound.names,
            ):
                return [_HeaderWrite(target.slice, node.value)]
        return []
    if isinstance(node, ast.Dict):
        reaches_a_request = id(node) in outbound.dicts
        return [
            _HeaderWrite(key, value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
            and _key_is_judged(
                key, credential_path=credential_path, outbound=reaches_a_request
            )
        ]
    return []


def _mapping_write_is_clean(write: _HeaderWrite, ctx: _Context) -> bool:
    """A header mapping takes both halves of ONE builder result.

    fix(#1756 codex round 3): ``headers["Authorization"] =
    credential_header_line(pair)`` used to pass, and puts
    ``Authorization: Authorization: Basic ...`` on the wire.
    fix(#1756 codex round 4): and a string-literal key used to pass, so an
    ``X-API-Key`` credential could be sent under ``Authorization``.
    fix(#1756 codex round 5): and the key and value were classified
    independently, so ``headers[first[0]] = second[1]`` paired one call's name
    with another call's credential. The two halves have to be the same answer.
    """
    value = _expr_kind(write.value, ctx, _pos(write.value))
    if value is None or value.kind != _VALUE:
        return False
    key = _expr_kind(write.key, ctx, _pos(write.key))
    if key is None or key.kind != _NAME:
        return False
    return key.result == value.result


class _Scan:
    """What one pass over a module found."""

    def __init__(self) -> None:
        self.unguarded_writes: Counter[tuple[str, str]] = Counter()
        self.unguarded_headers: Counter[tuple[str, str]] = Counter()
        # Every site the walk judged, guarded or not. The coverage control
        # below reads this rather than the unguarded counters, which went
        # empty for the converted modules the moment B2b landed and would
        # otherwise have made the control assert that the fix had not shipped.
        self.seen_headers: Counter[tuple[str, str]] = Counter()
        self.write_sites = 0
        self.header_sites = 0

    def absorb(self, other: _Scan) -> None:
        self.unguarded_writes.update(other.unguarded_writes)
        self.unguarded_headers.update(other.unguarded_headers)
        self.seen_headers.update(other.seen_headers)
        self.write_sites += other.write_sites
        self.header_sites += other.header_sites


class _ScopeFacts(NamedTuple):
    ctx: _Context
    outbound: _Outbound
    writes_a_header_file: bool


def _scope_facts(
    scope: ast.AST, imports: _Imports, module_bindings: dict[str, list[_Binding]]
) -> _ScopeFacts:
    bindings = (
        module_bindings
        if isinstance(scope, ast.Module)
        else _scope_bindings(scope, imports)
    )
    return _ScopeFacts(
        _Context(bindings, module_bindings, imports),
        _outbound_header_mappings(scope),
        _scope_calls(scope, HEADER_DIR_HELPER),
    )


def _scan_module(rel: str, tree: ast.Module) -> _Scan:
    _annotate_parents(tree)
    scan = _Scan()
    credential_path = rel.startswith(CREDENTIAL_PACKAGES)
    imports = _module_imports(tree)
    module_bindings = _scope_bindings(tree, imports)
    facts_cache: dict[int, _ScopeFacts] = {}

    for node in ast.walk(tree):
        is_write = (
            isinstance(node, ast.Call) and _call_name(node.func) in WRITE_CALL_NAMES
        )
        if not is_write and not isinstance(node, (ast.Assign, ast.AnnAssign, ast.Dict)):
            continue

        scope = _enclosing_scope(node, tree)
        facts = facts_cache.get(id(scope))
        if facts is None:
            facts = _scope_facts(scope, imports, module_bindings)
            facts_cache[id(scope)] = facts
        site = (rel, _scope_name(scope))

        if is_write and facts.writes_a_header_file:
            scan.write_sites += 1
            value = _written_value(node)  # type: ignore[arg-type]
            kind = None if value is None else _expr_kind(value, facts.ctx, _pos(value))
            if kind is None or kind.kind != _LINE:
                scan.unguarded_writes[site] += 1

        for write in _header_writes(
            node, credential_path=credential_path, outbound=facts.outbound
        ):
            scan.header_sites += 1
            scan.seen_headers[site] += 1
            if not _mapping_write_is_clean(write, facts.ctx):
                scan.unguarded_headers[site] += 1

    return scan


def _scan_backend() -> _Scan:
    total = _Scan()
    for rel, tree in _app_modules():
        total.absorb(_scan_module(rel, tree))
    return total


def _allowlist_failures(
    found: Counter[tuple[str, str]],
    allowlist: dict[tuple[str, str], tuple[int, str]],
    label: str,
) -> list[str]:
    failures: list[str] = []
    for site, count in sorted(found.items()):
        expected = allowlist.get(site)
        if expected is None:
            failures.append(
                f"{label}: {site[0]}:{site[1]} composes a credential header "
                f"itself ({count} site(s)). Use build_credential_header() and "
                "credential_header_line() from app/core/service_tokens.py."
            )
        elif expected[0] != count:
            failures.append(
                f"{label}: {site[0]}:{site[1]} has {count} unguarded site(s), "
                f"allowlisted for {expected[0]}."
            )
    for site, (expected_count, justification) in sorted(allowlist.items()):
        if not justification.strip():
            failures.append(f"{label}: {site[0]}:{site[1]} has a blank justification.")
        if site not in found:
            failures.append(
                f"{label}: {site[0]}:{site[1]} is allowlisted for "
                f"{expected_count} site(s) and has none left. Delete the entry."
            )
    return failures


def test_header_file_writes_come_from_the_shared_builder() -> None:
    scan = _scan_backend()
    assert scan.write_sites >= MIN_HEADER_FILE_WRITE_SITES, (
        "the walk found no header-file writes at all, so every assertion "
        "about them is vacuous"
    )
    failures = _allowlist_failures(
        scan.unguarded_writes, HEADER_FILE_WRITE_ALLOWLIST, "GDAL header file"
    )
    assert not failures, "\n".join(failures)


def test_credential_headers_come_from_the_shared_builder() -> None:
    scan = _scan_backend()
    assert scan.header_sites >= MIN_CREDENTIAL_HEADER_SITES, (
        "the walk found no credential headers at all, so every assertion "
        "about them is vacuous"
    )
    failures = _allowlist_failures(
        scan.unguarded_headers, CREDENTIAL_HEADER_ALLOWLIST, "credential header"
    )
    assert not failures, "\n".join(failures)


def test_the_walk_actually_covers_the_backend() -> None:
    """The positive control for the two allowlist assertions above."""
    modules = _app_modules()
    assert len(modules) >= MIN_APP_MODULES
    assert any(_scope_calls(tree, HEADER_DIR_HELPER) for _, tree in modules), (
        f"{HEADER_DIR_HELPER}() is called nowhere, so the header-file rule "
        "matches nothing"
    )
    # The scan reaches outside the sources package, which is the gap codex
    # round 1 found: the rule used to be scoped to sources/adapters/ and so
    # never looked at sources/router.py or anything else.
    scan = _scan_backend()
    scanned = {site[0] for site in scan.seen_headers}
    assert "modules/catalog/sources/router.py" in scanned
    assert any(not rel.startswith("modules/catalog/sources/") for rel in scanned)
    # And it still judges the two probe adapters, which are the sites the
    # every-key rule exists for: a header-key credential travels under a name
    # the SERVICE chose, so nothing about the key says it is a credential.
    assert "modules/catalog/sources/adapters/wfs.py" in scanned
    assert "modules/catalog/sources/adapters/ogcapi.py" in scanned


# The import every synthetic module needs, because provenance now requires the
# call to resolve to the real helper.
_POLICY_IMPORT = (
    f"from {POLICY_MODULE} import {CREDENTIAL_BUILDER}, {CREDENTIAL_JOINER}\n"
)


def _scan_synthetic(
    source: str, rel: str | None = None, *, imported: bool = True
) -> _Scan:
    """Run the real predicates over a synthetic module."""
    prelude = _POLICY_IMPORT if imported else ""
    return _scan_module(
        rel or "modules/catalog/sources/synthetic.py", ast.parse(prelude + source)
    )


# ---------------------------------------------------------------------------
# The blessed shapes. Every way lane B2b can write a credential, one test per
# sink, so tightening this gate further has to break a test that says what the
# implementation is allowed to look like.
# ---------------------------------------------------------------------------


def test_guard_every_blessed_file_write_shape_is_clean() -> None:
    """The header-file sink: a LINE, however it is spelled."""
    scan = _scan_synthetic(
        "def f(auth, fd, handle, path):\n"
        "    directory = gdal_header_dir()\n"
        "    pair = build_credential_header(auth)\n"
        "    line = credential_header_line(pair)\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        '    os.write(fd, (line + "\\n").encode())\n'
        "    os.write(fd, credential_header_line(build_credential_header(auth)))\n"
        "    handle.write(line)\n"
        "    handle.writelines(line)\n"
        "    path.write_text(line)\n"
        '    path.write_bytes(f"{line}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 7
    assert not scan.unguarded_writes


def test_guard_every_blessed_mapping_shape_is_clean() -> None:
    """The mapping sink: one result's NAME as the key, its VALUE as the value.

    Five spellings, which is every one B2b can reasonably reach for: subscript
    from the pair, subscript from an unpacking, a dict literal bound to a name,
    a dict literal inline in the request call, and a dict literal merged onto a
    base. The container is deliberately not called "headers" in one of them.
    """
    scan = _scan_synthetic(
        "def f(auth, client, url, base):\n"
        "    pair = build_credential_header(auth)\n"
        "    name, value = build_credential_header(auth)\n"
        "    request_options = {}\n"
        "    request_options[pair[0]] = pair[1]\n"
        "    request_options[name] = value\n"
        "    client.get(url, headers=request_options)\n"
        "    bound = {pair[0]: pair[1]}\n"
        "    client.post(url, headers=bound)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n"
        "    client.stream(url, headers={**base, name: value})\n"
    )
    assert scan.header_sites == 5
    assert not scan.unguarded_headers


def test_guard_the_policy_module_can_be_reached_three_ways() -> None:
    """An alias, a module import, and the fully qualified path all resolve."""
    aliased = _scan_synthetic(
        f"from {POLICY_MODULE} import {CREDENTIAL_BUILDER} as make_header\n"
        "def f(auth, client, url):\n"
        "    pair = make_header(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert aliased.header_sites == 1
    assert not aliased.unguarded_headers

    qualified = _scan_synthetic(
        f"from {POLICY_PACKAGE} import {POLICY_MODULE_TAIL}\n"
        "def f(auth, client, url):\n"
        f"    pair = {POLICY_MODULE_TAIL}.{CREDENTIAL_BUILDER}(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert qualified.header_sites == 1
    assert not qualified.unguarded_headers

    dotted = _scan_synthetic(
        f"import {POLICY_MODULE}\n"
        "def f(auth, client, url):\n"
        f"    pair = {POLICY_MODULE}.{CREDENTIAL_BUILDER}(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert dotted.header_sites == 1
    assert not dotted.unguarded_headers


# ---------------------------------------------------------------------------
# The rejected shapes, one per way the gate could be walked around.
# ---------------------------------------------------------------------------


def test_guard_an_inline_composition_is_flagged() -> None:
    scan = _scan_synthetic(
        "def f(token, fd, client, url):\n"
        "    path = gdal_header_dir()\n"
        '    os.write(fd, f"Authorization: Bearer {token}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = f"Bearer {token}"\n'
        '    client.get(url, headers={"Authorization": f"Bearer {token}"})\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 2
    assert set(scan.unguarded_writes) == {("modules/catalog/sources/synthetic.py", "f")}


def test_guard_a_lookalike_helper_confers_nothing() -> None:
    """fix(#1756 codex round 5): the call has to BE the shared function.

    A same-named local helper, a same-named attribute on some other object,
    and no import at all each validate nothing, so none of them may buy the
    provenance that exists because one function validates the inputs.
    """
    shadowed = _scan_synthetic(
        "def build_credential_header(auth):\n"
        '    return ("Authorization", auth)\n'
        "def f(auth, fd, client, url):\n"
        "    directory = gdal_header_dir()\n"
        "    pair = build_credential_header(auth)\n"
        "    os.write(fd, credential_header_line(pair))\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n"
    )
    assert sum(shadowed.unguarded_writes.values()) == 1
    assert sum(shadowed.unguarded_headers.values()) == 1

    other_module = _scan_synthetic(
        "def f(auth, other, client, url):\n"
        f"    pair = other.{CREDENTIAL_BUILDER}(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n"
    )
    assert sum(other_module.unguarded_headers.values()) == 1

    unimported = _scan_synthetic(
        "def f(auth, client, url):\n"
        "    pair = build_credential_header(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert sum(unimported.unguarded_headers.values()) == 1


def test_guard_a_shadowed_module_alias_confers_nothing() -> None:
    """fix(#1756 codex round 6): the base needs the same check as the name.

    ``from app.core import service_tokens as policy`` is authoritative right
    up until something else in the scope is also called ``policy``, at which
    point ``policy.build_credential_header(...)`` is whatever that object
    returns. The blessed twin is the same module with nothing shadowing it.
    """
    alias_import = f"from {POLICY_PACKAGE} import {POLICY_MODULE_TAIL} as policy\n"
    call = f"    pair = policy.{CREDENTIAL_BUILDER}(auth)\n"

    unshadowed = _scan_synthetic(
        alias_import
        + "def f(auth, client, url):\n"
        + call
        + "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert unshadowed.header_sites == 1
    assert not unshadowed.unguarded_headers

    by_parameter = _scan_synthetic(
        alias_import
        + "def f(auth, policy, client, url):\n"
        + call
        + "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert by_parameter.header_sites == 1
    assert sum(by_parameter.unguarded_headers.values()) == 1

    by_assignment = _scan_synthetic(
        alias_import + "def f(auth, impostor, client, url):\n"
        "    policy = impostor\n"
        + call
        + "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert by_assignment.header_sites == 1
    assert sum(by_assignment.unguarded_headers.values()) == 1

    # The fully qualified spelling resolves through its root name, so that
    # name is checked too.
    shadowed_root = _scan_synthetic(
        f"import {POLICY_MODULE}\n"
        "def f(auth, app, client, url):\n"
        f"    pair = {POLICY_MODULE}.{CREDENTIAL_BUILDER}(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert shadowed_root.header_sites == 1
    assert sum(shadowed_root.unguarded_headers.values()) == 1


def test_guard_a_namespace_import_is_not_read_as_a_shadow() -> None:
    """``import app.core.config`` beside the policy import is not a rebinding.

    The root name it binds is a package, and a package cannot be the impostor
    the shadow check is looking for. Reading it as one would reject a
    correctly written module.
    """
    scan = _scan_synthetic(
        f"import {POLICY_MODULE}\n"
        "import app.core.config\n"
        "def f(auth, client, url):\n"
        f"    pair = {POLICY_MODULE}.{CREDENTIAL_BUILDER}(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n",
        imported=False,
    )
    assert scan.header_sites == 1
    assert not scan.unguarded_headers


def test_guard_rebinding_the_imported_helper_confers_nothing() -> None:
    """A local rebinding of the imported name is a shadow like any other."""
    scan = _scan_synthetic(
        "def f(auth, impostor, client, url):\n"
        "    build_credential_header = impostor\n"
        "    pair = build_credential_header(auth)\n"
        "    client.get(url, headers={pair[0]: pair[1]})\n"
    )
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_two_builder_results_cannot_be_mixed() -> None:
    """fix(#1756 codex round 5): one call's name, another call's credential.

    Both halves are genuine builder output and the pairing is still wrong: the
    header goes out under a name that belongs to a different result.
    """
    scan = _scan_synthetic(
        "def f(first_auth, second_auth, client, url):\n"
        "    first = build_credential_header(first_auth)\n"
        "    second = build_credential_header(second_auth)\n"
        "    headers = {}\n"
        "    headers[first[0]] = second[1]\n"
        "    client.get(url, headers=headers)\n"
        "    client.post(url, headers={first[0]: second[1]})\n"
        "    client.put(url, headers={first[0]: first[1]})\n"
    )
    # The third site is the same shape from ONE result, so this fails if the
    # result identity is doing the rejecting and passes vacuously if nothing
    # resolves at all.
    assert scan.header_sites == 3
    assert sum(scan.unguarded_headers.values()) == 2


def test_guard_the_joiner_alone_confers_nothing() -> None:
    """fix(#1756 codex round 1): the joiner only concatenates.

    Crediting a bare ``credential_header_line(...)`` would let an
    unvalidated value through under a builder-shaped name.
    """
    scan = _scan_synthetic(
        "def f(token, fd):\n"
        "    path = gdal_header_dir()\n"
        '    line = credential_header_line(("Authorization", token))\n'
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = credential_header_line(("X", token))\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_double_prefix_around_a_builder_line_is_flagged() -> None:
    """fix(#1756 codex round 2): the case the module docstring promises.

    ``line`` really did come from the builder, and the f-string still writes
    ``Authorization: Bearer Authorization: Basic <blob>``. A rule that asks
    whether the expression MENTIONS builder output passes this.
    """
    scan = _scan_synthetic(
        "def f(auth, fd):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, f"Authorization: Bearer {line}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = f"Bearer {line}"\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_joined_line_in_mapping_position_is_flagged() -> None:
    """fix(#1756 codex round 3): the wire header would carry the name twice.

    ``credential_header_line`` output under a header key sends
    ``Authorization: Authorization: Basic <blob>``. The mapping sink takes the
    pair's VALUE component and nothing else.
    """
    scan = _scan_synthetic(
        "def f(auth, client, url):\n"
        "    pair = build_credential_header(auth)\n"
        "    headers = {}\n"
        "    headers[pair[0]] = credential_header_line(pair)\n"
        "    client.get(url, headers=headers)\n"
        "    other = credential_header_line(pair)\n"
        '    client.get(url, headers={"Authorization": other})\n'
    )
    assert scan.header_sites == 2
    assert sum(scan.unguarded_headers.values()) == 2


def test_guard_a_whole_pair_in_mapping_position_is_flagged() -> None:
    """A tuple under a header key is not a header value."""
    scan = _scan_synthetic(
        "def f(auth, client, url):\n"
        "    pair = build_credential_header(auth)\n"
        '    headers["Authorization"] = pair\n'
        '    client.get(url, headers={"Authorization": build_credential_header(auth)})\n'
    )
    assert sum(scan.unguarded_headers.values()) == 2


def test_guard_a_literal_key_beside_a_builder_value_is_flagged() -> None:
    """fix(#1756 codex round 4): the two halves have to come from one answer.

    ``headers["Authorization"] = pair[1]`` looks careful and sends an
    ``X-API-Key`` credential under ``Authorization`` whenever the pair is a
    header-key one. The key must be the builder's own name component.
    """
    scan = _scan_synthetic(
        "def f(auth, client, url):\n"
        "    pair = build_credential_header(auth)\n"
        "    name, value = build_credential_header(auth)\n"
        "    headers = {}\n"
        '    headers["Authorization"] = pair[1]\n'
        "    client.get(url, headers=headers)\n"
        '    client.post(url, headers={"Authorization": value})\n'
    )
    assert scan.header_sites == 2
    assert sum(scan.unguarded_headers.values()) == 2


def test_guard_a_pair_or_component_in_file_position_is_flagged() -> None:
    """The file wants a finished line, not the pair it was joined from."""
    scan = _scan_synthetic(
        "def f(auth, fd):\n"
        "    directory = gdal_header_dir()\n"
        "    pair = build_credential_header(auth)\n"
        "    os.write(fd, pair)\n"
        "    os.write(fd, pair[1])\n"
        '    os.write(fd, f"{pair[0]}: {pair[1]}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 3
    assert sum(scan.unguarded_writes.values()) == 3


def test_guard_concatenating_an_untrusted_name_is_flagged() -> None:
    """Only a trailing newline may be concatenated onto builder output."""
    scan = _scan_synthetic(
        "def f(auth, fd, untrusted):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, (line + untrusted).encode("ascii"))\n'
        '    headers["Authorization"] = line + untrusted\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_rebinding_after_the_builder_call_revokes_trust() -> None:
    """The latest binding before the use site is the one that counts."""
    scan = _scan_synthetic(
        "def f(auth, fd, untrusted, client, url):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        "    pair = build_credential_header(auth)\n"
        "    headers = {}\n"
        "    line = untrusted\n"
        "    pair = untrusted\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        "    headers[pair[0]] = pair[1]\n"
        "    client.get(url, headers=headers)\n"
    )
    assert scan.write_sites == 1
    assert sum(scan.unguarded_writes.values()) == 1
    assert scan.header_sites == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_second_interpolation_or_a_format_spec_is_flagged() -> None:
    """One interpolation, no conversion, no format spec, no extra literal."""
    scan = _scan_synthetic(
        "def f(auth, fd, extra):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, f"{line}{extra}\\n".encode("ascii"))\n'
        '    os.write(fd, f"{line:>40}\\n".encode("ascii"))\n'
        '    os.write(fd, f"{line!r}\\n".encode("ascii"))\n'
        '    os.write(fd, f"{line}\\n\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 4
    assert sum(scan.unguarded_writes.values()) == 4


def test_guard_a_parameter_carries_no_provenance() -> None:
    """A stated limit, reported rather than passed.

    A finished line arriving as an argument has no lexical provenance, so the
    write is judged rather than trusted. Composing at the write site is the
    fix; widening the rule is not.
    """
    scan = _scan_synthetic(
        "def f(line, fd):\n"
        "    path = gdal_header_dir()\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1


def test_guard_a_second_write_beside_a_builder_one_is_flagged() -> None:
    """An added composition does not ride a clean scope's credit."""
    scan = _scan_synthetic(
        "def f(auth, token, fd, other_fd):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        '    os.write(other_fd, f"X-API-Key: {token}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 2
    assert sum(scan.unguarded_writes.values()) == 1


def test_guard_os_write_reads_the_second_argument() -> None:
    """``os.write(fd, data)`` and ``handle.write(data)`` differ by one index."""
    scan = _scan_synthetic(
        "def f(auth, fd, handle):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        "    handle.write(line)\n"
        "    os.write(fd, line)\n"
    )
    assert scan.write_sites == 2
    assert not scan.unguarded_writes


def test_guard_a_write_outside_the_header_directory_is_not_judged() -> None:
    """The write rule is scoped to the one directory, not to every write.

    Without the ``gdal_header_dir()`` condition this test's module would be a
    violation, and so would every unrelated file write in the backend.
    """
    scan = _scan_synthetic(
        "def f(token, fd):\n"
        '    os.write(fd, f"Authorization: Bearer {token}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 0
    assert not scan.unguarded_writes


def test_guard_a_custom_api_key_header_is_judged_on_the_credential_paths() -> None:
    """fix(#1756 codex round 3): the header-key method's whole point.

    A hand-composed ``X-API-Key`` is a credential in exactly the way an
    ``Authorization`` header is, and the three-name rule could not see it.
    """
    source = (
        "def f(raw, client, url):\n"
        '    headers = {"Accept": "application/json"}\n'
        '    headers["X-API-Key"] = raw\n'
        "    client.get(url, headers=headers)\n"
        '    client.post(url, headers={"Ocp-Apim-Subscription-Key": raw})\n'
    )
    for rel in (
        "modules/catalog/sources/synthetic.py",
        "processing/ingest/synthetic.py",
    ):
        scan = _scan_synthetic(source, rel)
        assert scan.header_sites == 2, rel
        assert sum(scan.unguarded_headers.values()) == 2, rel

    # Outside the credential paths the same shape is not this rule's business:
    # the three credential names stay covered everywhere, a product header
    # does not.
    elsewhere = _scan_synthetic(source, "standards/ogc/synthetic.py")
    assert elsewhere.header_sites == 0


def test_guard_a_mapping_not_called_headers_is_still_judged() -> None:
    """fix(#1756 codex round 4): the request binding decides scope.

    The name filter this replaced meant ``request_options["X-API-Key"] = raw``
    was scanned nowhere at all, even though it reaches the wire.
    """
    scan = _scan_synthetic(
        "def f(raw, client, url):\n"
        "    request_options = {}\n"
        '    request_options["X-API-Key"] = raw\n'
        "    client.get(url, headers=request_options)\n"
    )
    assert scan.header_sites == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_mapping_held_on_an_attribute_is_judged() -> None:
    """fix(#1756 codex round 7): an attribute reaches the wire too.

    ``self.request_options["X-API-Key"] = raw`` with
    ``headers=self.request_options`` was scanned nowhere, because the write
    target was reduced to a name and the request argument was not reduced at
    all. Both sides go through one reducer now, so the two meet.
    """
    hand_composed = _scan_synthetic(
        "def f(self, raw, client, url):\n"
        '    self.request_options["X-API-Key"] = raw\n'
        "    client.get(url, headers=self.request_options)\n"
    )
    assert hand_composed.header_sites == 1
    assert sum(hand_composed.unguarded_headers.values()) == 1

    from_the_builder = _scan_synthetic(
        "def f(self, auth, client, url):\n"
        "    pair = build_credential_header(auth)\n"
        "    self.request_options[pair[0]] = pair[1]\n"
        "    client.get(url, headers=self.request_options)\n"
    )
    assert from_the_builder.header_sites == 1
    assert not from_the_builder.unguarded_headers

    # And a dict literal bound to the attribute is the same mapping.
    literal = _scan_synthetic(
        "def f(self, raw, client, url):\n"
        '    self.request_options = {"X-API-Key": raw}\n'
        "    client.get(url, headers=self.request_options)\n"
    )
    assert literal.header_sites == 1
    assert sum(literal.unguarded_headers.values()) == 1


def test_guard_a_mapping_with_no_request_binding_keeps_the_name_rule() -> None:
    """The fallback, so dropping the name filter loses nothing.

    Without a request call in the scope there is no outbound signal, and the
    three credential names are still judged; a custom key is not.
    """
    scan = _scan_synthetic(
        "def f(raw, token):\n"
        "    options = {}\n"
        '    options["X-API-Key"] = raw\n'
        '    options["Authorization"] = f"Bearer {token}"\n'
        "    return options\n"
    )
    assert scan.header_sites == 1
    assert sum(scan.unguarded_headers.values()) == 1


def test_guard_a_non_credential_header_is_ignored_on_the_credential_paths() -> None:
    """``Accept`` and friends cannot carry a credential.

    The exemption list is what keeps the every-key rule from flagging the
    ``Accept`` header every adapter sets.
    """
    scan = _scan_synthetic(
        "def f(client, url):\n"
        '    headers = {"Accept": "application/json", "Content-Type": "text/xml"}\n'
        '    headers["Accept-Encoding"] = "gzip"\n'
        '    headers["Range"] = "bytes=0-0"\n'
        "    client.get(url, headers=headers)\n"
    )
    assert scan.header_sites == 0


def test_guard_a_response_header_is_not_judged() -> None:
    """Response headers are not this rule's business.

    Everything under processing/export/ and processing/tiles/ passes
    ``headers=`` to Response, StreamingResponse or HTTPException, and none of
    it can carry a credential to a third party.
    """
    scan = _scan_synthetic(
        "def f(etag, body):\n"
        '    response.headers["ETag"] = etag\n'
        '    response.headers["X-GeoLens-Cache-Status"] = "hit"\n'
        '    return Response(body, headers={"X-GeoLens-Band-Count": "3"})\n',
        "processing/tiles/synthetic.py",
    )
    assert scan.header_sites == 0


def test_guard_a_computed_key_is_judged_on_the_credential_path_only() -> None:
    """The anti-evasion half of the key rule, and its limit.

    ``key = "Authorization"`` two lines above a ``headers[key] =`` would
    otherwise be a free pass. Outside the two credential trees the same shape
    is ordinary response-header plumbing (``response.headers[name] = value``
    appears throughout the API) and is left alone.
    """
    source = (
        "def f(token, client, url):\n"
        '    key = "Authorization"\n'
        "    headers = {}\n"
        '    headers[key] = f"Bearer {token}"\n'
        "    client.get(url, headers=headers)\n"
    )
    on_path = _scan_synthetic(source, "modules/catalog/sources/synthetic.py")
    assert sum(on_path.unguarded_headers.values()) == 1

    in_processing = _scan_synthetic(source, "processing/ingest/synthetic.py")
    assert sum(in_processing.unguarded_headers.values()) == 1

    elsewhere = _scan_synthetic(source, "standards/ogc/synthetic.py")
    assert elsewhere.header_sites == 0


def test_guard_a_credential_name_is_judged_everywhere() -> None:
    """The three names need no outbound signal and no credential path.

    This is the half of the rule with no preconditions, which is why it is
    the one that catches a composition in a module nobody thought about.
    """
    scan = _scan_synthetic(
        "def f(token):\n"
        '    anything["X-Esri-Authorization"] = f"Bearer {token}"\n'
        '    return {"Authorization": f"Bearer {token}"}\n',
        "standards/ogc/synthetic.py",
    )
    assert scan.header_sites == 2
    assert sum(scan.unguarded_headers.values()) == 2


def test_guard_a_self_reference_terminates() -> None:
    """``line = line`` resolves to nothing rather than recursing forever.

    The resolution limit strictly decreases on every name lookup, which is
    what makes that true; this is the check on that reasoning.
    """
    scan = _scan_synthetic(
        "def f(fd):\n"
        "    path = gdal_header_dir()\n"
        "    line = line\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1


class TestBuildCredentialHeaderRegistersEverythingItProduces:
    """fix(#1770 round 43 P2).

    `redact_exception_text`/the structlog `_scrub_text` processor used to
    redact a credential only by PATTERN -- a known query-parameter name, or
    userinfo -- so a reflection into the URL path, or into a query key
    neither recognises, reached a log line untouched. `register_credential_
    secret` (`core/service_tokens.py`) closes that by having the single
    producer of a credential header, `build_credential_header`, register the
    exact line it composes, so an exact-value scrub finds it regardless of
    where it gets reflected.

    That guarantee only holds while EVERY branch that returns a real pair
    also registers it. This is the structural half of that: it does not read
    the synthetic fixtures the guard tests above use (those exercise the
    OUTBOUND-header-mapping question, a different rule from this file's
    docstring), it reads `build_credential_header`'s own real source and
    counts the two shapes against each other. A regression that adds a
    fourth branch, or that adds a `return` without the matching
    registration, changes one count without the other and fails here rather
    than waiting for a review round to notice the new reflection surface.
    """

    @staticmethod
    def _build_credential_header_function() -> ast.FunctionDef:
        source = (APP_ROOT / "core" / "service_tokens.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "build_credential_header"
            ):
                return node
        raise AssertionError(
            "build_credential_header not found -- positive control failed"
        )

    @staticmethod
    def _pair_assignments(func: ast.FunctionDef) -> list[ast.Assign]:
        """Every ``<name> = (<header-name>, <header-value>)`` assignment.

        Each producing branch assigns the composed pair to a name (`pair =
        (...)`) rather than returning a tuple literal directly, so this is
        the shape that actually identifies "a branch that composed a
        header" -- not the `Return` node, which just holds the name.
        """
        return [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple)
        ]

    def test_every_pair_producing_branch_registers_its_own_secret(self) -> None:
        func = self._build_credential_header_function()

        pair_assignments = self._pair_assignments(func)
        registration_calls = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register_credential_secret"
        ]

        # Positive control: neither list is vacuous. `build_credential_header`
        # has three methods that compose a real pair (bearer, basic, header
        # key) -- a change to that shape is real news, not a broken walk.
        assert len(pair_assignments) >= 3, pair_assignments
        assert registration_calls, (
            "no register_credential_secret call found -- positive control failed"
        )
        assert len(registration_calls) == len(pair_assignments), (
            "build_credential_header composes a header pair on "
            f"{len(pair_assignments)} branch(es) but registers a secret on "
            f"{len(registration_calls)} -- every branch that composes a "
            "header must also register it (see this class's docstring)."
        )

    def test_each_composed_pair_is_registered_immediately_after_it_is_assigned(
        self,
    ) -> None:
        """Not just equal counts: paired one-for-one, in source order.

        Catches the shape where a stray extra registration call and a stray
        unregistered pair both exist and cancel out in the count above --
        e.g. a copy-pasted branch that registers a DIFFERENT pair than the
        one it just assigned.
        """
        func = self._build_credential_header_function()
        checked = 0
        for assign in self._pair_assignments(func):
            assert len(assign.targets) == 1 and isinstance(assign.targets[0], ast.Name)
            pair_name = assign.targets[0].id

            body = _enclosing_body(func, assign)
            index = body.index(assign)
            assert index + 1 < len(body), "a pair assignment has nothing after it"
            registration = body[index + 1]
            assert (
                isinstance(registration, ast.Expr)
                and isinstance(registration.value, ast.Call)
                and isinstance(registration.value.func, ast.Name)
                and registration.value.func.id == "register_credential_secret"
            ), (
                "the statement immediately after a pair assignment is not a "
                "register_credential_secret(...) call"
            )
            # And it has to register THIS pair, via `credential_header_line`,
            # not some other name left over from a copy-pasted branch.
            (arg,) = registration.value.args
            assert (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "credential_header_line"
                and len(arg.args) == 1
                and isinstance(arg.args[0], ast.Name)
                and arg.args[0].id == pair_name
            ), (
                f"register_credential_secret after `{pair_name} = (...)` does "
                f"not register `credential_header_line({pair_name})`"
            )

            assert index + 2 < len(body), "a registered pair has no return after it"
            returned = body[index + 2]
            assert (
                isinstance(returned, ast.Return)
                and isinstance(returned.value, ast.Name)
                and returned.value.id == pair_name
            ), f"the statement after registering `{pair_name}` does not return it"
            checked += 1
        assert checked >= 3, checked


def _enclosing_body(func: ast.FunctionDef, target: ast.AST) -> list[ast.stmt]:
    """The flat statement list directly containing *target* within *func*."""
    for node in ast.walk(func):
        body = getattr(node, "body", None)
        if isinstance(body, list) and any(isinstance(item, ast.stmt) for item in body):
            if target in body:
                return body
    raise AssertionError("target statement not found in any enclosing body")
