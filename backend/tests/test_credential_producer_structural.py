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

The two shapes it watches, over the whole ``backend/app/`` tree:

1. **Header-file writes.** Any write in a scope that calls
   ``gdal_header_dir()``. That directory exists for exactly one thing, the
   0600 ``GDAL_HTTP_HEADER_FILE``, so a write in a scope that located it is a
   credential line by construction.
2. **Credential header writes.** Any ``headers[...] = ...`` keyed by a
   credential header name, and any dict literal with such a key. The dict
   literal is the same composition one line up, and leaving it out would make
   the rule free to evade.

   Under ``modules/catalog/sources/`` and ``processing/``, a header
   assignment with a NON-constant key is judged too, because that is where a
   service credential is actually handled and ``headers[key] = ...`` with
   ``key = "Authorization"`` two lines above would otherwise walk straight
   through. Elsewhere in the tree a computed key is left alone: response
   headers are set that way all over the API (``response.headers[name] =
   value``), and judging those would be noise, not coverage.

   fix(#1756 codex round 1): this rule used to be scoped to
   ``sources/adapters/``, which missed the composition in ``sources/router.py``
   entirely. Scope now comes from the key, not from the directory.

**Provenance is a whole-expression rule.** fix(#1756 codex round 2): it used
to ask whether the written expression MENTIONED builder output anywhere, which
passed ``f"Authorization: Bearer {line}"`` for a builder-derived ``line``, the
exact double-prefix string this module exists to prevent. It now asks whether
the whole expression is one of these projections of builder output, and
nothing else is accepted:

- ``build_credential_header(...)`` itself.
- a name whose latest binding BEFORE the use site is an allowed expression, so
  a later ``line = anything_else`` revokes it, and a parameter, loop target or
  ``with`` target carries no provenance at all.
- ``credential_header_line(<allowed>)``, one positional argument. The joiner
  on its own only concatenates the pair it is handed, so
  ``credential_header_line(("Authorization", value))`` is not allowed.
- ``<allowed> + "\\n"``, or an f-string whose single interpolation is
  ``<allowed>`` with no conversion and no format spec, and whose only literal
  part, if any, is a trailing newline.
- ``.encode()`` or ``.encode("ascii")`` on an allowed expression.
- ``<allowed pair>[0]`` and ``[1]``, and a name unpacked from an allowed pair,
  for the header-dict case.

Any other operator, any extra literal text, a second interpolation, or a
format spec fails. A credential that arrives as a parameter has no lexical
provenance and is therefore reported: the fix is to compose it at the write
site, not to widen this rule.

Both allowlists are asserted EXACT in both directions and by count, so an
entry whose site disappears fails loudly instead of going stale. Four of the
five credential-header entries are the compositions lane B2b deletes; this
test is what tells it when the last one is gone.

WHAT THIS DOES NOT CLAIM, in the same spirit as the Rule-2 guard. It is a
lexical rule, not dataflow. A line built in one function and written in
another, a header dict assembled through ``update()`` from a value computed
elsewhere, and a binding made under one branch of an ``if`` and used under the
other are all outside what an AST rule can answer. Binding order is read from
source position, which is the straight-line answer and not a control-flow one.
False alarms are cheap and visible; a silent miss is the failure that matters,
so anything the resolver cannot classify is reported.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The single producer, and the joiner that turns its pair into a line. Only
# the producer confers provenance; see the module docstring.
CREDENTIAL_BUILDER = "build_credential_header"
CREDENTIAL_JOINER = "credential_header_line"

# The helper that locates the 0600 header-file directory. A scope that calls
# it is writing a credential header or nothing at all.
HEADER_DIR_HELPER = "gdal_header_dir"

# Where a computed header key is judged as well as a literal one: the two
# trees that handle a service credential.
DYNAMIC_KEY_PACKAGES = ("modules/catalog/sources/", "processing/")

# Write calls, by exact name. Substring matching would sweep in unrelated
# helpers: `_tenant_writer_subprocess_env` contains "write".
WRITE_CALL_NAMES = frozenset({"write", "writelines", "write_text", "write_bytes"})

# Header names that carry a credential, compared case-insensitively because
# HTTP field names are case-insensitive.
CREDENTIAL_HEADER_KEYS = frozenset(
    {"authorization", "proxy-authorization", "x-esri-authorization"}
)

# Every allowlist entry is (module, scope) -> (exact count, justification).
HEADER_FILE_WRITE_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/ingest/ogr.py", "run_ogr2ogr_service"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes "
        "`Authorization: Bearer <token>` inline for the commit path",
    ),
    ("modules/catalog/sources/preview.py", "run_service_preview"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the same line "
        "inline for the preview path",
    ),
}

CREDENTIAL_HEADER_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("modules/catalog/sources/adapters/wfs.py", "probe_wfs"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the bearer header "
        "for the WFS GetCapabilities probe",
    ),
    ("modules/catalog/sources/adapters/ogcapi.py", "probe_ogcapi"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the bearer header "
        "for the OGC API Features landing-page probe",
    ),
    ("modules/catalog/sources/router.py", "_fetch_ogcapi_collection_srid"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the bearer header "
        "for the collection CRS fallback fetch, which is the same service "
        "credential the two probe adapters carry",
    ),
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


def _scope_calls(scope: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == name
        for node in ast.walk(scope)
    )


def _pos(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


class _Binding(NamedTuple):
    """One binding of a name inside a scope.

    ``value`` is None when the binding is something this rule cannot judge: a
    parameter, a loop target, an import. Such a binding is RECORDED rather
    than skipped, because it has to revoke an earlier builder binding.
    """

    pos: tuple[int, int]
    value: ast.expr | None


def _iter_scope_nodes(scope: ast.AST):
    """Every node in *scope*, without descending into a nested callable."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED_SCOPES):
            continue
        stack.extend(ast.iter_child_nodes(node))


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


def _opaque_names(node: ast.AST) -> list[str]:
    """Names *node* binds to something this rule cannot judge."""
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, _NESTED_SCOPES) and not isinstance(node, ast.Lambda):
        return [node.name]
    return []


def _scope_bindings(scope: ast.AST) -> dict[str, list[_Binding]]:
    """Every name binding in *scope*, ordered by source position."""
    bindings: dict[str, list[_Binding]] = defaultdict(list)

    def record(target: ast.expr, value: ast.expr | None) -> None:
        if isinstance(target, ast.Name):
            bindings[target.id].append(_Binding(_pos(target), value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            # A component of an allowed pair is allowed, which is what makes
            # `name, value = build_credential_header(auth)` usable.
            for element in target.elts:
                record(element, value)
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
        for name in _opaque_names(node):
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


def _is_newline_literal(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value == "\n"


def _is_line_fstring(
    expr: ast.JoinedStr, bindings: dict[str, list[_Binding]], limit: tuple[int, int]
) -> bool:
    """One interpolation of an allowed expression, plus a trailing newline."""
    interpolations = [
        value for value in expr.values if isinstance(value, ast.FormattedValue)
    ]
    literals = [
        value for value in expr.values if not isinstance(value, ast.FormattedValue)
    ]
    if len(interpolations) != 1 or len(literals) > 1:
        return False
    if literals and not (
        literals[0] is expr.values[-1] and _is_newline_literal(literals[0])
    ):
        return False
    placeholder = interpolations[0]
    if placeholder.conversion != -1 or placeholder.format_spec is not None:
        return False
    return _is_builder_projection(placeholder.value, bindings, limit)


def _is_pair_component(
    expr: ast.Subscript, bindings: dict[str, list[_Binding]], limit: tuple[int, int]
) -> bool:
    index = expr.slice
    if not isinstance(index, ast.Constant) or isinstance(index.value, bool):
        return False
    if index.value not in (0, 1):
        return False
    return _is_builder_projection(expr.value, bindings, limit)


def _is_encode_call(
    expr: ast.Call, bindings: dict[str, list[_Binding]], limit: tuple[int, int]
) -> bool:
    if not isinstance(expr.func, ast.Attribute) or expr.keywords:
        return False
    if len(expr.args) > 1:
        return False
    if expr.args and not (
        isinstance(expr.args[0], ast.Constant) and expr.args[0].value == "ascii"
    ):
        return False
    return _is_builder_projection(expr.func.value, bindings, limit)


def _is_builder_projection(
    expr: ast.expr, bindings: dict[str, list[_Binding]], limit: tuple[int, int]
) -> bool:
    """Whether the WHOLE of *expr* is an allowed projection of builder output.

    The allowed shapes are enumerated in the module docstring. Anything else
    is a violation, including an expression that merely CONTAINS builder
    output: that was the round-2 hole, and ``f"Authorization: Bearer {line}"``
    is exactly the string it let through.

    Name resolution walks backwards: a name resolves to its latest binding
    before *limit*, and that binding's own value is then judged with the
    binding's position as the new limit. The limit therefore decreases on
    every step, so a self-reference such as ``line = line`` terminates instead
    of recursing forever.
    """
    if isinstance(expr, ast.Call):
        name = _call_name(expr.func)
        if name == CREDENTIAL_BUILDER:
            return True
        if name == CREDENTIAL_JOINER:
            return (
                len(expr.args) == 1
                and not expr.keywords
                and _is_builder_projection(expr.args[0], bindings, limit)
            )
        if name == "encode":
            return _is_encode_call(expr, bindings, limit)
        return False
    if isinstance(expr, ast.Name):
        binding = _binding_before(bindings, expr.id, limit)
        if binding is None or binding.value is None:
            return False
        return _is_builder_projection(binding.value, bindings, binding.pos)
    if isinstance(expr, ast.BinOp):
        return (
            isinstance(expr.op, ast.Add)
            and _is_newline_literal(expr.right)
            and _is_builder_projection(expr.left, bindings, limit)
        )
    if isinstance(expr, ast.JoinedStr):
        return _is_line_fstring(expr, bindings, limit)
    if isinstance(expr, ast.Subscript):
        return _is_pair_component(expr, bindings, limit)
    return False


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


def _header_container_name(target: ast.expr) -> str | None:
    if not isinstance(target, ast.Subscript):
        return None
    container = target.value
    if isinstance(container, ast.Name):
        name = container.id
    elif isinstance(container, ast.Attribute):
        name = container.attr
    else:
        return None
    return name if "header" in name.lower() else None


def _is_credential_key(key: ast.expr, allow_dynamic_key: bool) -> bool:
    if isinstance(key, ast.Constant):
        return (
            isinstance(key.value, str) and key.value.lower() in CREDENTIAL_HEADER_KEYS
        )
    # A computed key cannot be read off the AST. In the two trees that handle
    # a service credential that is a violation waiting to happen, so it is
    # judged; everywhere else it is ordinary response-header plumbing.
    return allow_dynamic_key


def _credential_header_values(node: ast.AST, allow_dynamic_key: bool) -> list[ast.expr]:
    """Every value *node* writes under a credential header name.

    Two shapes: a subscript assignment into a name that reads as a header
    mapping, and a dict literal keyed by a credential header name.
    """
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        if node.value is None:
            return []
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if _header_container_name(target) is None:
                continue
            assert isinstance(target, ast.Subscript)
            if _is_credential_key(target.slice, allow_dynamic_key):
                return [node.value]
        return []
    if isinstance(node, ast.Dict):
        return [
            value
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None and _is_credential_key(key, allow_dynamic_key=False)
        ]
    return []


class _Scan:
    """What one pass over a module found."""

    def __init__(self) -> None:
        self.unguarded_writes: Counter[tuple[str, str]] = Counter()
        self.unguarded_headers: Counter[tuple[str, str]] = Counter()
        self.write_sites = 0
        self.header_sites = 0

    def absorb(self, other: _Scan) -> None:
        self.unguarded_writes.update(other.unguarded_writes)
        self.unguarded_headers.update(other.unguarded_headers)
        self.write_sites += other.write_sites
        self.header_sites += other.header_sites


def _scan_module(rel: str, tree: ast.Module) -> _Scan:
    _annotate_parents(tree)
    scan = _Scan()
    allow_dynamic_key = rel.startswith(DYNAMIC_KEY_PACKAGES)
    bindings_cache: dict[int, dict[str, list[_Binding]]] = {}
    header_dir_cache: dict[int, bool] = {}

    for node in ast.walk(tree):
        is_write = (
            isinstance(node, ast.Call) and _call_name(node.func) in WRITE_CALL_NAMES
        )
        header_values = _credential_header_values(node, allow_dynamic_key)
        if not is_write and not header_values:
            continue

        scope = _enclosing_scope(node, tree)
        bindings = bindings_cache.get(id(scope))
        if bindings is None:
            bindings = _scope_bindings(scope)
            bindings_cache[id(scope)] = bindings
        site = (rel, _scope_name(scope))

        if is_write:
            writes_a_header = header_dir_cache.get(id(scope))
            if writes_a_header is None:
                writes_a_header = _scope_calls(scope, HEADER_DIR_HELPER)
                header_dir_cache[id(scope)] = writes_a_header
            if writes_a_header:
                scan.write_sites += 1
                value = _written_value(node)  # type: ignore[arg-type]
                if value is None or not _is_builder_projection(
                    value, bindings, _pos(value)
                ):
                    scan.unguarded_writes[site] += 1

        for value in header_values:
            scan.header_sites += 1
            if not _is_builder_projection(value, bindings, _pos(value)):
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
    scanned = {site[0] for site in _scan_backend().unguarded_headers}
    assert "modules/catalog/sources/router.py" in scanned
    assert any(not rel.startswith("modules/catalog/sources/") for rel in scanned)


def _scan_synthetic(source: str, rel: str | None = None) -> _Scan:
    """Run the real predicates over a synthetic module."""
    return _scan_module(
        rel or "modules/catalog/sources/synthetic.py", ast.parse(source)
    )


def test_guard_an_inline_composition_is_flagged() -> None:
    scan = _scan_synthetic(
        "def f(token, fd):\n"
        "    path = gdal_header_dir()\n"
        '    os.write(fd, f"Authorization: Bearer {token}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = f"Bearer {token}"\n'
        '    other = {"Authorization": f"Bearer {token}"}\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 2
    assert set(scan.unguarded_writes) == {("modules/catalog/sources/synthetic.py", "f")}


def test_guard_a_builder_composition_is_clean() -> None:
    scan = _scan_synthetic(
        "def f(auth, fd):\n"
        "    path = gdal_header_dir()\n"
        "    pair = build_credential_header(auth)\n"
        "    line = credential_header_line(pair)\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        "    headers[pair[0]] = pair[1]\n"
        '    other = {"Authorization": credential_header_line(pair)}\n'
    )
    assert scan.write_sites == 1
    assert scan.header_sites == 2
    assert not scan.unguarded_writes
    assert not scan.unguarded_headers


def test_guard_the_other_allowed_projections_are_clean() -> None:
    """The shapes B2b may reasonably write, spelled out.

    Concatenation instead of an f-string, an unencoded line, and the pair
    unpacked into two names.
    """
    scan = _scan_synthetic(
        "def f(auth, fd, handle):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, (line + "\\n").encode())\n'
        "    handle.write(line)\n"
        "    name, value = build_credential_header(auth)\n"
        "    headers[name] = value\n"
    )
    assert scan.write_sites == 2
    assert scan.header_sites == 1
    assert not scan.unguarded_writes
    assert not scan.unguarded_headers


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
        "def f(auth, fd, untrusted):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        "    line = untrusted\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = line\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
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


def test_guard_a_computed_key_is_judged_on_the_credential_path_only() -> None:
    """The anti-evasion half of the key rule, and its limit.

    ``key = "Authorization"`` two lines above a ``headers[key] =`` would
    otherwise be a free pass. Outside the two credential trees the same shape
    is ordinary response-header plumbing (``response.headers[name] = value``
    appears throughout the API) and is left alone.
    """
    source = (
        "def f(token):\n"
        '    key = "Authorization"\n'
        '    headers[key] = f"Bearer {token}"\n'
    )
    on_path = _scan_synthetic(source, "modules/catalog/sources/synthetic.py")
    assert sum(on_path.unguarded_headers.values()) == 1

    in_processing = _scan_synthetic(source, "processing/ingest/synthetic.py")
    assert sum(in_processing.unguarded_headers.values()) == 1

    elsewhere = _scan_synthetic(source, "standards/ogc/synthetic.py")
    assert elsewhere.header_sites == 0


def test_guard_a_non_credential_header_is_not_judged() -> None:
    """Response headers are not this test's business.

    Judging every header assignment would flag the CORS, CSP and ETag writes
    all over the API, which have nothing to do with a credential.
    """
    scan = _scan_synthetic(
        "def f(response, etag):\n"
        '    response.headers["ETag"] = etag\n'
        '    response.headers["Cache-Control"] = "no-store"\n'
        '    other = {"Accept": "application/json"}\n',
        "processing/tiles/synthetic.py",
    )
    assert scan.header_sites == 0


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
